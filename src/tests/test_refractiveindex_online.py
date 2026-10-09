import unittest

from refractiveindex_online import CATALOG_URL, DATA_BASE_URL, download_dataset, parse_dataset, search_catalog


CATALOG = b'''- SHELF: main
  name: Main
  content:
    - BOOK: Si
      name: "Si (Silicon)"
      content:
        - PAGE: Green-2008
          name: "Green 2008: n,k 0.25-1.45 um"
          data: main/Si/nk/Green-2008.yml
    - BOOK: Ag
      name: "Ag (Silver)"
      content: []
'''

DATA = b'''REFERENCES: |
  M. A. Green. Test reference.
COMMENTS: 300 K sample
DATA:
  - type: tabulated nk
    data: |
      0.25 1.6 3.6
      0.50 4.2 0.04
CONDITIONS:
  temperature: 300
'''


class OnlineMaterialTests(unittest.TestCase):
    def test_search_downloads_catalog_only(self):
        calls = []
        def fetch(url, limit):
            calls.append((url, limit))
            return CATALOG
        results = search_catalog('Silicon', fetch=fetch)
        self.assertEqual([call[0] for call in calls], [CATALOG_URL])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['page'], 'Green-2008')

    def test_download_fetches_only_selected_dataset_after_request(self):
        item = search_catalog('Si', fetch=lambda *_: CATALOG)[0]
        calls = []
        package = download_dataset(item, fetch=lambda url, limit: calls.append(url) or DATA)
        self.assertEqual(calls, [DATA_BASE_URL + 'main/Si/nk/Green-2008.yml'])
        self.assertEqual(package['rows'], [[250.0, 1.6, 3.6], [500.0, 4.2, 0.04]])
        self.assertIn('Green', package['reference'])

    def test_formula_requires_explicit_missing_k(self):
        raw = b'''DATA:\n  - type: formula 1\n    wavelength_range: 0.5 1.0\n    coefficients: 0 1 0.1\n'''
        item = {'data_path': 'main/Test/nk/Test.yml'}
        with self.assertRaisesRegex(ValueError, 'n but no k'):
            parse_dataset(raw, item)
        rows, *_ = parse_dataset(raw, item, missing_k=True)
        self.assertEqual(len(rows), 401)
        self.assertEqual(rows[0][2], 0.)

    def test_dataset_path_cannot_escape_database(self):
        with self.assertRaisesRegex(ValueError, 'dataset path|catalog result'):
            download_dataset({'data_path': '../secret.yml'}, fetch=lambda *_: DATA)


if __name__ == '__main__':
    unittest.main()
