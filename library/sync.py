"""Publish a stable catalog and enrich what the source can safely observe."""
from http.client import HTTPException
import sqlite3

from controller.compatibility import Capability, require_client
from controller.catalog import CatalogChanged
from controller.events import check_events
from library.observation import observe_current
from library.snapshot import Snapshot


def synchronize(store, device, reader, client, http, *, enrichment=None,
                include_genres=False, before_publish=lambda: None, on_stage=lambda stage: None):
    """Caller owns connection, budgets and cancellation; Library owns data flow.

    Enrichment is optional and partial. Its failure cannot suppress a complete
    catalog, and it never advances playback to fill missing fields.
    """
    expected = store.head(device)['generation']
    on_stage('identity')
    version = require_client(client, Capability.CATALOG_SNAPSHOT)
    client.scan_guard()
    check_events(client)
    on_stage('catalog')
    tracks = reader.read_stable(include_genres=True) if include_genres else reader.read_stable()
    observation = None
    if enrichment:
        on_stage('enrichment')
        draft = Snapshot(None, [dict(ordinal=i, title=t.title, artist=t.artist, album=t.album)
                                for i, t in enumerate(tracks)])
        try:
            observation = observe_current(client, http, draft)
        except CatalogChanged:
            raise
        except (OSError, ValueError, RuntimeError, HTTPException):
            pass
    on_stage('verification')
    check_events(client, during_read=True)
    client.scan_guard()
    before_publish()
    head = store.publish(device, tracks, {'soc_version': version,
        'consistency': 'two-equal-reads-not-atomic', 'identity': 'snapshot-only',
        **({'genres': reader.genres} if include_genres else {})},
        expected_generation=expected)
    enriched = False
    if enrichment and observation and observation.ordinal is not None:
        try:
            enriched = enrichment.record_observation(device, head['generation'], observation)
        except (OSError, sqlite3.Error):
            pass
    return {'head': head, 'enriched': enriched}
