#!/usr/bin/env python3
"""Stock DISC HTTP API (12103; emulator direct port 12113).

Mutations return the raw reply, not a success assertion: stock can return empty
200 on failure. Serialize operations and verify with a subsequent read. No retry,
recursive deletion, reset, or firmware access is provided. See docs/protocol/http-api.md.
"""
import argparse
from dataclasses import dataclass
import http.client
import json
from pathlib import Path, PurePosixPath
from urllib.parse import quote


CATEGORIES = frozenset(('all/song', 'artist', 'artist/song', 'artist/album',
    'artist/album/song', 'album', 'album/song', 'style', 'style/song',
    'style/album', 'style/album/song', 'love/song', 'curlist/song',
    'custom', 'custom/song'))


def integer(value, maximum=2**31 - 1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f'expected integer in 0..{maximum}')
    return str(value)


def name_header(value):
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError('expected nonempty name without edge whitespace or control characters')
    encoded = quote(value, safe='')
    # The firmware copies the header into 256 bytes BEFORE percent decoding.
    if len(encoded) > 255:
        raise ValueError('encoded name exceeds the firmware header buffer (255 bytes)')
    return encoded


def sd_path(value, *, child=False):
    if not isinstance(value, str) or not value.startswith('/') or any(ord(c) < 32 for c in value):
        raise ValueError('expected absolute SD path')
    parts = value.rstrip('/').split('/')
    if any(p in ('', '.', '..') for p in parts[1:]) or '\\' in value:
        raise ValueError('ambiguous SD path')
    value = value.rstrip('/')
    if value != '/tmp/sdcard' and not value.startswith('/tmp/sdcard/'):
        raise ValueError('path must be inside /tmp/sdcard')
    if child and value == '/tmp/sdcard':
        raise ValueError('operation requires an SD child path')
    if len(value.encode('utf-8')) > 1023:
        raise ValueError('SD path exceeds client limit')
    return value


def range_body(ranges):
    if not isinstance(ranges, (list, tuple)) or not ranges or len(ranges) > 100:
        raise ValueError('expected 1..100 inclusive position ranges')
    previous = -1
    for pair in ranges:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('each range is [first, last]')
        first, last = pair
        integer(first)
        integer(last)
        if first <= previous or last < first or last - first >= 1000000:
            raise ValueError('ranges must be ordered, nonoverlapping and bounded')
        previous = last
    return json.dumps(ranges, separators=(',', ':')).encode('ascii')


@dataclass
class Reply:
    status: int
    headers: dict
    body: bytes

    def json(self):
        return json.loads(self.body)

    def page(self):
        # /dir/ conflates missing and empty directories in a blank 200 reply.
        items = self.json() if self.body else []
        if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            raise ValueError('expected a JSON list of records')
        total = self.headers.get('total-num')
        total = int(total) if total is not None else None
        if total is not None and (total < 0 or len(items) > total):
            raise ValueError('invalid page total')
        return dict(total=total, items=items,
                    mark=int(self.headers['mark-pos']) if 'mark-pos' in self.headers else None)


class HTTPClient:
    def __init__(self, host='127.0.0.1', port=12113, timeout=15, *, host_header=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.host_header = host_header

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            headers = dict(headers or {})
            if self.host_header is not None:
                headers['Host'] = self.host_header
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            reply = Reply(response.status, {k.lower(): v for k, v in response.getheaders()}, response.read())
            if reply.status != 200:
                raise OSError(f'stock HTTP returned {reply.status}')
            return reply
        finally:
            connection.close()

    def directory(self, path='/tmp/sdcard', offset=0, limit=200, *, local=False):
        path = sd_path(path)
        headers = {'start-pos': integer(offset), 'num-max': integer(limit, 200)}
        if limit == 0:
            raise ValueError('page limit must be positive')
        route = '/localdir' if local else '/dir'
        return self.request('GET', route + quote(path, safe='/') + '/', headers=headers).page()

    def mkdir(self, path):
        return self.request('POST', '/dir' + quote(sd_path(path, child=True), safe='/'), body=b'')

    def delete_file(self, path):
        # Empty-body handler uses remove(), including rmdir of an empty directory.
        # Do not use stock batch deletion: its directory branch builds shell text.
        return self.request('DELETE', '/file' + quote(sd_path(path, child=True), safe='/'), body=b'')

    def progress(self, path):
        # Completed transfers can remain cached even AFTER the file is deleted.
        reply = self.request('GET', '/progress' + quote(sd_path(path, child=True), safe='/'))
        return reply.json() if reply.body else None

    def upload(self, source, destination, *, image=False, overwrite=False,
               before_send=None, on_progress=None):
        destination = sd_path(destination, child=True)
        source = Path(source)
        size = source.stat().st_size
        integer(size)
        if size == 0:
            raise ValueError('empty uploads are not supported')
        if not overwrite:
            # Conservative for images, which /dir/ may omit. A stale completed
            # transfer can also block reuse until overwrite is explicitly chosen.
            if self.progress(destination) is not None:
                raise FileExistsError(destination)
            parent = str(PurePosixPath(destination).parent)
            filename = PurePosixPath(destination).name.casefold()
            offset = 0
            for _ in range(100):
                page = self.directory(parent, offset)
                if any(str(item.get('name', '')).casefold() == filename for item in page['items']):
                    raise FileExistsError(destination)
                offset += len(page['items'])
                if page['total'] is None or offset >= page['total']:
                    break
                if not page['items']:
                    raise ValueError('directory pagination made no progress')
            else:
                raise ValueError('directory preflight budget exhausted')
        # Preflight is best-effort: stock truncates an existing path, with no
        # exclusive-create option. Another writer can race this check.
        with source.open('rb') as data:
            if before_send:
                before_send()
            class Body:
                sent = 0

                def read(self, amount):
                    chunk = data.read(min(amount, size - self.sent))
                    self.sent += len(chunk)
                    if on_progress:
                        on_progress(self.sent, size)
                    return chunk
            return self.request('POST', ('/image' if image else '/audio') + quote(destination, safe='/'),
                Body() if on_progress else data,
                {'Content-Length': str(size), 'Content-Type': 'application/octet-stream'})

    def catalog(self, category='all/song', offset=0, limit=200, **filters):
        headers = self._category(category, filters)
        headers.update({'start-pos': integer(offset), 'num-max': integer(limit, 200)})
        if limit == 0:
            raise ValueError('page limit must be positive')
        page = self.request('GET', '/song_category_tree/', headers=headers).page()
        if page['total'] is None:
            raise ValueError('catalog returned no page; empty 200 is not an empty catalog')
        return page

    @staticmethod
    def _category(category, filters):
        if category not in CATEGORIES:
            raise ValueError('unsupported category')
        headers = {'type': category}
        for key, value in filters.items():
            if key in ('artist', 'album', 'style', 'list_name'):
                headers[key] = name_header(value)
            elif key == 'src_list_id':
                headers[key] = integer(value)
            else:
                raise ValueError(f'unsupported category filter: {key}')
        return headers

    def create_playlist(self, name):
        return self.request('POST', '/custom_list_cmd/', b'', {'type': 'create', 'list_name': name_header(name)})

    def rename_playlist(self, position, name):
        return self.request('POST', '/custom_list_cmd/', b'',
            {'type': 'update', 'list_id': integer(position), 'list_name': name_header(name)})

    def add_to_playlist(self, position, ranges, category='all/song', **filters):
        headers = self._category(category, filters)
        headers['dst_list_id'] = integer(position)
        headers['Content-Type'] = 'application/json'
        return self.request('POST', '/add_custom_list/', range_body(ranges), headers)

    def add_selection_to_playlist(self, position, ranges, *, expected_name,
                                  category='all/song', **filters):
        """Bulk add with current destination name and source-bounds preflight.

        Ranges belong to this exact category/filter, not song IDs. Group rows
        expand to their songs. This is not atomic: serialize edits, refresh the
        UI before calling, verify resulting contents and never retry a timeout.
        The lower-level add_to_playlist() remains available for protocol work.
        """
        integer(position)
        name_header(expected_name)
        range_body(ranges)
        required = {
            'all/song': set(), 'style': set(), 'style/song': {'style'},
            'style/album': {'style'}, 'style/album/song': {'style', 'album'},
            'album': set(), 'album/song': {'album'},
        }
        if category not in required or set(filters) != required[category]:
            raise ValueError('unsupported bulk source or missing/extraneous filters')
        self._category(category, filters)

        def row(category, wanted, **filters):
            page = self.catalog(category, offset=wanted, limit=1, **filters)
            total, items = page['total'], page['items']
            if (type(total) is not int or not 0 <= wanted < total or len(items) != 1
                    or type(items[0].get('pos')) is not int or items[0]['pos'] != wanted):
                raise ValueError('position outside the current catalog')
            return items[0]

        def destination():
            if row('custom', position).get('name') != expected_name:
                raise ValueError('destination playlist changed; refresh position and name')

        destination()
        for first, last in ranges:
            row(category, first, **filters)
            if last != first:
                row(category, last, **filters)
        destination()
        return self.add_to_playlist(position, ranges, category, **filters)

    def remove_from_playlist(self, position, ranges):
        return self.request('DELETE', '/song_category_tree/', range_body(ranges),
            {'type': 'custom/song', 'src_list_id': integer(position),
             'delete_source': '0', 'Content-Type': 'application/json'})

    def delete_playlist(self, position):
        integer(position)
        return self.request('DELETE', '/song_category_tree/', range_body([[position, position]]),
            {'type': 'custom', 'delete_source': '0', 'Content-Type': 'application/json'})

    def cover(self):
        reply = self.request('GET', '/image/cover/')
        if reply.body and not reply.headers.get('content-type', '').startswith('image/'):
            raise ValueError('cover reply is not an image')
        return reply.body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=12113)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--directory', metavar='SD_PATH')
    actions.add_argument('--catalog', choices=sorted(CATEGORIES))
    actions.add_argument('--mkdir', metavar='SD_PATH')
    actions.add_argument('--upload', nargs=2, metavar=('LOCAL_FILE', 'SD_PATH'))
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=200)
    args = parser.parse_args()
    client = HTTPClient(args.host, args.port)
    if args.directory:
        result = client.directory(args.directory, args.offset, args.limit)
    elif args.catalog:
        result = client.catalog(args.catalog, args.offset, args.limit)
    else:
        reply = client.mkdir(args.mkdir) if args.mkdir else client.upload(*args.upload)
        result = {'status': reply.status, 'headers': reply.headers,
                  'body': reply.body.decode('utf-8'), 'verification_required': True}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
