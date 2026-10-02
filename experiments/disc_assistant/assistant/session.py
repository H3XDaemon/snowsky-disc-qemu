"""Catalog synchronization over a one-shot or borrowed persistent session."""
from contextlib import nullcontext

from controller.compatibility import Capability, require_client
from controller.fiio_http import HTTPClient
from controller.fiio_link import Client
from library.catalog import CatalogReader, CatalogChanged


from controller.events import check_events

def sync(config, store, *, shared=None, reuse_unchanged=False):
    expected = store.head(config.device_key)['generation']
    with (Client(config.host, config.tcp_port, config.timeout) if shared is None else nullcontext(shared)) as client:
        version = require_client(client, Capability.CATALOG_SNAPSHOT)
        http = HTTPClient(config.host, config.http_port, config.timeout)
        reader = CatalogReader(http, page_size=config.page_size, max_tracks=config.max_tracks,
                               max_requests=config.max_requests)
        check_events(client)
        tracks = reader.read_stable()
        check_events(client, during_read=True)
    if reuse_unchanged and expected and store.matches_tracks(expected, tracks):
        if store.head(config.device_key)['generation'] != expected:
            raise CatalogChanged('another import published during sync')
        return dict(store.head(config.device_key), reused=True)
    return store.publish(config.device_key, tracks, {
        'soc_version': version, 'host': config.host, 'tcp_port': config.tcp_port,
        'http_port': config.http_port, 'consistency': 'two-equal-reads-not-atomic',
        'identity': 'snapshot-only'}, expected_generation=expected)
