"""Metadata edition markers independent of the Assistant interaction locale."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import tomllib
import unicodedata


def normalized(value):
    return ' '.join(unicodedata.normalize('NFC', value).casefold().split())


@dataclass(frozen=True)
class VersionMarkers:
    phrases: tuple[tuple[str, str], ...]

    def version_parts(self, text):
        text = normalized(text)
        meanings = dict(self.phrases)
        pattern = r'(?<!\w)(?:' + '|'.join(r'\s+'.join(re.escape(word) for word in p.split())
                                           for p in sorted(meanings, key=lambda p: (-len(p), p))) + r')(?!\w)'
        found = set()
        def remove(match):
            found.add(meanings[normalized(match[0])])
            return ' '
        rest = re.sub(pattern, remove, text)
        return found, ' '.join(rest.split())


@lru_cache(maxsize=1)
def metadata_markers():
    with Path(__file__).with_name('version_markers.toml').open('rb') as stream:
        raw = tomllib.load(stream)
    return VersionMarkers(tuple((normalized(phrase), key) for key, phrases in raw.items() for phrase in phrases))


def with_query_markers(phrases):
    combined = dict(metadata_markers().phrases)
    for phrase, meaning in phrases:
        if phrase in combined and combined[phrase] != meaning:
            raise ValueError('command version marker conflicts with metadata marker')
        combined[phrase] = meaning
    return VersionMarkers(tuple(combined.items()))
