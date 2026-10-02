"""Bounded stock HTTP pagination; no local catalog or snapshot storage."""
def verify_expected(rows, expected):
    """Compare a displayed positional source with fresh device rows before a write."""
    if expected is None:
        return
    from controller.models import QueueItem
    if not isinstance(expected, tuple) or any(not isinstance(row, QueueItem) for row in expected):
        raise ValueError('expected source must be an immutable tuple of QueueItem rows')
    actual = tuple(QueueItem(row['pos'], row['name'], row['author']) for row in rows)
    if actual != expected:
        raise CatalogChanged('displayed source changed; refresh before selecting a track')


class CatalogChanged(ValueError):
    def __init__(self, message, *, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics


class CatalogReader:
    def __init__(self, http, *, page_size=200, max_tracks=100000, max_requests=10000):
        self.http = http
        self.page_size = page_size
        self.max_tracks = max_tracks
        self.remaining = max_requests

    def rows(self, category, **filters):
        result, expected = [], None
        while True:
            if self.remaining <= 0:
                raise ValueError('catalog request budget exhausted')
            self.remaining -= 1
            page = self.http.catalog(category, offset=len(result), limit=self.page_size, **filters)
            total, items = page.get('total'), page.get('items')
            if type(total) is not int or not 0 <= total <= self.max_tracks:
                raise ValueError('missing or invalid catalog total')
            if expected is not None and total != expected:
                raise CatalogChanged('catalog total changed during pagination')
            expected = total
            if not isinstance(items, list) or len(items) > self.page_size or len(result) + len(items) > total:
                raise ValueError('invalid catalog page size')
            for position, row in enumerate(items, len(result)):
                if (not isinstance(row, dict) or type(row.get('pos')) is not int
                        or row['pos'] != position or not isinstance(row.get('name'), str)
                        or not row['name']):
                    raise ValueError('invalid catalog row or non-contiguous positions')
                if category.endswith('/song') and not isinstance(row.get('author'), str):
                    raise ValueError('track row is missing its author')
            result.extend(items)
            if len(result) == total:
                return result
            if not items:
                raise CatalogChanged('catalog pagination stopped before its declared total')
