"""Assistant regression plus the shared Library tests after its extraction."""
import sys
import unittest


def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.discover(root, top_level_dir='.')
                              for root in ('library/tests', 'experiments/disc_assistant'))
    return int(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())


if __name__ == '__main__':
    sys.exit(main())
