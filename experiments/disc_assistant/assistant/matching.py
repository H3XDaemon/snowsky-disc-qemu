"""Name evidence shared by catalog resolution and ranking; no command rewriting."""
from difflib import SequenceMatcher
import re

from experiments.disc_assistant.assistant.nlu.languages import normalized
from library.transliteration import fold
from library.artists import artist_names


def artist_similarity(query, credit, aliases):
    # Literal members outrank aliases, including aliases of the complete credit.
    return max((similarity(query, name, aliases.get('artists', {}).get(name, []))
                for name in artist_names(credit)), key=lambda result: result[0])


def words(value):
    return re.findall(r'[^\W_]+', normalized(value))


def similarity(query, canonical, aliases=()):
    q = ' '.join(words(query))
    best = (0.0, 'none')
    for value, label in [(canonical, 'literal'), *((a, 'alias') for a in aliases)]:
        candidate = ' '.join(words(value))
        if not q or not candidate:
            continue
        score = 1.0 if q == candidate else SequenceMatcher(None, q, candidate, autojunk=False).ratio()
        evidence = label if score == 1 else 'fuzzy_' + label
        score *= 1 if label == 'literal' else .99
        if score > best[0]:
            best = (score, evidence)
        fq, fc = fold(q), fold(candidate)
        if (fq, fc) != (q, candidate) and fq and fc:
            # Literal/explicit alias matches outrank projected spellings.
            score = .98 * (1 if label == 'literal' else .99) * (
                1.0 if fq == fc else SequenceMatcher(None, fq, fc, autojunk=False).ratio())
            if score > best[0]:
                best = (score, ('transliterated_' if fq == fc else 'fuzzy_transliterated_') + label)
    return best


def exact_name(query, name, aliases=()):
    return strong_match(similarity(query, name, aliases)[1])


def strong_match(label):
    return label.removeprefix('base_') in ('literal', 'alias', 'transliterated_literal', 'transliterated_alias')
