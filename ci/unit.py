"""Discover every component test; missing dependencies/skipped tests fail CI."""
import sys
import unittest
from pathlib import Path


def test_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_cases(item)
        else:
            yield item


def main():
    repo = Path(__file__).resolve().parents[1]
    loader = unittest.TestLoader()
    # Test only source test directories, never ignored user SD/rootfs contents.
    roots = ('emulator/tests', 'viewer/tests', 'controller/tests', 'library/tests', 'firmware/tests',
             'research/diagnostics/tests', 'experiments/browser/tests', 'experiments/disc_web/tests', 'tests')
    suite = unittest.TestSuite(loader.discover(str(repo / root), pattern='test_*.py',
                                              top_level_dir=str(repo)) for root in roots)
    # Catch a new directory missing __init__.py: unittest would silently skip it.
    expected = {str(p.relative_to(repo).with_suffix('')).replace('/', '.')
                for root in roots for p in (repo / root).rglob('test_*.py')}
    discovered = {case.__class__.__module__ for case in test_cases(suite)}
    missing = expected - discovered
    if loader.errors:
        print('\n'.join(loader.errors), file=sys.stderr)
    if missing:
        print('Undiscovered test modules:', ', '.join(sorted(missing)), file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print('CI forbids skipped tests; install dependencies from emulator/docker/Dockerfile.', file=sys.stderr)
    return int(not result.wasSuccessful() or bool(result.skipped) or result.testsRun == 0)


if __name__ == '__main__':
    sys.exit(main())
