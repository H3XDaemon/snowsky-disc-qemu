"""Application projection. All playback mutations use the Controller facade."""
import threading
from collections import OrderedDict
import secrets
import time

from controller import DeviceConfig, DiscSession, QueueItem, Track
from controller.models import PlaybackSource
from controller.catalog import CatalogReader
from controller.fiio_http import HTTPClient


class BusyError(ValueError):
    pass


class Device:
    demo = False

    def __init__(self, config: DeviceConfig, *, session=None, http=None, configured=True):
        self.config = config
        self.configured = configured
        self.session = session or DiscSession(config)
        self.http = http or HTTPClient(config.host, config.http_port, config.timeout)
        self.lock = threading.Lock()
        self.state_guard = threading.RLock()
        self.generation_base = 0
        self.volume = None
        self.sources = OrderedDict()
        self.source_guard = threading.RLock()
        self.catalogue = None

    def _source(self, kind, rows, name='', artist=''):
        expected = tuple(QueueItem(row['pos'], row['name'], row['author']) for row in rows)
        return self._remember(dict(kind=kind, expected=expected, name=name, artist=artist,
            generation=self.session.snapshot().generation + self.generation_base, created=time.monotonic()))

    def _remember(self, source):
        token = secrets.token_urlsafe(18)
        with self.source_guard:
            self.sources[token] = source
            if len(self.sources) > 32:
                self.sources.popitem(last=False)
        return token

    def clear_sources(self):
        with self.source_guard:
            self.sources.clear()

    def _selection(self, value):
        if not isinstance(value, str) or ':' not in value:
            raise ValueError('a displayed selection is required')
        token, number = value.rsplit(':', 1)
        with self.source_guard:
            source = self.sources.get(token)
        if (not source or source['generation'] != self.session.snapshot().generation + self.generation_base
                or time.monotonic() - source['created'] > 600):
            raise ValueError('displayed source expired; refresh before selecting')
        index = int(number)
        if source.get('kind') == 'snapshot':
            if not 0 <= index < len(source['ordinals']):
                raise ValueError('position outside displayed snapshot')
            head, snapshot = self.catalogue.snapshot()
            if head['generation'] != source['snapshot']:
                raise ValueError('saved collection changed; refresh before selecting')
            album, rows, position = snapshot.selection(source['ordinals'][index], artist=source['artist'] or None)
            return {'kind': 'album', 'name': album, 'artist': source['artist'],
                    'expected': tuple(QueueItem(r['pos'], r['name'], r['author']) for r in rows)}, position
        if source.get('kind') == 'genre':
            head, _ = self.catalogue.snapshot()
            if source['snapshot'] != head['generation']:
                raise ValueError('Saved genre changed; refresh before selecting')
        if not 0 <= index < len(source['expected']):
            raise ValueError('position outside the displayed source')
        return source, index

    def __enter__(self):
        self.session.__enter__()
        return self

    def __exit__(self, *args):
        self.session.__exit__(*args)

    def state(self):
        with self.state_guard:
            value = self.session.snapshot().to_dict()
            value['generation'] += self.generation_base
            if value['connection'] != 'ready':
                self.volume = None
            return {**value, 'demo': False, 'volume': self.volume,
                    'busy': self.lock.locked(), 'endpoint': self.config.host if self.configured else '',
                    'tcp_port': self.config.tcp_port, 'http_port': self.config.http_port}

    def sound_settings(self):
        generation = self.state()['generation']
        result = self.session.sound_settings(expected_generation=self.protocol_generation(generation))
        return {**result.to_dict(), 'generation': generation}

    def protocol_generation(self, displayed):
        with self.state_guard:
            if type(displayed) is not int or displayed != self.state()['generation']:
                raise ValueError('Connection changed; refresh before sending')
            return displayed - self.generation_base

    def configure(self, config, generation):
        """Explicitly replace the sole owner; old browser selections never carry over."""
        if not self.lock.acquire(False):
            raise BusyError('Another operation is in progress. Nothing was queued.')
        try:
            self.protocol_generation(generation)
            if config != self.config:
                replacement = DiscSession(config)
                self.session.__exit__(None, None, None)
                with self.state_guard:
                    self.generation_base += self.session.snapshot().generation + 1
                    self.session, self.config = replacement, config
                    self.http = HTTPClient(config.host, config.http_port, config.timeout)
                    self.volume = None
                    self.clear_sources()
                    self.session.__enter__()
            with self.state_guard:
                self.configured = True
            self.session.connect()
            return {'status': 'observed', 'state': self.state()}
        finally:
            self.lock.release()

    def _rows(self, category, **filters):
        return CatalogReader(self.http, max_tracks=10000, max_requests=60).rows(category, **filters)

    def browse(self, kind, name='', artist='', genre=''):
        if self.catalogue:
            with self.state_guard:
                cached = self.browse_snapshot(kind, name, artist, genre)
            if cached is not None:
                return cached
        if genre:
            raise ValueError('Synchronize the collection before browsing genres')
        if not self.lock.acquire(False):
            raise BusyError('Another operation is in progress. Nothing was queued.')
        try:
            with self.session.operation() as client:
                client.scan_guard()
                if kind == 'album_info':
                    rows = (self._rows('artist/album/song', artist=artist, album=name) if artist
                            else self._rows('album/song', album=name))
                    client.scan_guard()
                    return {'generation': self.state()['generation'], 'count': len(rows),
                            'artists': list(dict.fromkeys(row['author'] for row in rows if row['author']))}
                categories = {'albums': 'album', 'artists': 'artist', 'tracks': 'all/song',
                              'favorites': 'love/song', 'playlists': 'custom'}
                if kind in categories:
                    rows = self._rows(categories[kind])
                    item_type = {'albums': 'album', 'artists': 'artist', 'playlists': 'playlist'}.get(kind, 'track')
                elif kind == 'album':
                    rows = (self._rows('artist/album/song', artist=artist, album=name) if artist
                            else self._rows('album/song', album=name))
                    item_type = 'track'
                elif kind == 'artist':
                    rows, item_type = self._rows('artist/album', artist=name), 'album'
                elif kind == 'playlist':
                    playlists = self._rows('custom')
                    matches = [r for r in playlists if r['name'] == name]
                    if len(matches) != 1:
                        raise ValueError('Playlist changed or its name is ambiguous. Refresh the library.')
                    rows = self._rows('custom/song', src_list_id=matches[0]['pos'])
                    if self._rows('custom') != playlists:
                        raise ValueError('Playlists changed while reading. Refresh the library.')
                    item_type = 'track'
                else:
                    raise ValueError('Unsupported library view')
                client.scan_guard()
                token = self._source(kind, rows, name, artist) if item_type == 'track' else None
                return {'kind': kind, 'name': name, 'items': [
                    {'id': str(r['pos']), 'title': r['name'], 'artist': r.get('author', ''),
                     'count': r.get('count'), 'type': item_type,
                     'scope_artist': name if kind == 'artist' else None,
                     'selection': f"{token}:{r['pos']}" if token else None,
                     'playable': kind in ('album', 'tracks', 'favorites', 'playlist'),
                     'album': name if kind == 'album' else None,
                     'editable': kind in ('tracks', 'playlist') or (kind == 'album' and not artist),
                     'art': None, 'duration': None} for r in rows]}
        finally:
            self.lock.release()

    def browse_snapshot(self, kind, name, artist, genre=''):
        from experiments.disc_web.backend.catalogue import CACHED_VIEWS
        if kind not in CACHED_VIEWS:
            return None
        head, snapshot = self.catalogue.snapshot()
        if snapshot is None:
            return None
        if genre:
            if artist or kind not in ('albums', 'tracks', 'album'):
                raise ValueError('Unsupported combined genre scope')
            return self.browse_genre(snapshot, kind, name, genre)
        metadata = self.catalogue.metadata.rows(head['generation'])
        def observed(row):
            fields = metadata.get(row['id'], {})
            duration = fields.get('duration_ms')
            digest = fields.get('artwork')
            return dict(metadata=fields.get('metadata', {}), duration=duration / 1000 if duration is not None else None,
                        art='/api/artwork/' + digest if digest else None)
        token = None
        if kind in ('tracks', 'album'):
            rows = snapshot.tracks(album=name if kind == 'album' else None,
                                   artist=artist or None)
            token = self._remember(dict(kind='snapshot', snapshot=head['generation'],
                ordinals=tuple(row['ordinal'] for row in rows), artist=artist,
                generation=self.state()['generation'], created=time.monotonic()))
            items = [dict(id=row['id'], title=row['title'], artist=row['artist'], album=row['album'],
                type='track', selection=f'{token}:{i}', playable=True, editable=not artist,
                **observed(row)) for i, row in enumerate(rows)]
        else:
            rows = snapshot.groups('artist' if kind == 'artists' else 'album',
                                   artist=name if kind == 'artist' else None)
            items = [dict(id=str(i), title=row['name'], count=row['count'], artists=row['artists'],
                artist=row['artists'][0] if len(row['artists']) == 1 else '',
                type='artist' if kind == 'artists' else 'album', art=None,
                scope_artist=name if kind == 'artist' else None) for i, row in enumerate(rows)]
            if kind != 'artists':
                artwork = {}
                for row in snapshot.tracks(artist=name if kind == 'artist' else None):
                    image = observed(row)['art']
                    if image:
                        artwork.setdefault(row['album'], image)
                for item in items:
                    item['art'] = artwork.get(item['title'])
        return dict(kind=kind, name=name, items=items, snapshot=head['generation'],
                    genres=self.genre_groups(snapshot))

    @staticmethod
    def genre_groups(snapshot):
        return None if snapshot.genres is None else [
            {key: group[key] for key in ('name', 'count', 'available')} for group in snapshot.genres]

    def browse_genre(self, snapshot, kind, name, genre):
        group = snapshot.genre(genre)
        album = name if kind == 'album' else None
        rows = snapshot.genre_rows(genre, album)
        token = self._remember(dict(kind='genre', name=genre, album=album,
            expected=tuple(QueueItem(r['pos'], r['name'], r['author']) for r in rows),
            snapshot=snapshot.generation, generation=self.state()['generation'], created=time.monotonic()))
        if kind == 'albums':
            items = []
            for i, entry in enumerate(group['albums']):
                artists = list(dict.fromkeys(r['author'] for r in entry['tracks'] if r['author']))
                items.append(dict(id=str(i), type='album', title=entry['name'], artists=artists,
                    artist=artists[0] if len(artists) == 1 else '', count=len(entry['tracks']),
                    scope_genre=genre, art=None))
        else:
            items = []
            memberships = {}
            for entry in group['albums']:
                for member in entry['tracks']:
                    memberships.setdefault((member['name'], member['author']), []).append(entry['name'])
            for row in rows:
                # A genre row is a separate positional observation, not a catalog ID.
                # Only a unique album membership supplies navigation; no artwork join.
                albums = memberships.get((row['name'], row['author']), [])
                observed_album = album if album is not None else albums[0] if len(albums) == 1 else None
                items.append(dict(id=f"genre:{row['pos']}", type='track', title=row['name'],
                    artist=row['author'], album=observed_album, scope_genre=genre,
                    selection=f"{token}:{row['pos']}", playable=True, editable=False,
                    art=None, duration=None))
        return dict(kind=kind, name=name, items=items, snapshot=snapshot.generation,
                    genres=self.genre_groups(snapshot), genre_selection=f'{token}:0' if rows else None)

    def queue(self):
        if not self.lock.acquire(False):
            raise BusyError('Another operation is in progress. Nothing was queued.')
        try:
            result = self.session.queue().to_dict()
            if result.get('queue'):
                rows = result['queue']['items']
                token = self._source('queue', [dict(pos=r['position'], name=r['title'], author=r['artist']) for r in rows])
                for row in rows:
                    row.update(selection=f"{token}:{row['position']}", playable=True)
            return result
        finally:
            self.lock.release()

    def cover(self, expected=None):
        if not self.lock.acquire(False):
            raise BusyError('Another operation is in progress.')
        try:
            with self.session.operation() as client:
                if self.catalogue:
                    return self.catalogue.metadata.capture(client, expected)
                return self.http.cover()
        finally:
            self.lock.release()

    def action(self, body):
        if not self.lock.acquire(False):
            raise BusyError('Another operation is in progress. Nothing was queued.')
        try:
            action = body.get('action')
            if not isinstance(action, str):
                raise ValueError('A named action is required')
            if action in ('connect', 'disconnect'):
                if action == 'connect' and not self.configured:
                    raise ValueError('Choose a player address before connecting')
                if 'generation' in body:
                    self.protocol_generation(body['generation'])
                getattr(self.session, action)()
                return {'status': 'observed', 'state': self.state()}
            state = self.state()
            if (state['connection'] != 'ready' or type(body.get('generation')) is not int
                    or body['generation'] != state['generation']):
                raise ValueError('Connection changed. Refresh the state before a new command.')
            if action in ('pause', 'resume', 'next', 'previous'):
                result = self.session.control(action)
            elif action == 'favorite':
                result = self.session.set_favorite(body.get('value'))
            elif action == 'volume':
                value = body.get('value')
                if type(value) is not int or not 0 <= value <= 120:
                    raise ValueError('Volume must be an integer in 0..120')
                result = self.session.set_volume(value)
            elif action == 'sound_setting':
                result = self.session.set_sound_setting(body.get('name'), body.get('value'),
                    expected=body.get('expected'), expected_generation=self.protocol_generation(body['generation']))
            elif action == 'mode':
                result = self.session.set_play_mode(body.get('value'))
            elif action == 'genre':
                source, _ = self._selection(body.get('selection'))
                if source['kind'] != 'genre':
                    raise ValueError('A displayed genre selection is required')
                result = self.session.play_genre(source['name'], album=source['album'], expected=source['expected'])
            elif action == 'album':
                album = body.get('name')
                if not isinstance(album, str) or not album or len(album) > 1024:
                    raise ValueError('An album name is required')
                artist = body.get('artist')
                options = {}
                if body.get('snapshot') is not None:
                    if not self.catalogue:
                        raise ValueError('Saved collection is unavailable')
                    head, snapshot = self.catalogue.snapshot()
                    if not snapshot or head['generation'] != body['snapshot']:
                        raise ValueError('Saved collection changed; refresh before playing')
                    tracks = snapshot.tracks(album=album, artist=artist)
                    options['expected'] = tuple(QueueItem(i, row['title'], row['artist'])
                                                for i, row in enumerate(tracks))
                result = (self.session.play_artist(artist, album=album, **options) if artist is not None
                          else self.session.play_album(album, **options))
            elif action == 'playlist':
                source, _ = self._selection(body.get('selection'))
                if source['kind'] != 'playlist' or source['name'] != body.get('name'):
                    raise ValueError('playlist selection scope changed')
                result = self.session.play_playlist(source['name'], expected=source['expected'])
            elif action == 'seek':
                expected = body.get('expected')
                fields = {'title', 'artist', 'album', 'queue_position', 'path', 'duration_ms'}
                allowed = set(Track.__dataclass_fields__)
                if not isinstance(expected, dict) or not fields <= set(expected) <= allowed or type(body.get('source')) is not int:
                    raise ValueError('displayed track and source are required')
                result = self.session.seek(body.get('position_ms'), expected=Track(**expected),
                                           source=PlaybackSource(body['source']))
            elif action == 'artist':
                result = self.session.play_artist(body.get('name'))
            elif action in ('track', 'queue', 'playlist_add', 'playlist_remove'):
                source, index = self._selection(body.get('selection'))
                expected = source['expected']
                if action == 'track' and source['kind'] == 'genre':
                    result = self.session.play_genre(source['name'], album=source['album'], index=index,
                                                    expected=source['expected'])
                elif action == 'queue' and source['kind'] == 'queue':
                    result = self.session.play_queue_index(index, expected=expected)
                elif action == 'track' and source['kind'] == 'album':
                    result = (self.session.play_artist(source['artist'], album=source['name'], index=index, expected=expected)
                              if source['artist'] else self.session.play_album(source['name'], index=index, expected=expected))
                elif action == 'track' and source['kind'] in ('tracks', 'favorites'):
                    result = self.session.play_catalog_track(index, favorites=source['kind'] == 'favorites', expected=expected)
                elif action == 'track' and source['kind'] == 'playlist':
                    result = self.session.play_playlist(source['name'], index=index, expected=expected)
                elif action == 'playlist_add' and (source['kind'] == 'tracks' or (source['kind'] == 'album' and not source['artist'])):
                    result = self.session.add_playlist_track(body.get('name'), index, expected=expected,
                        album=source['name'] if source['kind'] == 'album' else None)
                elif action == 'playlist_remove' and source['kind'] == 'playlist':
                    result = self.session.remove_playlist_track(source['name'], index, expected=expected)
                else:
                    raise ValueError('selection scope does not match the requested operation')
            elif action == 'playlist_create':
                result = self.session.create_playlist(body.get('name'))
            elif action == 'playlist_rename':
                result = self.session.rename_playlist(body.get('name'), body.get('new_name'))
            else:
                raise ValueError('Unsupported operation')
            if result.volume is not None:
                self.volume = result.volume
            return result.to_dict()
        finally:
            self.lock.release()
