"""Read-only V2.57 catalog observation. Positional rows are snapshot identities."""
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str
    position: int
    raw: dict


from controller.catalog import CatalogChanged, CatalogReader as PageReader


class CatalogReader(PageReader):
    def read_once(self, *, include_genres=False):
        root = self.rows('all/song')
        groups = self.rows('album')
        names = [r['name'] for r in groups]
        if len(set(names)) != len(names):
            raise ValueError('duplicate album selectors cannot be resolved safely')
        tracks = []
        for album in names:
            for row in self.rows('album/song', album=album):
                tracks.append(Track(row['name'], row['author'], album, row['pos'], row))
                if len(tracks) > self.max_tracks:
                    raise ValueError('catalog exceeds track limit')
        # Compare multiplicities: same title/artist is NOT proof of one recording.
        if Counter((r['name'], r['author']) for r in root) != Counter((t.title, t.artist) for t in tracks):
            raise CatalogChanged('album membership does not match the complete root catalog')
        if include_genres:
            return root, groups, tracks, self.read_genres(tracks)
        return root, groups, tracks

    def read_stable(self, *, include_genres=False):
        first = self.read_once(include_genres=include_genres)
        if first != self.read_once(include_genres=include_genres):
            raise CatalogChanged('catalog changed between full reads; retry once the device is idle')
        self.genres = first[3] if include_genres else None
        return first[2]

    def read_genres(self, tracks):
        groups = self.rows('style')
        names = [row['name'] for row in groups]
        if len(set(names)) != len(names):
            raise CatalogChanged('duplicate genre selectors cannot be resolved safely')
        result, observed = [], Counter()
        catalog = Counter((t.title, t.artist, t.album) for t in tracks)
        for group in groups:
            name = group['name']
            entry = dict(name=name, count=group.get('count'), available=False)
            result.append(entry)
            # Reserved tokens are not aliases for localized stock unknown labels.
            if name == 'unknown_style':
                continue
            songs = self.rows('style/song', style=name)
            if not songs:
                # Some stock unknown-label groups cannot be resolved literally.
                # Retain the group as unavailable, never map or translate it.
                continue
            if type(group.get('count')) is int and len(songs) != group['count']:
                raise CatalogChanged('genre count changed during observation')
            albums = self.rows('style/album', style=name)
            if len({row['name'] for row in albums}) != len(albums):
                raise CatalogChanged('duplicate genre album selectors')
            members, membership = [], Counter()
            for album in albums:
                rows = self.rows('style/album/song', style=name, album=album['name'])
                members.append(dict(name=album['name'], tracks=rows))
                membership.update((r['name'], r['author'], album['name']) for r in rows)
            if Counter((r['name'], r['author']) for r in songs) != Counter(
                    (title, artist) for title, artist, album in membership.elements()):
                raise CatalogChanged('genre album membership changed')
            observed.update(membership)
            if observed - catalog:
                raise CatalogChanged('genre membership exceeds the catalog')
            entry.update(available=True, count=len(songs), tracks=songs, albums=members)
        return result
