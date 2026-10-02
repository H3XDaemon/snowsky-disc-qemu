"""One serialized playback operation, with fresh selectors and no mutation retries."""
from controller.compatibility import Capability, require_client
from collections import Counter
import time
from contextlib import nullcontext
from uuid import uuid4

from controller.events import merge_snapshot
from controller.playback import GuardedHTTP, matches, verify_playing
from controller.fiio_library import artist_command, album_command
from controller.fiio_http import HTTPClient
from experiments.disc_assistant.assistant.device import (
    PlaybackClient, ObservedSocket, device_lock, validate_scan_events)
from library.catalog import CatalogReader, CatalogChanged
from library.store import StaleSnapshot
from experiments.disc_assistant.assistant.queue import snapshot as queue_snapshot, ensure_continuous


def fresh_selection(config, store, generation, selected, http):
    local = store.documents(generation)
    artist = selected['artist']
    filters = {'artist': artist}
    category = 'artist/song'
    if selected['kind'] == 'album':
        filters = {'album': selected['album'], **({'artist': artist} if artist is not None else {})}
        category = 'artist/album/song' if artist is not None else 'album/song'
    if selected['kind'] == 'track':
        found = [d for d in local if d['id'] == selected['track_id']]
        if len(found) != 1 or any(found[0][k] != selected[k] for k in ('artist', 'album', 'title')):
            raise StaleSnapshot('candidate no longer matches the local snapshot')
        filters['album'] = selected['album']
        category = 'artist/album/song'
    scope = [d for d in local if (artist is None or d['artist'] == artist) and
             ('album' not in filters or d['album'] == filters['album'])]
    reader = CatalogReader(http, page_size=config.page_size, max_tracks=config.max_tracks,
                           max_requests=config.max_requests)
    rows = reader.rows(category, **filters)
    if not rows or rows != reader.rows(category, **filters):
        raise CatalogChanged('playback source is empty or changing; run sync')
    if Counter((r['name'], r['author']) for r in rows) != Counter((d['title'], d['artist']) for d in scope):
        raise CatalogChanged('playback source differs from the snapshot; run sync')
    matching = [r for r in rows if r['name'] == selected.get('title') and r['author'] == artist]
    # Metadata-identical copies are not permanently distinguishable. Policy v1
    # chooses the first CURRENT matching row, not a cached snapshot position.
    index = matching[0]['pos'] if selected['kind'] == 'track' and matching else 0
    if selected['kind'] == 'track' and not matching:
        raise CatalogChanged('requested track disappeared; run sync')
    return category, filters, rows, index, len(matching)


def execute(config, store, ranking, *, shared=None):
    selected = ranking['candidates'][0]
    result = {'operation_id': uuid4().hex, 'selected': selected, 'status': 'not_sent'}
    client = None
    with (device_lock(config.data_dir) if shared is None else nullcontext()):
        try:
            if store.head(config.device_key)['generation'] != ranking['generation']:
                raise StaleSnapshot('catalog changed after ranking; repeat the command')
            generic_album = selected['kind'] == 'album' and selected.get('artist') is None
            if generic_album:
                album_command(selected['album'])
            else:
                artist_command(selected['artist'], 0 if selected['kind'] == 'track' else None, selected.get('album'))
            with (PlaybackClient(config.host, config.tcp_port, config.timeout) if shared is None
                  else nullcontext(shared)) as client:
                require_client(client, 'album_playback' if generic_album else 'artist_playback')
                if config.continuous_context:
                    client.begin_phase('mode')
                    result['mode_change'] = ensure_continuous(client)
                    if result['mode_change']['status'] not in ('confirmed', 'already_satisfied'):
                        return dict(result, status=result['mode_change']['status'],
                                    reason='mode preparation failed; selection was not sent',
                                    mutation_attempted=result['mode_change']['mutation_attempted'])
                    client.begin_phase('selection')
                # Wait only for the remaining stock interval, then revalidate.
                client.wait_for_mutation()
                http = HTTPClient(config.host, config.http_port, config.timeout)
                category, filters, rows, index, equivalents = fresh_selection(
                    config, store, ranking['generation'], selected, http)
                client.scan_guard()
                if store.head(config.device_key)['generation'] != ranking['generation']:
                    raise StaleSnapshot('catalog changed before playback')
                if ranking.get('playback_context'):
                    from experiments.disc_assistant.assistant.context import verify
                    verify(config, client, ranking['playback_context'])
                guard = GuardedHTTP(http, category, filters, rows, index, client)
                if generic_album:
                    client.play_album(selected['album'], http=guard)
                else:
                    client.play_artist(selected['artist'], index if selected['kind'] == 'track' else None,
                                       album=selected.get('album'), http=guard)
                result['confirmation'] = {}
                state = verify_playing(client, selected, rows, config.timeout,
                                       config=config, http=http, diagnostics=result['confirmation'])
                result.update(status='playing' if state else 'uncertain', mutation_attempted=True,
                              fresh_position=index if selected['kind'] == 'track' else None,
                              metadata_equivalent_rows=equivalents, state=state)
                if not state:
                    result['reason'] = 'playback not confirmed before timeout; selection was not retried'
                else:
                    result['queue'] = queue_snapshot(config, client, http, expected=rows, selected=selected,
                        selected_position=index if selected['kind'] == 'track' else None)
                    result['queue']['source'] = {'category': category, **filters}
                    if config.continuous_context and result['queue']['mode_name'] != 'repeat_list':
                        raise CatalogChanged('continuous mode changed externally; selection was not retried')
        except (OSError, ValueError, RuntimeError) as exc:
            attempted = bool(client and client.mutation_attempted) or result.get('mode_change', {}).get('mutation_attempted', False)
            result.update(status='uncertain' if attempted else 'not_sent', mutation_attempted=attempted,
                          reason=str(exc), error_type=type(exc).__name__, retry='never automatic')
            if isinstance(exc, CatalogChanged) and exc.diagnostics is not None:
                result.setdefault('confirmation', {})['queue'] = exc.diagnostics
    return result
