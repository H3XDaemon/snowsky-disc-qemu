import unittest

from library.catalog import CatalogReader, CatalogChanged
from library.tests.helpers import Catalog, TRACKS


class CatalogTests(unittest.TestCase):
    def test_full_pagination_and_duplicate_cue_entries(self):
        fake = Catalog()
        tracks = CatalogReader(fake, page_size=1).read_stable()
        self.assertEqual(tracks, TRACKS)
        self.assertEqual(sum(t.title == 'Numb' for t in tracks), 3)
        self.assertEqual(sum(t.raw.get('id') == 7 for t in tracks), 2)
        self.assertIn(('all/song', 6, 1, {}), fake.calls)

    def test_empty_confirmed_catalog(self):
        self.assertEqual(CatalogReader(Catalog([])).read_stable(), [])

    def test_bad_pagination(self):
        for problem in ('missing_total', 'count_change', 'gap', 'empty_page', 'oversized', 'missing_author'):
            with self.subTest(problem=problem):
                fake = Catalog()
                def change(category, offset, page):
                    if category != 'all/song':
                        return
                    if problem == 'missing_total':
                        page.pop('total')
                    elif problem == 'count_change' and offset:
                        page['total'] -= 1
                    elif problem == 'gap':
                        page['items'][0]['pos'] += 1
                    elif problem == 'empty_page':
                        page['items'] = []
                    elif problem == 'oversized':
                        page['items'] *= 2
                    elif problem == 'missing_author':
                        page['items'][0].pop('author')
                fake.change = change
                with self.assertRaises(ValueError):
                    CatalogReader(fake, page_size=1).read_stable()

    def test_same_count_change_between_reads(self):
        fake = Catalog()
        roots = 0
        def change(category, offset, page):
            nonlocal roots
            if category == 'all/song' and offset == 0:
                roots += 1
            if roots == 2 and category.endswith('/song'):
                for row in page['items']:
                    if row['name'] == 'Numb':
                        row['name'] = 'Replacement'
        fake.change = change
        with self.assertRaisesRegex(CatalogChanged, 'between full reads'):
            CatalogReader(fake).read_stable()

    def test_album_membership_mismatch(self):
        fake = Catalog()
        def change(category, offset, page):
            if category == 'album/song' and page['items'][0]['name'] == 'Numb':
                page['items'][0]['name'] = 'Different recording'
        fake.change = change
        with self.assertRaisesRegex(CatalogChanged, 'membership'):
            CatalogReader(fake).read_stable()

    def test_bounded_catalog_reads(self):
        for kwargs in ({'max_tracks': 2}, {'max_requests': 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                CatalogReader(Catalog(), **kwargs).read_stable()
