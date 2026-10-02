"""Curated fictional UI fixture. No sockets, files, speech or real device writes."""
from copy import deepcopy
import threading
import time


ALBUMS = [
    ('Afterglow', 'Northline', 'Electronic', ['First Light', 'Afterglow', 'Soft Focus', 'Somewhere, Slowly', 'Stay a Little Longer']),
    ('Тихий океан', 'Берег', 'Indie', ['Волны', 'На другом берегу', 'Тихий океан', 'Тёплый ветер']),
    ('Blue Hours', 'Mira Sol', 'Jazz', ['Blue Hours', 'Almost Sunday', 'Window Seat', 'An Open Door']),
    ('Inner Space', 'Forma', 'Ambient', ['Orbit', 'Weightless', 'Inner Space', 'Still Here']),
    ('Velvet Season', 'June & the City', 'Soul', ['Velvet Season', 'Slow Motion', 'Golden', 'Home Again']),
    ('Patterns', 'Parallel Lines', 'Electronic', ['Patterns', 'Side by Side', 'In Between', 'A New Shape']),
    ('Лето внутри', 'Поля', 'Indie', ['Лето внутри', 'Вишнёвый сад', 'Там, где свет', 'По пути домой']),
    ('Daybreak', 'Sundial', 'Alternative', ['Daybreak', 'Wide Open', 'Good Things', 'Better Days']),
]


class Demo:
    demo = True

    def __init__(self):
        self.lock = threading.RLock()
        self.albums = []
        self.tracks = []
        for i, (title, artist, genre, songs) in enumerate(ALBUMS):
            art = f'/art/cover-{i}.svg'
            self.albums.append(dict(id=str(i), title=title, artist=artist, genre=genre,
                                    type='album', art=art, count=len(songs), year=2026 - i % 3))
            for j, song in enumerate(songs):
                self.tracks.append(dict(id=f'{i}-{j}', title=song, artist=artist, album=title,
                                        type='track', art=art, metadata=dict(sample_rate_hz=44100 if i%2 else 96000,
                                            bit_depth=16 if i%2 else 24, channels=2, genre=genre, track_number=j+1), duration=187 + (i * 31 + j * 23) % 150))
        self.playlists = [dict(id='0', title='Медленное утро', artist='Время для себя', type='playlist', art='/art/cover-2.svg', count=8),
                          dict(id='1', title='После заката', artist='Город звучит иначе', type='playlist', art='/art/cover-0.svg', count=7)]
        self.queue_items = deepcopy(self.tracks[:5])
        self.selected = 1
        self.playing = False
        self.position = 42
        self.updated = time.monotonic()
        self.volume = 38
        self.mode = 'list_once'
        self.likes = {'0-1', '2-0', '4-2', '6-1'}
        self.members = {self.playlists[0]['title']: deepcopy(self.tracks[::4]),
                        self.playlists[1]['title']: deepcopy(self.tracks[1::5])}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def state(self):
        with self.lock:
            track = self.queue_items[self.selected]
            elapsed = self.position + (time.monotonic() - self.updated if self.playing else 0)
            elapsed = min(elapsed, track['duration'])
            if elapsed == track['duration']:
                self.position, self.playing = elapsed, False
            return {'demo': True, 'connection': 'ready', 'generation': 1, 'enabled': True,
                    'busy': False, 'endpoint': 'Demo collection', 'volume': self.volume,
                    'playback': {'state': 'playing' if self.playing else 'paused',
                                 'track': {**track, 'queue_position': self.selected},
                                 'position_ms': int(elapsed * 1000), 'mode': self.mode,
                                 'favorite': track['id'] in self.likes}}

    def browse(self, kind, name='', artist='', genre=''):
        with self.lock:
            if kind == 'albums':
                items = self.albums
            elif kind == 'artists':
                items = [dict(a, title=a['artist'], type='artist', count=1) for a in self.albums]
            elif kind == 'tracks':
                items = self.tracks
            elif kind == 'favorites':
                items = [t for t in self.tracks if t['id'] in self.likes]
            elif kind == 'playlists':
                items = self.playlists
            elif kind == 'album':
                items = [t for t in self.tracks if t['album'] == name and (not artist or t['artist'] == artist)]
            elif kind == 'artist':
                items = [dict(a, scope_artist=name) for a in self.albums if a['artist'] == name]
            elif kind == 'playlist':
                if name not in self.members:
                    raise ValueError('playlist not found')
                items = self.members[name]
            else:
                raise ValueError('Unsupported library view')
            if genre:
                if artist or kind not in ('albums', 'album', 'tracks'):
                    raise ValueError('Unsupported combined genre scope')
                if kind == 'albums':
                    scoped = []
                    for item in items:
                        members = [t for t in self.tracks if t['album'] == item['title']
                                   and t['artist'] == item['artist'] and t['metadata']['genre'] == genre]
                        if members:
                            scoped.append(dict(item, count=len(members), genre=genre, scope_genre=genre))
                    items = scoped
                else:
                    items = [dict(item, scope_genre=genre) for item in items
                             if item.get('metadata', {}).get('genre') == genre]
            genres = [dict(name=g, available=True, count=sum(t['metadata']['genre'] == g for t in self.tracks))
                      for g in dict.fromkeys(t['metadata']['genre'] for t in self.tracks)]
            return deepcopy({'kind': kind, 'name': name, 'items': items, 'genres': genres,
                             'genre_selection': 'demo:0' if genre and items else None})

    def queue(self):
        with self.lock:
            return deepcopy({'status': 'observed', 'queue': {'items': [dict(t, position=i) for i, t in enumerate(self.queue_items)],
                                                           'selected_position': self.selected}})

    def action(self, body):
        with self.lock:
            action = body.get('action')
            if not isinstance(action, str):
                raise ValueError('A named action is required')
            current = self.state()
            if action == 'pause':
                self.position = current['playback']['position_ms'] / 1000
                self.playing = False
            elif action == 'resume':
                if self.position >= self.queue_items[self.selected]['duration']:
                    self.position = 0
                self.playing = True
                self.updated = time.monotonic()
            elif action == 'seek':
                value = body.get('position_ms')
                if type(value) is not int or not 0 <= value < current['playback']['track']['duration'] * 1000:
                    raise ValueError('seek outside track duration')
                if body.get('expected') != current['playback']['track']:
                    raise ValueError('displayed demo track changed')
                self.position, self.updated = value // 1000, time.monotonic()
            elif action in ('next', 'previous'):
                self.selected = (self.selected + (1 if action == 'next' else -1)) % len(self.queue_items)
                self.position, self.updated = 0, time.monotonic()
            elif action == 'volume':
                if type(body.get('value')) is not int or not 0 <= body['value'] <= 120:
                    raise ValueError('Volume must be in 0..120')
                self.volume = body['value']
            elif action == 'mode':
                if body.get('value') not in ('list_once', 'random', 'repeat_one', 'repeat_list', 'single_once'):
                    raise ValueError('Unsupported play mode')
                self.mode = body['value']
            elif action == 'favorite':
                if type(body.get('value')) is not bool:
                    raise ValueError('Favorite must be boolean')
                track_id = self.queue_items[self.selected]['id']
                self.likes.add(track_id) if body['value'] else self.likes.discard(track_id)
            elif action in ('album', 'artist', 'track', 'queue', 'playlist', 'genre'):
                if action == 'queue':
                    index = body.get('index')
                    if type(index) is not int or not 0 <= index < len(self.queue_items):
                        raise ValueError('Invalid queue position')
                    self.selected = index
                else:
                    field = {'album': 'album', 'artist': 'artist', 'track': 'id'}.get(action)
                    tracks = (self.browse('album' if body.get('album') else 'tracks', body.get('album', ''), genre=body.get('genre', ''))['items'] if action == 'genre'
                              else self.browse('playlist', body.get('name'))['items'] if action == 'playlist'
                              else self.browse('album', body.get('name'), body.get('artist', ''))['items'] if action == 'album'
                              else [t for t in self.tracks if t[field] == body.get('name')])
                    if not tracks:
                        raise ValueError('Selection is empty')
                    index = 0
                    if action == 'track' and body.get('source_view') in ('album', 'tracks', 'favorites', 'playlist'):
                        tracks = self.browse(body['source_view'], body.get('source_name', ''), body.get('source_artist', ''), body.get('source_genre', ''))['items']
                        index = next((i for i, row in enumerate(tracks) if row['id'] == body.get('name')), None)
                        if index is None:
                            raise ValueError('track left displayed source')
                    self.queue_items, self.selected = deepcopy(tracks), index
                self.position, self.updated, self.playing = 0, time.monotonic(), True
            elif action in ('connect', 'disconnect'):
                raise ValueError('Demo is isolated. Start without --demo to connect a DISC.')
            elif action.startswith('playlist_'):
                name = body.get('name')
                if not isinstance(name, str) or not name.strip() or len(name) > 100:
                    raise ValueError('playlist name is required')
                if action == 'playlist_create':
                    if name in self.members:
                        raise ValueError('playlist already exists')
                    self.members[name] = []
                    self.playlists.append(dict(id=str(len(self.playlists)), title=name, type='playlist', count=0, art=None))
                elif action == 'playlist_rename':
                    new = body.get('new_name')
                    if name not in self.members or not isinstance(new, str) or not new.strip() or new in self.members:
                        raise ValueError('playlist name is unavailable')
                    self.members[new] = self.members.pop(name)
                    next(p for p in self.playlists if p['title'] == name)['title'] = new
                elif action == 'playlist_add':
                    track = next((t for t in self.tracks if t['id'] == body.get('track')), None)
                    if name not in self.members or not track or any(t['id'] == track['id'] for t in self.members[name]):
                        raise ValueError('track is unavailable or already in the playlist')
                    self.members[name].append(deepcopy(track))
                elif action == 'playlist_remove':
                    if name not in self.members or not any(t['id'] == body.get('track') for t in self.members[name]):
                        raise ValueError('playlist track changed')
                    self.members[name] = [t for t in self.members[name] if t['id'] != body['track']]
                else:
                    raise ValueError('unsupported playlist edit')
                for playlist in self.playlists:
                    playlist['count'] = len(self.members[playlist['title']])
            else:
                raise ValueError('Unsupported operation')
            return {'status': 'confirmed', 'demo': True, 'mutation_attempted': False}
