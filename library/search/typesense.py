"""Official async SDK adapter. SQLite selects a completely built collection."""
import hashlib
import json
from uuid import uuid4

from library.store import StaleSnapshot
from library.transliteration import projected_aliases, fingerprint
from library.artists import artist_names, split_artists, artist_key

SCHEMA_VERSION = 4
FIELDS = ['title', 'artist', 'album', 'title_aliases', 'artist_aliases', 'album_aliases', 'artists']


def signature(aliases, server):
    value = json.dumps([SCHEMA_VERSION, fingerprint(), aliases, server], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


def create_client(config, api_key):
    try:
        from typesense import AsyncClient
    except ImportError as exc:
        raise RuntimeError('install the prototype requirements to use search') from exc
    return AsyncClient({'api_key': api_key, 'nodes': [{'host': config.search_host,
        'port': config.search_port, 'protocol': config.search_protocol}],
        'connection_timeout_seconds': config.timeout, 'num_retries': 0})


class Search:
    def __init__(self, client, aliases, server):
        self.client = client
        self.aliases = aliases
        self.signature = signature(aliases, server)

    async def build(self, store, device):
        head = store.head(device)
        generation = head['generation']
        if generation is None:
            raise ValueError('no catalog snapshot; run sync first')
        documents = store.documents(generation)
        for doc in documents:
            doc['album_aliases'] = projected_aliases(doc['album'], [])
            doc['artist_aliases'] = list(dict.fromkeys(alias
                for name in artist_names(doc['artist'])
                for alias in projected_aliases(name, self.aliases.get('artists', {}).get(name, []))))
            doc['title_aliases'] = projected_aliases(doc['title'], self.aliases.get('titles', {}).get(doc['title'], []))
        # Random per attempt: no in-place updates and no exposed partial collections.
        name = 'disc_prototype_' + uuid4().hex
        collection = self.client.collections[name]
        try:
            await self.client.collections.create({'name': name, 'fields': [
                {'name': field, 'type': 'string[]' if field.endswith('_aliases') or field == 'artists' else 'string'}
                for field in FIELDS] + [{'name': 'artist_key', 'type': 'string', 'facet': True}, {'name': 'generation', 'type': 'string', 'index': False}]})
            for start in range(0, len(documents), 200):
                batch = documents[start:start + 200]
                result = await collection.documents.import_(batch, {'action': 'create'})
                # HTTP 200 can include per-document failures. Never publish those.
                if (not isinstance(result, list) or len(result) != len(batch)
                        or any(not isinstance(row, dict) or row.get('success') is not True for row in result)):
                    raise ValueError('Typesense rejected an index batch; old projection retained')
            info = await collection.retrieve()
            if info.get('num_documents') != head['track_count']:
                raise ValueError('Typesense document count mismatch; old projection retained')
            store.publish_index(device, generation, name, self.signature)
        except BaseException:
            # Best effort for this attempt only. Do not delete a previous published index.
            try:
                await collection.delete()
            except Exception:
                pass
            raise
        return store.head(device)

    async def search(self, store, device, query, *, limit=10, fields=None, artist_scope=None, split_join="off"):
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError('query must contain 1..1000 characters')
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('limit must be in 1..50')
        fields = list(fields) if fields is not None else FIELDS
        if not fields or any(field not in FIELDS for field in fields):
            raise ValueError('unsupported search fields')
        weights = dict(zip(FIELDS, (6, 5, 2, 4, 3, 1, 5)))
        if split_join not in ('off', 'fallback', 'always'):
            raise ValueError('unsupported split/join policy')
        extra = {}
        if artist_scope is not None:
            if not isinstance(artist_scope, (list, tuple, set)) or not artist_scope or any(not isinstance(a, str) or not a for a in artist_scope):
                raise ValueError('artist scope must contain nonempty raw credits')
            if len(artist_scope) > 1000:
                raise ValueError('artist scope exceeds the bounded filter size')
            extra['filter_by'] = 'artist_key:=[' + ','.join(sorted({artist_key(a) for a in artist_scope})) + ']'
        head = store.verify_index(device, self.signature)
        reply = await self.client.collections[head['collection']].documents.search({
            'q': query.strip(), 'query_by': ','.join(fields), 'query_by_weights': ','.join(str(weights[f]) for f in fields),
            'per_page': limit, 'num_typos': 2, 'prefix': True,
            'drop_tokens_threshold': 0, 'split_join_tokens': split_join, **extra,
            'highlight_fields': ','.join(FIELDS), 'enable_highlight_v1': True,
        })
        if store.verify_index(device, self.signature) != head:
            raise StaleSnapshot('catalog or index changed during search; repeat the query')
        if (type(reply.get('found')) is not int or not isinstance(reply.get('hits'), list)
                or reply.get('search_cutoff') is True):
            raise ValueError('incomplete or invalid search response')
        hits = []
        for hit in reply['hits']:
            document = hit['document']
            row = store.db.execute('SELECT * FROM tracks WHERE id=? AND generation=?',
                                   (document.get('id'), head['generation'])).fetchone()
            if (row is None or any(document.get(k) != row[k] for k in ('generation', 'title', 'artist', 'album'))
                    or document.get('artists') != split_artists(row['artist'])
                    or document.get('artist_key') != artist_key(row['artist'])):
                raise StaleSnapshot('search result disagrees with SQLite; rebuild the index')
            evidence = [{'field': h['field'], 'matched_tokens': h.get('matched_tokens', [])}
                        for h in hit.get('highlights', []) if h.get('field') in FIELDS]
            hits.append({'id': row['id'], 'title': row['title'], 'artist': row['artist'],
                         'artists': split_artists(row['artist']),
                         'album': row['album'], 'source': json.loads(row['source']),
                         'match': evidence, 'text_match': str(hit.get('text_match', ''))})
        return {'device': device, 'generation': head['generation'], 'observed_at': head['observed_at'],
                'query': query, 'found': reply['found'], 'candidates': hits,
                'selection': 'candidates_only', 'identity': 'snapshot-only'}
