"""Persistent playlist edits: fresh names/positions, one HTTP write, readback."""
from collections import Counter

from controller.catalog import CatalogChanged, CatalogReader, verify_expected
from controller.compatibility import require_client
from controller.fiio_http import name_header


def edit(config, client, http, action, name, *, new_name=None, index=None,
         category=None, album=None, expected=None):
    if action not in ('create', 'rename', 'add', 'remove'):
        raise ValueError('unsupported playlist edit')
    name_header(name)
    if action == 'rename':
        name_header(new_name)
    if action in ('add', 'remove'):
        if type(index) is not int or not 0 <= index <= 65535 or expected is None:
            raise ValueError('a displayed source and bounded index are required')
    if action == 'add' and (category not in ('all/song', 'album/song')
                            or (category == 'album/song') != (album is not None)):
        raise ValueError('unsupported playlist source scope')
    require_client(client, 'playlist_edit')
    client.wait_for_mutation()
    reader = CatalogReader(http, page_size=config.page_size, max_tracks=config.max_tracks,
                           max_requests=config.max_requests)

    def stable(category, **filters):
        rows = reader.rows(category, **filters)
        if rows != reader.rows(category, **filters):
            raise CatalogChanged('playlist source is changing')
        return rows

    lists = stable('custom')
    names = [row['name'] for row in lists]
    if action == 'create':
        if name in names:
            raise ValueError('a playlist with this name already exists')
        expected_names = Counter(names + [name])
        def callback():
            return http.create_playlist(name)
    else:
        matches = [row for row in lists if row['name'] == name]
        if len(matches) != 1:
            raise CatalogChanged('playlist name is missing or ambiguous; refresh')
        position = matches[0]['pos']
        if action == 'rename':
            if name == new_name:
                return {'status': 'already_satisfied', 'mutation_attempted': False}
            if new_name in names:
                raise ValueError('a playlist with the new name already exists')
            expected_names = Counter(new_name if value == name else value for value in names)
            def callback():
                return http.rename_playlist(position, new_name)
        else:
            members = stable('custom/song', src_list_id=position)
            if action == 'add':
                filters = {'album': album} if album is not None else {}
                source = stable(category, **filters)
                verify_expected(source, expected)
                if index >= len(source):
                    raise ValueError('position outside the displayed source')
                target = source[index]
                if any((row['name'], row['author']) == (target['name'], target['author']) for row in members):
                    raise ValueError('matching playlist metadata already exists; duplicate identity is ambiguous')
                wanted = members + [target]
                def callback():
                    return http.add_selection_to_playlist(position, [[index, index]],
                        expected_name=name, category=category, **filters)
            else:
                verify_expected(members, expected)
                if index >= len(members):
                    raise ValueError('position outside the displayed playlist')
                wanted = members[:index] + members[index + 1:]
                def callback():
                    return http.remove_from_playlist(position, [[index, index]])

    # The final read catches positional shifts before any HTTP mutation attempt.
    if reader.rows('custom') != lists:
        raise CatalogChanged('playlist positions changed before the edit')
    if action in ('add', 'remove'):
        if reader.rows('custom/song', src_list_id=position) != members:
            raise CatalogChanged('playlist membership changed before the edit')
        if action == 'add':
            verify_expected(reader.rows(category, **filters), expected)
    client.scan_guard()
    if client.closed.is_set():
        raise ConnectionError('connection ended before the playlist edit')
    if client.mutation_attempted:
        raise RuntimeError('playlist edit replay refused')
    client.pacer.attempted()
    client.mutation_attempted = True
    client.attempted_phases.add('selection')
    callback()
    # HTTP 200 is not evidence of success. No retry follows any failure below.
    after = stable('custom')
    if action in ('create', 'rename'):
        if Counter(row['name'] for row in after) != expected_names:
            raise CatalogChanged('playlist name change not confirmed; edit was not retried')
    else:
        if [(row['pos'], row['name']) for row in after] != [(row['pos'], row['name']) for row in lists]:
            raise CatalogChanged('playlist positions changed after the edit')
        actual = stable('custom/song', src_list_id=position)
        def keys(rows):
            return Counter((row['name'], row['author']) for row in rows)
        if keys(actual) != keys(wanted):
            raise CatalogChanged('playlist membership change not confirmed; edit was not retried')
    client.scan_guard()
    return {'status': 'confirmed', 'mutation_attempted': True, 'outcome': 'playlist_' + action}
