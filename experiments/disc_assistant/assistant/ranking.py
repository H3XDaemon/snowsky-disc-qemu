"""Deterministic lexical ranking. No invented history, likes or confidence values."""
import re
from dataclasses import asdict

from experiments.disc_assistant.assistant.nlu.intents import Intent, AlbumIntent, normalized, names
from experiments.disc_assistant.assistant.nlu.languages import load_languages
from library.store import StaleSnapshot
from library.versions import with_query_markers
from experiments.disc_assistant.assistant.resolver import infer
from experiments.disc_assistant.assistant.matching import similarity, strong_match, artist_similarity
from library.transliteration import fold
from library.artists import artist_names


def versions(value, rules):
    return rules.version_parts(value)[0]


def clean_title(value):
    return re.sub(r'\.(?:flac|mp3|wav|m4a|aac|ogg|dsf|dff)$', '', normalized(value))


def base_title(value, rules):
    value = clean_title(value)
    value = re.sub(r'\([^)]*\)|\[[^]]*\]', lambda m: '' if versions(m[0], rules) else m[0], value)
    parts = re.split(r'\s+[-–—]\s+', value, maxsplit=1)
    if len(parts) == 2 and versions(parts[1], rules):
        value = parts[0]
    return ' '.join(value.split())


def score_tracks(intent, documents, aliases, rules=None):
    rules = rules if rules is not None else load_languages()
    metadata_rules = with_query_markers(rules.versions)
    ranked = []
    requested_title = intent.title if intent.title is not None else intent.query
    requested_versions, query_core = metadata_rules.version_parts(clean_title(requested_title))
    for doc in documents:
        edition = versions(doc['title'], metadata_rules) | versions(doc['album'], metadata_rules)
        if requested_versions and not requested_versions <= edition:
            continue
        title_score, title_match = similarity(clean_title(requested_title), clean_title(doc['title']),
                                             aliases.get('titles', {}).get(doc['title'], []))
        base_score, base_match = similarity(query_core or requested_title, base_title(doc['title'], metadata_rules),
                                           aliases.get('titles', {}).get(doc['title'], []))
        if base_score > title_score:
            title_score, title_match = base_score, 'base_' + base_match
        artist_score, artist_match = 0.0, 'not_requested'
        if intent.artist is not None:
            artist_score, artist_match = artist_similarity(intent.artist, doc['artist'], aliases)
            if artist_score < .72 or title_score < .55:
                continue
            score = 75 * title_score + 25 * artist_score
        else:
            # Mixed requests with a misspelled artist can still be retrieved and
            # ranked as a complete artist/title phrase; never discard its words.
            combined, combined_match = max((similarity(intent.query, name + ' ' + doc['title'])
                for name in artist_names(doc['artist'])), key=lambda result: result[0])
            if intent.kind == 'auto' and combined > title_score:
                title_score, title_match = combined, 'combined_' + combined_match
            if title_score < .60:
                continue
            score = 100 * title_score
        penalty = 0 if requested_versions else (2 if edition == {'remaster'} else 12 if edition else 0)
        evidence = {'title_similarity': round(title_score, 4), 'title_match': title_match,
                    'artist_similarity': round(artist_score, 4), 'artist_match': artist_match,
                    'requested_versions': sorted(requested_versions), 'version_markers': sorted(edition),
                    'unrequested_version_penalty': penalty}
        ranked.append({'kind': 'track', 'track_id': doc['id'], 'title': doc['title'],
                       'artist': doc['artist'], 'album': doc['album'],
                       'score': round(score - penalty, 4), 'evidence': evidence})
    return ranked


def score_artists(intent, documents, aliases):
    result = []
    for artist in sorted({d['artist'] for d in documents}):
        score, match = artist_similarity(intent.query, artist, aliases)
        if score >= .80:
            result.append({'kind': 'artist', 'artist': artist, 'score': round(score * 100, 4),
                           'evidence': {'artist_similarity': round(score, 4), 'artist_match': match}})
    return result


def ordered(candidates):
    # Metadata ordering then snapshot ordinal break ties, never random UUIDs or
    # hidden popularity. An artist wins an exact same-name artist/title tie.
    return sorted(candidates, key=lambda c: (-c['score'], c['kind'] != 'artist',
        normalized(c['artist']), normalized(c.get('album', '')), normalized(c.get('title', '')),
        int(c['track_id'].rsplit(':', 1)[1]) if c['kind'] == 'track' else -1))


async def rank(config, store, search, intent, *, trace=None, context=None):
    if type(intent) not in (Intent, AlbumIntent):
        raise TypeError('rank requires an interpreted music Intent')
    rules = load_languages((config.locale,))
    head = store.verify_index(config.device_key, search.signature)
    documents = store.documents(head['generation'])
    if trace:
        trace.event('catalog_loaded', {'track_count': len(documents),
                                      'artist_count': len({d['artist'] for d in documents})})
    if type(intent) is AlbumIntent:
        candidates = score_albums(intent, documents, config.aliases)
        if store.verify_index(config.device_key, search.signature) != head:
            raise StaleSnapshot('catalog changed during album ranking')
        return {'status': 'ranked' if candidates else 'not_found', 'query': intent.query,
                'intent': 'album', 'resolved_intent': asdict(intent), 'generation': head['generation'],
                'device': config.device_key, 'retrieval': {'source': 'sqlite', 'truncated': False},
                'candidates': candidates[:10], 'candidate_count': len(candidates),
                'candidates_truncated': len(candidates) > 10, 'ranking_policy': 'album-lexical-v1; scores are not probabilities'}
    intent = infer(intent, documents, config.aliases)
    if trace:
        trace.event('intent_resolved', asdict(intent))
    if intent.kind != 'artist' and intent.artist is None:
        from experiments.disc_assistant.assistant.context import scopes
        if callable(context):
            context = context()
        for scope, pool in scopes(context, documents):
            candidates = ordered(c for c in score_tracks(intent, pool, config.aliases, rules)
                                 if c['evidence']['title_similarity'] >= .85)
            if candidates:
                if store.verify_index(config.device_key, search.signature) != head:
                    raise StaleSnapshot('catalog changed during contextual ranking')
                if trace:
                    trace.event('playback_search_scope', {'scope': scope, 'candidate_count': len(candidates)})
                return {'status': 'ranked', 'query': intent.query, 'intent': intent.kind,
                        'resolved_intent': asdict(intent), 'generation': head['generation'],
                        'device': config.device_key, 'retrieval': {'source': 'sqlite', 'scope': scope, 'truncated': False},
                        'candidates': candidates[:10], 'candidate_count': len(candidates),
                        'candidates_truncated': len(candidates) > 10,
                        'playback_context': context, 'ranking_policy': 'context-lexical-v1; album then artist then global'}
    if intent.artist is not None:
        known = {d['artist'] for d in documents if strong_match(artist_similarity(intent.artist, d['artist'], config.aliases)[1])}
        if known:
            # A literal canonical name wins over an alias shared with another artist.
            strengths = {artist: artist_similarity(intent.artist, artist, config.aliases)[0] for artist in known}
            known = {artist for artist in known if strengths[artist] == max(strengths.values())}
            documents = [d for d in documents if d['artist'] in known]
    else:
        known = set()
    candidates = score_artists(intent, documents, config.aliases) if intent.kind != 'track' else []
    if trace:
        artist_query = normalized(intent.artist if intent.artist is not None else intent.query)
        exact_artists = sorted({d['artist'] for d in documents if artist_query
                                in {alias for name in artist_names(d['artist'])
                                    for alias in names(name, config.aliases.get('artists', {}))}})
        trace.event('local_matches', {'scoped_track_count': len(documents),
                    'exact_artist_count': len(exact_artists), 'exact_artists': exact_artists[:10],
                    'exact_artists_truncated': len(exact_artists) > 10,
                    'artist_candidate_count': len(candidates),
                    'track_search_enabled': intent.kind != 'artist'})
    retrieval = {'source': 'sqlite', 'truncated': False}
    if intent.kind != 'artist':
        # Exact/base-title/alias matches across the whole SQLite snapshot are not
        # subject to the search engine's top-k limit. Fuzzy retrieval is bounded.
        exact = [r for r in score_tracks(intent, documents, config.aliases, rules)
                 if strong_match(r['evidence']['title_match']) and
                 (intent.artist is None or strong_match(r['evidence']['artist_match']))]
        if trace:
            trace.event('local_track_matches', {'exact_track_count': len(exact),
                                               'typesense_needed': not bool(exact)})
        if exact:
            candidates.extend(exact)
        else:
            query = (intent.artist + ' ' + intent.title) if intent.artist is not None else intent.query
            query = fold(query)
            if trace:
                trace.event('search_query', {'query': query, 'limit': 50})
            response = await search.search(store, config.device_key, query, limit=50,
                                           fields=('title', 'artist', 'title_aliases', 'artist_aliases', 'album', 'album_aliases', 'artists'),
                                           artist_scope=known or None)
            if trace:
                trace.search(response, phase='retrieval')
            if response['generation'] != head['generation']:
                raise StaleSnapshot('catalog changed during ranking; repeat the command')
            pool = [dict(r, id=r['id']) for r in response['candidates'] if not known or r['artist'] in known]
            scored = score_tracks(intent, pool, config.aliases, rules)
            if trace:
                trace.event('retrieval_filtered', {'found': response['found'],
                            'returned_count': len(response['candidates']), 'scoped_count': len(pool),
                            'ranked_track_count': len(scored)})
            candidates.extend(scored)
            retrieval = {'source': 'typesense', 'found': response['found'],
                         'truncated': response['found'] > len(pool)}
    if store.verify_index(config.device_key, search.signature) != head:
        raise StaleSnapshot('catalog or index changed during ranking; repeat the command')
    candidates = ordered(candidates)
    return {'status': 'ranked' if candidates else 'not_found', 'query': intent.query,
            'intent': intent.kind, 'resolved_intent': asdict(intent), 'generation': head['generation'], 'device': config.device_key,
            'retrieval': retrieval, 'candidates': candidates[:10],
            'candidate_count': len(candidates), 'candidates_truncated': len(candidates) > 10,
            'ranking_policy': 'lexical-v5; scores are not probabilities; no history/likes'}


def score_albums(intent, documents, aliases):
    """Album names are native scopes; generic albums retain every credited artist."""
    scopes = {(d['album'], d['artist'] if intent.artist is not None else None) for d in documents}
    result = []
    for album, artist in scopes:
        album_score, album_match = similarity(intent.album, album)
        artist_score, artist_match = artist_similarity(intent.artist, artist, aliases) if artist is not None else (1.0, 'not_requested')
        # Version words remain part of the complete album name; no title cleanup.
        if album_score < .80 or artist_score < .80:
            continue
        score = album_score * 100 if artist is None else album_score * 75 + artist_score * 25
        result.append({'kind': 'album', 'album': album, 'artist': artist, 'score': round(score, 4),
                       'evidence': {'album_similarity': round(album_score, 4), 'album_match': album_match,
                                    'artist_similarity': round(artist_score, 4), 'artist_match': artist_match}})
    return sorted(result, key=lambda c: (-c['score'], normalized(c['album']), normalized(c['artist'] or '')))
