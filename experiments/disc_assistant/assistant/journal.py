"""Bounded request/decision journal. Evidence collection, never a replay queue."""
import asyncio
from experiments.disc_assistant.assistant.nlu import RULES_VERSION
from dataclasses import asdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from uuid import uuid4

from experiments.disc_assistant.assistant.database import connect
from experiments.disc_assistant.assistant.nlu.languages import load_languages, normalized
from library.store import StaleSnapshot
from library.versions import metadata_markers
from library.transliteration import fingerprint as transliteration_fingerprint
from experiments.disc_assistant.assistant.responses import Responses
from experiments.disc_assistant.assistant.providers import ProviderUnavailable, InvalidProviderResult
from experiments.disc_assistant.assistant.nlu.interpreter import UnsupportedCommand
from experiments.disc_assistant.assistant.speech import SpeechUnavailable, InvalidSpeech, NoSpeech


class JournalWriteError(RuntimeError):
    pass


@contextmanager
def durable_write(db):
    try:
        with db:
            yield
    except sqlite3.Error as exc:
        raise JournalWriteError('journal write failed; an operation may already have completed; do not replay it') from exc


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def debug_line(event):
    # JSON escapes terminal control characters in user input and metadata.
    return '[trace] ' + json.dumps(event, ensure_ascii=False)


def debug_stderr(event):
    print(debug_line(event), file=sys.stderr, flush=True)


def bounded(value, depth=0):
    """Bound trusted structured evidence; never pass raw SDK/HTTP error bodies here."""
    if depth > 8:
        return {'truncated': True}
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, dict):
        return {str(k)[:100]: bounded(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [bounded(v, depth + 1) for v in value[:10]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


def candidate(row):
    return bounded({k: row[k] for k in ('kind', 'id', 'track_id', 'artist', 'album', 'title',
                                      'score', 'evidence', 'match', 'text_match', 'source') if k in row})


def search_evidence(result):
    rows = result.get('candidates', [])
    evidence = {k: result[k] for k in ('query', 'generation', 'device', 'observed_at',
                'intent', 'ranking_policy', 'retrieval', 'found', 'selection', 'identity', 'candidate_count') if k in result}
    evidence.update(candidates=[candidate(row) for row in rows[:10]],
                    returned_count=len(rows), retained_count=min(10, len(rows)),
                    truncated=(len(rows) > 10 or result.get('found', 0) > len(rows)
                               or result.get('candidates_truncated', False)
                               or result.get('retrieval', {}).get('truncated', False)))
    return evidence


def outcome(result):
    # Do not persist arbitrary exception reasons, server bodies, headers or full queues.
    result = result or {}
    safe = {k: result[k] for k in ('status', 'operation_id', 'mutation_attempted', 'action',
            'outcome', 'state', 'fresh_position', 'metadata_equivalent_rows', 'assistant_continuation',
            'device_stop_semantics', 'enabled', 'source', 'reused', 'generation', 'index_generation',
            'track_count', 'locale', 'mode', 'error_type', 'requested', 'previous', 'confirmation', 'response', 'timing',
            'passed', 'total', 'sample_count', 'selection_passed', 'selection_total', 'interpretation_passed') if k in result}
    if result.get('status') in ('not_sent', 'uncertain'):
        safe['failure_category'] = result['status']
    if 'mode_change' in result:
        safe['mode_change'] = outcome(result['mode_change'])
    if 'queue' in result:
        safe['queue'] = {k: result['queue'][k] for k in ('total', 'mode', 'source', 'continuation')
                         if k in result['queue']}
    return bounded(safe)


class Journal:
    def __init__(self, config):
        self.config = config
        self.db = connect(config.data_dir)
        self.db.row_factory = sqlite3.Row

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def prune(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.config.journal_retention_days)).isoformat(timespec='milliseconds')
        with durable_write(self.db):
            before = self.db.execute('SELECT count(*) FROM requests').fetchone()[0]
            self.db.execute('DELETE FROM requests WHERE started_at < ?', (cutoff,))
            # Recent in-flight requests are never removed by the count limit.
            self.db.execute('''DELETE FROM requests WHERE id IN (
                SELECT id FROM requests WHERE completed_at IS NOT NULL
                ORDER BY started_at DESC,rowid DESC LIMIT -1 OFFSET ?)''', (self.config.journal_max_requests,))
            return before - self.db.execute('SELECT count(*) FROM requests').fetchone()[0]

    def detail(self, request_id):
        row = self.db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if row is None:
            raise ValueError('request not found (it may have expired)')
        result = dict(row)
        result['context'] = json.loads(result.pop('context_json'))
        result['outcome'] = json.loads(result.pop('outcome_json') or 'null')
        result['events'] = [dict(id=r['id'], phase=r['phase'], observed_at=r['observed_at'],
                                 elapsed_ms=r['elapsed_ms'], payload=json.loads(r['payload_json']))
                            for r in self.db.execute('SELECT * FROM request_events WHERE request_id=? ORDER BY id', (request_id,))]
        return result


def recallable(text):
    """Recall submitted single-line commands, excluding history maintenance/UI."""
    return (bool(text.strip()) and text.strip() != '[audio]' and len(text) <= 4000
            and not any(ord(c) < 32 or ord(c) == 127 for c in text)
            and text.strip().split(maxsplit=1)[0] not in ('/history', '/clear', '/exit'))


def console_history(config):
    """Oldest first, device-scoped interactive input; persistence stays in Trace."""
    if not config.journal_enabled:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.journal_retention_days)).isoformat(timespec='milliseconds')
    with Journal(config) as journal:
        rows = journal.db.execute('''SELECT input FROM requests
            WHERE device=? AND source='interactive' AND input_truncated=0 AND started_at>=?
              AND command NOT IN ('history','clear','exit')
            ORDER BY started_at DESC,rowid DESC LIMIT ?''',
            (config.device_key, cutoff, min(1000, config.journal_max_requests))).fetchall()
    return [row['input'] for row in reversed(rows) if recallable(row['input'])]


class Trace:
    def __init__(self, config, command, text, *, source='cli', session_id=None, event_sink=None, persist=True):
        self.config, self.command, self.text = config, command, text
        self.source, self.session_id = source, session_id or uuid4().hex
        self.id, self.stage = uuid4().hex, 'input'
        self.journal = None
        self.event_sink, self.persist = event_sink, persist
        self.started = time.monotonic()
        self.responses = Responses(config.locale, config.response_mode)

    def __enter__(self):
        if not self.config.journal_enabled or not self.persist:
            return self
        try:
            self.journal = Journal(self.config)
            self.journal.prune()
            rules = asdict(load_languages((self.config.locale,)))
            context = {'locale': self.config.locale, 'shadow_enabled': self.config.shadow, 'command_rules_version': RULES_VERSION,
                       'matching_policy': 'context-lexical-v1/lexical-v5', 'transliteration_sha256': transliteration_fingerprint(),
                       'language_rules_sha256': hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest(),
                       'metadata_markers_sha256': hashlib.sha256(json.dumps(metadata_markers().phrases).encode()).hexdigest(),
                       'selection_policy': 'automatic-best-match', 'continuous_context': self.config.continuous_context,
                       'response': self.responses.context()}
            with durable_write(self.journal.db):
                self.journal.db.execute('''INSERT INTO requests
                    (id,session_id,source,device,command,input,normalized_input,input_truncated,context_json,started_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''', (self.id, self.session_id, self.source, self.config.device_key,
                    self.command, self.text[:4000], normalized(self.text[:4000]), len(self.text) > 4000,
                    json.dumps(context), utcnow()))
        except BaseException as exc:
            self.unrecorded_failure(exc)
            if self.journal is not None:
                self.journal.__exit__()
            raise
        return self

    def event(self, phase, payload):
        self.stage = phase
        event = {'request_id': self.id, 'phase': phase, 'observed_at': utcnow(),
                 'elapsed_ms': round((time.monotonic() - self.started) * 1000),
                 'payload': bounded(payload)}
        if self.journal is not None:
            with durable_write(self.journal.db):
                self.journal.db.execute('''INSERT INTO request_events(request_id,phase,observed_at,elapsed_ms,payload_json)
                    VALUES(?,?,?,?,?)''', (self.id, phase, event['observed_at'], event['elapsed_ms'],
                    json.dumps(event['payload'], ensure_ascii=False)))
        if self.event_sink is not None:
            try:
                self.event_sink(event)
            except Exception:
                # Debug output is optional; a broken stream must not change/replay an action.
                self.event_sink = None

    def intent(self, intent):
        self.event('parsed', asdict(intent))

    def catalog(self, store):
        head = store.head(self.config.device_key)
        self.event('catalog', {k: head.get(k) for k in ('generation', 'index_generation', 'collection', 'index_signature')})

    def search(self, result, *, phase='ranking'):
        self.event(phase, search_evidence(result))

    def select(self, result):
        self.event('selection', {'method': 'automatic_best_match', 'rank': 1,
                                 'generation': result['generation'], 'candidate': candidate(result['candidates'][0])})

    def stamp(self, result):
        result['timing'] = {'total_ms': round((time.monotonic() - self.started) * 1000, 3)}
        result['request_id'] = self.id
        return result

    def unrecorded_failure(self, exc):
        # A failed journal write can follow a successful device mutation.
        result = {'status': 'uncertain', 'error_type': type(exc).__name__}
        self.responses.attach(result, command=self.command, source=self.source)
        exc.assistant_result = self.stamp(result)
        exc.request_id = self.id

    def finish(self, result, *, failure=None):
        if result is None:
            return None
        self.responses.attach(result, command=self.command, source=self.source, failure=failure)
        self.stamp(result)
        safe = outcome(result)
        status = result.get('status', 'completed') if result else 'completed'
        self.event('result', safe)
        if self.journal is not None:
            with durable_write(self.journal.db):
                self.journal.db.execute('UPDATE requests SET completed_at=?,status=?,outcome_json=? WHERE id=?',
                                       (utcnow(), status, json.dumps(safe, ensure_ascii=False), self.id))
            self.journal.prune()
        return result

    def __exit__(self, kind=None, exc=None, tb=None):
        try:
            if exc is not None:
                exc.request_id = self.id
            if isinstance(exc, JournalWriteError):
                self.unrecorded_failure(exc)
            if exc is not None and not isinstance(exc, JournalWriteError):
                if isinstance(exc, NoSpeech):
                    category = 'speech_no_speech'
                elif isinstance(exc, InvalidSpeech):
                    category = 'speech_invalid'
                elif isinstance(exc, SpeechUnavailable):
                    category = 'speech_unavailable'
                elif isinstance(exc, ProviderUnavailable):
                    category = 'interpreter_unavailable'
                elif isinstance(exc, InvalidProviderResult):
                    category = 'invalid_interpretation'
                elif isinstance(exc, UnsupportedCommand):
                    category = 'unsupported_command'
                elif isinstance(exc, StaleSnapshot):
                    category = 'stale_index_or_catalog'
                elif isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                    category = 'interrupted'
                elif self.stage in ('input', 'parse', 'interpretation_started', 'interpretation'):
                    category = 'unrecognized_or_invalid_command'
                elif self.stage == 'preference':
                    category = 'invalid_preference'
                elif self.stage in ('search', 'retrieval', 'catalog', 'ranking', 'search_query', 'intent_resolved',
                                    'catalog_loaded', 'local_matches', 'local_track_matches', 'retrieval_filtered'):
                    category = 'search_unavailable_or_invalid'
                else:
                    category = 'execution_error'
                # Class/category only: exception text may contain credentials or server bodies.
                self.event('error', {'stage': self.stage, 'category': category, 'type': type(exc).__name__})
                exc.assistant_result = self.finish(
                    {'status': 'interrupted' if category == 'interrupted' else 'error'}, failure=category)
        except JournalWriteError as write_error:
            self.unrecorded_failure(write_error)
            raise
        finally:
            if self.journal is not None:
                self.journal.__exit__()


def history_command(config, arguments=()):
    args = list(arguments)
    with Journal(config) as journal:
        if not args or (len(args) == 1 and args[0].isdigit()):
            limit = int(args[0]) if args else 20
            if not 1 <= limit <= 100:
                raise ValueError('history limit must be in 1..100')
            return {'requests': [dict(r) for r in journal.db.execute('''SELECT id,started_at,source,device,command,
                input,status FROM requests ORDER BY started_at DESC,rowid DESC LIMIT ?''', (limit,))]}
        if len(args) == 2 and args[0] == 'show':
            return journal.detail(args[1])
        if args == ['prune']:
            return {'removed': journal.prune()}
        if args == ['clear', '--yes']:
            with journal.db:
                count = journal.db.execute('SELECT count(*) FROM requests').fetchone()[0]
                journal.db.execute('DELETE FROM requests')
            return {'removed': count}
        if len(args) == 2 and args[0] == 'export':
            path = Path(args[1]).expanduser().resolve()
            repo = Path(__file__).resolve().parents[3]
            if path == repo or repo in path.parents:
                raise ValueError('export personal history outside the repository')
            # One consistent read transaction; exclusive/private output, never overwrite.
            journal.db.execute('BEGIN')
            try:
                with open(path, 'x', encoding='utf-8', opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                    count = 0
                    for row in journal.db.execute('SELECT id FROM requests ORDER BY started_at,rowid'):
                        output.write(json.dumps(journal.detail(row['id']), ensure_ascii=False) + '\n')
                        count += 1
            finally:
                journal.db.rollback()
            return {'exported': count, 'path': str(path)}
    raise ValueError('history: [1..100], show ID, export PATH, prune, or clear --yes')
