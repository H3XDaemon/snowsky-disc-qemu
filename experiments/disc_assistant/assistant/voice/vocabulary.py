"""Bounded, deterministic catalog hints; never derive prompts from expected answers."""
import hashlib
import json
import sqlite3
from library.artists import artist_names


def catalog_vocabulary(config):
    if not config.speech.get('catalog_hints', False):
        return (), {'enabled': False}
    path = config.data_dir / 'library.sqlite3'
    if not path.exists():
        return (), {'enabled': True, 'status': 'no_catalog'}
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.2) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('unsupported library vocabulary schema')
        head = db.execute('SELECT generation FROM heads WHERE device=?', (config.device_key,)).fetchone()
        if head is None:
            return (), {'enabled': True, 'status': 'no_snapshot'}
        rows = db.execute('SELECT artist,title,album FROM tracks WHERE generation=? ORDER BY ordinal LIMIT 513', head).fetchall()
    terms, seen, used = [], set(), 0
    truncated = len(rows) > 512
    for artist, title, album in rows[:512]:
        for term in (*artist_names(artist), title, album):
            term = ' '.join(term.split())
            if not term or term.casefold() in seen:
                continue
            seen.add(term.casefold())
            if len(terms) >= 64 or used + len(term) + 2 > 800:
                truncated = True
                continue
            terms.append(term); used += len(term) + 2
    signature = hashlib.sha256(json.dumps(terms, ensure_ascii=False).encode()).hexdigest()
    return tuple(terms), {'enabled': True, 'generation': head[0], 'terms': len(terms),
                          'sha256': signature, 'truncated': truncated}


def prompt(vocabulary):
    if not vocabulary:
        return ''
    if len(vocabulary) > 64 or any(not isinstance(s, str) or any(ord(c)<32 for c in s) for s in vocabulary):
        raise ValueError('invalid speech vocabulary')
    value = ', '.join(vocabulary)
    if len(value) > 800:
        raise ValueError('speech vocabulary exceeds 800 characters')
    return value
