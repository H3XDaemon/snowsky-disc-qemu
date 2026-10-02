"""Shared reviewed commands for sequential and persistent TCP transports.

The persistent transport adds narrow sound commands separately, never raw reset/PEQ.
"""
from typing import Any, Protocol
from controller.compatibility import require
from controller.wire import settings_snapshot, volume_command, favorite_command, frame, hex_value, play_mode_value
from controller.fiio_library import artist_command, verify_artist, album_command, verify_album


class Sender(Protocol):
    def sendall(self, data: bytes) -> None: ...


class ReviewedCommands:
    socket: Sender

    def request(self, tag: str, payload: bytes | str = b'', *, expected: str | None = None) -> bytes:
        raise NotImplementedError

    def _queue_page(self) -> dict[str, Any]:
        raise ValueError('persistent queue selection requires fresh HTTP preflight')

    def settings(self) -> dict[str, Any]:
        return settings_snapshot(self.request('0501'))

    def play_pause(self) -> None:
        # 0201 -> FUN_004e477c -> FUN_00424b2c(0, action); action 0 toggles.
        self.socket.sendall(frame('0201', '0000'))

    def next_track(self) -> None:
        self.socket.sendall(frame('0201', '0001'))

    def previous_track(self) -> None:
        # At >10 seconds stock restarts this track instead of moving backwards.
        self.socket.sendall(frame('0201', '0002'))

    def set_play_mode(self, mode: int) -> None:
        self.socket.sendall(frame('0102', hex_value(mode, 4)))

    def play_mode(self) -> int:
        # Stock 0105 reads the mode but replies with a102, not a105.
        return play_mode_value(self.request('0105', expected='a102'))

    def play_queue_index(self, index: int, *, http: Any = None) -> None:
        """Select a zero-based position in the current queue, with a fresh bounds check.

        The queue can still change between query and selection; Link has no revision
        token. Never replay this command after reconnecting or reuse a cached count.
        """
        position = hex_value(index)
        # HTTP permits a caller to guard the exact row immediately before send.
        # The original TCP-only API retains its fresh queue-count query.
        page = (http.catalog('curlist/song', offset=index, limit=1) if http is not None
                else self._queue_page())
        if index >= page['total'] or (http is not None and len(page['items']) != 1):
            raise ValueError('position outside the current queue')
        self.socket.sendall(frame('0100', position + '0000'))

    def set_favorite(self, value: bool) -> None:
        """Set the current track favorite flag; callers must verify identity/readback."""
        self.socket.sendall(frame(*favorite_command(value)))

    def set_volume(self, value: int) -> None:
        self.socket.sendall(frame(*volume_command(value)))

    def play_artist(self, artist: str, index: int | None = None, *, album: str | None = None, http: Any) -> None:
        """Play an artist, or an artist-scoped album/track, after fresh HTTP checks.

        Indexed type-7 selection requires an album. HTTP must target this device;
        serialize edits and never replay an uncertain selection.
        """
        command = artist_command(artist, index, album)
        version = self.settings().get('soc_version')
        require(version, 'artist_playback')
        verify_artist(http, artist, index, album)
        self.socket.sendall(frame(*command))

    def play_genre(self, genre: str, index: int | None = None, *, album: str | None = None, http: Any) -> None:
        from controller.fiio_library import genre_command, verify_genre
        command = genre_command(genre, index, album)
        require(self.settings().get('soc_version'), 'genre_playback')
        verify_genre(http, genre, index, album)
        self.socket.sendall(frame(*command))

    def play_album(self, album: str, index: int | None = None, *, http: Any) -> None:
        """Play a complete named album after fresh source bounds verification."""
        command = album_command(album, index)
        version = self.settings().get('soc_version')
        require(version, 'album_playback')
        verify_album(http, album, index)
        self.socket.sendall(frame(*command))

    def play_playlist(self, position: int, index: int | None = None, *, http: Any, expected_name: str) -> None:
        from controller.fiio_playlist import playlist_command, verify_playlist
        command = playlist_command(position, index, expected_name)
        require(self.settings().get('soc_version'), 'playlist_playback')
        verify_playlist(http, position, index, expected_name)
        self.socket.sendall(frame(*command))

    def play_catalog_track(self, index: int, *, favorites: bool = False, http: Any) -> None:
        position = hex_value(index)
        if type(favorites) is not bool:
            raise ValueError('favorites must be a boolean')
        require(self.settings().get('soc_version'), 'catalog_playback')
        category = 'love/song' if favorites else 'all/song'
        page = http.catalog(category, offset=index, limit=1)
        if index >= page['total'] or len(page['items']) != 1:
            raise ValueError('position outside current catalog')
        self.socket.sendall(frame('0100', position + ('0006' if favorites else '0001')))

    def seek(self, position_ms: int) -> None:
        self.socket.sendall(frame('0103', hex_value(position_ms, 0x7fffffff, 8)))
