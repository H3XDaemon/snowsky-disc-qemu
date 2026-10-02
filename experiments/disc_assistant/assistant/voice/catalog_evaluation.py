"""Read-only selection evaluation over one pinned catalog/index generation."""
from experiments.disc_assistant.assistant.nlu.intents import AlbumIntent, music_from_dict

import os
import time

from experiments.disc_assistant.assistant.nlu.intents import Intent
from experiments.disc_assistant.assistant.ranking import rank
from experiments.disc_assistant.assistant.nlu.languages import normalized
from library.search.typesense import Search, create_client
from library.store import Store, StaleSnapshot


def music_case(case):
    return case['expected'].get('status') == 'recognized' and 'query' in case['expected'].get('intent', {})


def validate_targets(cases, overlay, locale):
    targets = {case['id']: case['selection'] for case in cases if 'selection' in case}
    if overlay is not None:
        if (not isinstance(overlay, dict) or overlay.get('version') != 1 or overlay.get('locale') != locale
                or not isinstance(overlay.get('selections'), dict)):
            raise ValueError('selection expectations must be version 1 and match the active locale')
        targets.update(overlay['selections'])
    required = {case['id'] for case in cases if music_case(case)}
    if set(targets) != required:
        raise ValueError('catalog evaluation needs exactly one explicit selection for every music case')
    for target in targets.values():
        if target is None:  # Explicit expected absence, not a missing annotation.
            continue
        if not isinstance(target, dict) or target.get('kind') not in ('artist', 'track'):
            raise ValueError('selection must be null, an artist, or a track with artist/title/album')
        fields = {'kind', 'artist'} if target['kind'] == 'artist' else {'kind', 'artist', 'title', 'album'}
        if set(target) != fields or any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in target.values()):
            raise ValueError('selection must specify exact artist or track metadata')
    return targets


def selection_matches(selected, expected):
    if expected is None:
        return selected is None
    return selected is not None and all(normalized(selected.get(key, '')) == normalized(value)
                                        for key, value in expected.items())


class CatalogEvaluation:
    def __init__(self, config, targets, trace):
        self.config, self.targets, self.trace = config, targets, trace
        self.client = self.store = None

    async def __aenter__(self):
        key = os.environ.get(self.config.api_key_env, '')
        if not key.strip():
            raise ValueError(f'catalog evaluation requires {self.config.api_key_env} and a current index')
        try:
            self.store = Store(self.config.data_dir)
            self.client = create_client(self.config, key)
            self.search = Search(self.client, self.config.aliases,
                                 [self.config.search_protocol, self.config.search_host, self.config.search_port])
            self.head = self.store.verify_index(self.config.device_key, self.search.signature)
            self.trace.catalog(self.store)
            return self
        except BaseException:
            await self.__aexit__()
            raise

    async def __aexit__(self, *args):
        try:
            if self.client is not None:
                await self.client.api_call.aclose()
        finally:
            if self.store is not None:
                self.store.close()

    def verify(self):
        if self.store.verify_index(self.config.device_key, self.search.signature) != self.head:
            raise StaleSnapshot('catalog changed during evaluation; rerun against one snapshot')

    async def evaluate(self, case, actual):
        self.verify()
        intent = actual.get('intent', {})
        if actual.get('status') != 'recognized' or 'query' not in intent:
            return {'passed': False, 'failed_stage': 'interpretation', 'selection': None,
                    'expected_selection': self.targets[case['id']]}
        start = time.monotonic()
        try:
            result = await rank(self.config, self.store, self.search, music_from_dict(intent), trace=self.trace)
        except StaleSnapshot:
            raise
        except Exception as exc:
            return {'passed': False, 'failed_stage': 'search', 'error_type': type(exc).__name__,
                    'expected_selection': self.targets[case['id']]}
        self.trace.search(result)
        self.verify()
        selected = result['candidates'][0] if result['candidates'] else None
        passed = selection_matches(selected, self.targets[case['id']])
        failure = ('retrieval' if selected is None and not result['retrieval'].get('found', 0) else 'ranking')
        return {'passed': passed, 'failed_stage': None if passed else failure,
                'selection': selected, 'expected_selection': self.targets[case['id']],
                'retrieval': result['retrieval'], 'candidate_count': result['candidate_count'],
                'ranking_policy': result['ranking_policy'],
                'search_ranking_ms': round((time.monotonic() - start) * 1000, 3)}
