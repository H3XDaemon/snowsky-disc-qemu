"""Resolve interpreted music references against catalog metadata; no input parsing."""
from experiments.disc_assistant.assistant.nlu.intents import Intent, names, normalized
from experiments.disc_assistant.assistant.matching import similarity, exact_name
from library.transliteration import fold
from library.artists import artist_names


def infer(intent, documents, aliases):
    if intent.kind != 'auto' or intent.artist is not None:
        return intent
    artists = sorted({name for d in documents for name in artist_names(d['artist'])})
    q = normalized(intent.query)
    entries = [(alias, artist) for artist in artists for alias in names(artist, aliases.get('artists', {}))]
    if any(q == alias for alias, _ in entries):
        return Intent(intent.query, 'artist')
    # An exact standalone title takes precedence over a coincidental artist prefix.
    if any(q in names(d['title'], aliases.get('titles', {})) for d in documents):
        return Intent(intent.query, 'track')
    prefixes = [alias for alias, _ in entries if q.startswith(alias + ' ')]
    if prefixes:
        prefix = max(prefixes, key=lambda a: (len(a), a))
        return Intent(intent.query, 'track', prefix, q[len(prefix):].strip())
    if any(exact_name(q, artist, aliases.get('artists', {}).get(artist, [])) for artist in artists):
        return Intent(intent.query, 'artist')
    # A projected standalone title still precedes inferred artist boundaries.
    if any(exact_name(q, d['title'], aliases.get('titles', {}).get(d['title'], [])) for d in documents):
        return Intent(intent.query, 'track')
    splits = []
    tokens = q.split()
    for size in range(1, min(8, len(tokens) - 1) + 1):
        prefix, suffix = ' '.join(tokens[:size]), ' '.join(tokens[size:])
        for artist in artists:
            score, _ = similarity(prefix, artist, aliases.get('artists', {}).get(artist, []))
            if score >= .90:
                splits.append((score, artist, suffix))
    if splits:
        splits.sort(key=lambda row: (-row[0], row[1], row[2]))
        best = splits[0]
        # Competing artists/boundaries must not silently share a fuzzy prefix.
        alternatives = [row for row in splits[1:] if row[1:] != best[1:]]
        if not alternatives or best[0] - alternatives[0][0] >= .08:
            return Intent(intent.query, 'track', best[1], best[2])
    # A missing space is recoverable only when BOTH names are catalog-backed.
    # Never split an arbitrary suffix or discard it to play the artist instead.
    fused = set()
    has_fused_prefix = False
    folded = fold(q)
    for alias, artist in entries:
        prefix = fold(alias)
        if not prefix or not folded.startswith(prefix) or len(folded) <= len(prefix):
            continue
        has_fused_prefix = True
        for end in range(1, len(q)):
            if fold(q[:end]) != prefix or q[end].isspace():
                continue
            suffix = q[end:]
            if len(suffix) >= 3 and any(artist in artist_names(d['artist']) and exact_name(
                    suffix, d['title'], aliases.get('titles', {}).get(d['title'], [])) for d in documents):
                fused.add((artist, suffix))
    if len(fused) == 1:
        artist, suffix = next(iter(fused))
        return Intent(intent.query, 'track', artist, suffix)
    # A known artist followed by unresolved fused text is not an artist-only request.
    return Intent(intent.query, 'track') if has_fused_prefix else intent
