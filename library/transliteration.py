"""Deterministic, inspectable search spelling projection shared with the index."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import tomllib
import unicodedata


@lru_cache(maxsize=1)
def characters():
    with Path(__file__).with_suffix('.toml').open('rb') as stream:
        table = tomllib.load(stream)['characters']
    if any(len(key) != 1 or not isinstance(value, str) or not value.isascii()
           or (value and not value.isalpha()) for key, value in table.items()):
        raise ValueError('invalid search transliteration table')
    return table


def fold(text):
    text = unicodedata.normalize('NFC', text).casefold()
    return ' '.join(''.join(characters().get(c, c) for c in text).split())


def fingerprint():
    return hashlib.sha256(json.dumps(characters(), sort_keys=True).encode()).hexdigest()


def projected_aliases(name, aliases):
    original = list(aliases)
    return original + sorted({fold(value) for value in (name, *original)} -
                             {' '.join(value.casefold().split()) for value in (name, *original)})
