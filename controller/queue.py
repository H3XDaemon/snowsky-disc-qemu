"""Native queue observations; independent of search and recommendation policy."""
from controller.models import WirePlaybackState, PlaybackSource
from controller.compatibility import Capability, require_client
from collections import Counter
from controller.catalog import CatalogReader, CatalogChanged
from controller.playback import album_matches

MODES = ('list_once', 'random', 'repeat_one', 'repeat_list', 'single_once')


def queue_failure(code, message, **evidence):
    """Small structured proof of a failed guard; no full queue or device paths."""
    raise CatalogChanged(message, diagnostics={'stage': 'queue_verification', 'code': code, **evidence})


def brief_song(state):
    song = state.get('song') or {}
    return {'state': state.get('state'), 'playerflag': state.get('playerflag'),
            'pos_id': song.get('pos_id'), 'title': str(song.get('song_name', ''))[:200],
            'artist': str(song.get('song_artist_name', ''))[:200],
            'album': str(song.get('song_album_name', ''))[:200]}


def read_queue(config, http):
    marks = []

    class Pages:
        def catalog(self, *args, **kwargs):
            page = http.catalog(*args, **kwargs)
            mark = page.get('mark')
            total = page.get('total')
            if (type(total) is not int or total < 0 or type(mark) is not int
                    or not -1 <= mark < total or (total == 0 and mark != -1)):
                queue_failure('invalid_mark', 'missing or invalid queue mark',
                              mark=mark if type(mark) is int else None,
                              total=total if type(total) is int else None)
            marks.append(mark)
            return page

    reader = CatalogReader(Pages(), page_size=config.page_size, max_tracks=config.max_tracks,
                           max_requests=config.max_requests)
    rows = reader.rows('curlist/song')
    second = reader.rows('curlist/song')
    if rows != second or len(set(marks)) != 1:
        queue_failure('unstable_queue', 'queue changed during observation',
                      first_total=len(rows), second_total=len(second), rows_equal=rows == second,
                      marks=marks[:8], mark_observations=len(marks))
    return {'items': rows, 'total': len(rows), 'mark': marks[0]}


def continuation(mode, total, mark):
    if not total:
        return 'empty'
    if mark < 0:
        return 'unknown_current_position'
    if mode == 0:
        return 'stop_after_current' if mark == total - 1 else 'remaining_queue_then_stop'
    return ('random_within_queue', 'repeat_current', 'wrap_queue', 'stop_after_current')[mode-1]


def snapshot(config, client, http, *, expected=None, selected=None, selected_position=None):
    mode = client.play_mode()
    result = read_queue(config, http)
    # A fresh state read AFTER HTTP checks catches observed source replacement.
    # No stock atomic revision exists; report this as an observation, not a lease.
    try:
        state = client.now_playing()
    except TimeoutError:
        state = {}
    client.scan_guard()
    after_mode = client.play_mode()
    if after_mode != mode:
        queue_failure('mode_changed', 'play mode changed during queue observation',
                      before_mode=mode, after_mode=after_mode)
    if expected is not None:
        def keys(rows):
            return Counter((r['name'], r['author']) for r in rows)
        actual_keys, expected_keys = keys(result['items']), keys(expected)
        if actual_keys != expected_keys:
            queue_failure('membership_mismatch', 'actual queue differs from the requested source',
                          expected_total=len(expected), observed_total=result['total'],
                          missing_count=sum((expected_keys - actual_keys).values()),
                          unexpected_count=sum((actual_keys - expected_keys).values()))
        song = state.get('song', {})
        mark = result['mark']
        source = selected.get('source') if selected and selected.get('source') is not None else PlaybackSource.ALBUM if selected and selected['kind'] == 'album' and selected.get('artist') is None else PlaybackSource.ARTIST_SCOPE
        row = result['items'][mark] if 0 <= mark < result['total'] else None
        checks = {'playing': state.get('state') == WirePlaybackState.PLAYING, 'source': state.get('playerflag') == source,
                  'mark_in_bounds': row is not None, 'position': song.get('pos_id') == mark + 1,
                  'title': row is not None and song.get('song_name') == row['name'],
                  'artist': row is not None and song.get('song_artist_name') == row['author']}
        if not all(checks.values()):
            queue_failure('state_mismatch', 'queue selection is not confirmed by fresh playback state',
                          failed_checks=[key for key, passed in checks.items() if not passed],
                          observed=brief_song(state), mark=mark, total=result['total'],
                          expected={'state': 0, 'playerflag': source, 'pos_id': mark + 1,
                                    'title': row['name'][:200] if row else None,
                                    'artist': row['author'][:200] if row else None})
        if selected is not None and ((selected.get('artist') is not None and song.get('song_artist_name') != selected['artist']) or
                (selected['kind'] == 'track' and song.get('song_name') != selected['title']) or
                (selected.get('selected_index') is not None and (song.get('song_name') != selected['title']
                    or song.get('song_artist_name') != selected['target_artist']))):
            queue_failure('selection_mismatch', 'playback changed during queue observation',
                          observed=brief_song(state),
                          expected_artist=(selected.get('artist') or '')[:200],
                          expected_title=(selected.get('title') or '')[:200])
        if selected_position is not None and mark != selected_position:
            queue_failure('position_mismatch', 'queue position differs from the requested selection',
                          expected_position=selected_position, observed_position=mark)
        if selected is not None and not album_matches(state, selected, config=config, http=http):
            queue_failure('album_mismatch', 'playback album differs from the requested selection',
                          expected_album=(selected.get('album') or '')[:200], observed=brief_song(state))
        if (selected is not None and selected.get('album') is not None
                and song.get('song_album_name') != selected['album']):
            fresh = client.now_playing()
            if any(fresh.get(key) != state.get(key) for key in ('state', 'playerflag', 'song')):
                queue_failure('album_resolution_race', 'playback changed while resolving the shortened album',
                              before=brief_song(state), after=brief_song(fresh))
        # The extra HTTP reads for a shortened album can receive scan events too.
        client.scan_guard()
    result.update(mode=mode, mode_name=MODES[mode], state=state,
                  continuation=continuation(mode, result['total'], result['mark']),
                  consistency='two_equal_reads_not_atomic',
                  playback_known=bool(state.get('song')) and state.get('state') in (WirePlaybackState.PLAYING, WirePlaybackState.PAUSED))
    return result


def _row_matches(state, row, index):
    from pathlib import PurePosixPath
    song = state.get('song') or {}
    names = {song.get('song_name'), PurePosixPath(song.get('song_file_path') or '').name}
    # Queue selection changes the source flag to type 0 even if the queue was
    # created from type 7. Position, row identity and stable membership are proof.
    return (song.get('pos_id') == index + 1
            and row['name'] in names and (not row['author'] or row['author'] == song.get('song_artist_name')))


def previous_in_queue(config, client, http):
    """One guarded predecessor selection, independent of elapsed time or shuffle history.

    At the start of the displayed queue, leave playback unchanged in every mode.
    No atomic device revision exists; observed races block or make the result uncertain.
    """
    return _select_queue(config, client, http, predecessor=True)


def select_queue_index(config, client, http, index, *, expected=None):
    """Select one current queue position with exact displayed-membership protection."""
    return _select_queue(config, client, http, index=index, expected=expected)


def _select_queue(config, client, http, *, predecessor=False, index=None, expected=None):
    import time
    from uuid import uuid4
    from controller.controls import identity
    from controller.catalog import verify_expected
    result = {'operation_id': uuid4().hex, 'action': 'previous' if predecessor else 'play_queue_index', 'status': 'not_sent',
              'mutation_attempted': False, 'navigation_policy': 'previous_queue_row' if predecessor else 'explicit_queue_row'}
    try:
        if not predecessor and (type(index) is not int or not 0 <= index <= 65535):
            raise ValueError('queue index outside 0..65535')
        require_client(client, Capability.QUEUE_NAVIGATION)
        client.wait_for_mutation()
        before = snapshot(config, client, http)
        verify_expected(before['items'], expected)
        current = before['mark']
        state = before['state']
        if (state.get('state') not in (WirePlaybackState.PLAYING, WirePlaybackState.PAUSED) or not 0 <= current < before['total']
                or not _row_matches(state, before['items'][current], current)):
            raise CatalogChanged('current queue position is not confirmed; no selection sent')
        if predecessor and current == 0:
            return dict(result, status='already_satisfied', outcome='queue_start', state=state, queue=before)
        if predecessor:
            index = current - 1
        if index >= before['total']:
            raise ValueError('position outside current queue')
        target = before['items'][index]

        class Guard:
            def catalog(self, category, offset=0, limit=200, **filters):
                if (category, offset, limit, filters) != ('curlist/song', index, 1, {}):
                    raise ValueError('unexpected queue selection preflight')
                fresh = snapshot(config, client, http)
                if (any(fresh[k] != before[k] for k in ('items', 'mark', 'mode'))
                        or identity(fresh['state']) != identity(state)
                        or fresh['state'].get('state') != state['state']):
                    raise CatalogChanged('queue or playback changed before selection')
                return {'total': fresh['total'], 'items': [fresh['items'][index]]}

        client.play_queue_index(index, http=Guard())
        result.update(mutation_attempted=True, selected_position=index)
        deadline = time.monotonic() + config.timeout
        while time.monotonic() < deadline:
            try:
                after = snapshot(config, client, http)
            except TimeoutError:
                continue
            if after['items'] != before['items'] or after['mode'] != before['mode']:
                raise CatalogChanged('queue changed after selection; selection was not retried')
            if (after['mark'] == index and after['state'].get('state') == WirePlaybackState.PLAYING
                    and _row_matches(after['state'], target, index)):
                return dict(result, status='confirmed', outcome='track_changed', state=after['state'], queue=after)
            time.sleep(.15)
        result.update(status='uncertain', reason='queue row not confirmed; selection was not retried')
    except (OSError, ValueError, RuntimeError) as exc:
        attempted = result['mutation_attempted'] or bool(client.mutation_attempted)
        result.update(status='uncertain' if attempted else 'not_sent', mutation_attempted=attempted,
                      reason=str(exc), error_type=type(exc).__name__)
        if isinstance(exc, CatalogChanged) and exc.diagnostics is not None:
            result['confirmation'] = {'queue': exc.diagnostics}
    return result
