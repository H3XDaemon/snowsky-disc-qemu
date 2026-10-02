"""Derived artist membership; literal device tags remain playback selectors."""
import unicodedata


def split_artists(value):
    """Split explicit semicolons only, preserving first spelling and member order."""
    result, seen = [], set()
    for part in value.split(';'):
        name = part.strip()
        key = unicodedata.normalize('NFC', name).casefold()
        if name and key not in seen:
            result.append(name)
            seen.add(key)
    return result


def artist_names(value):
    """Match the complete credit as well as its members without rewriting it."""
    return list(dict.fromkeys([value, *split_artists(value)]))


def artist_key(credit):
    """Exact raw-credit filter key; never interpolate catalog names into query syntax."""
    import hashlib
    return hashlib.sha256(credit.encode('utf-8')).hexdigest()
