"""Synthetic retrieval ablation, not an independent acceptance or player command."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from library.catalog import Track
from library.store import Store
from library.search.typesense import Search, create_client
from library.transliteration import fold
from experiments.disc_assistant.assistant.nlu.intents import Intent
from experiments.disc_assistant.assistant.nlu.languages import load_languages
from experiments.disc_assistant.assistant.ranking import score_tracks, ordered


async def run(output, port):
    output.mkdir(parents=True, exist_ok=False)
    store = Store(output / 'data')
    rows = [('Signal Beta', 'Test Atlas', 'Original'), ('Shared Signal', 'Test Atlas;Test Guest', 'Duet'),
            ('Тишина', 'Артист Ё', 'Альбом'), ('Signal Alpha', 'Test Atlas', 'Original')]
    rows += [('Test Atlas Signal Beta', f'Noise Artist {i}', 'Covers') for i in range(80)]
    tracks = [Track(title, artist, album, i, dict(pos=i, name=title, author=artist)) for i,(title,artist,album) in enumerate(rows)]
    store.publish('fixture', tracks, {}, expected_generation=None)
    config = SimpleNamespace(search_host='127.0.0.1', search_port=port, search_protocol='http', timeout=10)
    sdk = create_client(config, os.environ['TYPESENSE_API_KEY'])
    search = Search(sdk, {}, ['http', '127.0.0.1', port])
    cases = [dict(id='top-k-pressure', artist='Test Atlas', title='Signal Beto', expected=0, scope=['Test Atlas']),
             dict(id='credit-member', artist='Test Guest', title='Shared Sgnal', expected=1, scope=['Test Atlas;Test Guest']),
             dict(id='cyrillic', artist='Артист Ё', title='Тишина', expected=2, scope=['Артист Ё']),
             dict(id='joined-title', artist='Test Atlas', title='SignalAlpha', expected=3, scope=['Test Atlas']),
             dict(id='missing-version', artist='Test Atlas', title='Signal Alpha remix', expected=None, scope=['Test Atlas'])]
    records = []
    try:
        await search.build(store, 'fixture')
        for c in cases:
            for variant, join, scope in [('baseline','off',None),('split-fallback','fallback',None),
                    ('split-always','always',None),('artist-before-top-k','off',c['scope'])]:
                started = time.perf_counter()
                reply = await search.search(store, 'fixture', fold(c['artist']+' '+c['title']), limit=50,
                                            artist_scope=scope, split_join=join)
                # The historical baseline filters AFTER retrieval. Keep it here
                # to isolate prefiltering from changes to ranking or query words.
                pool = [d for d in reply['candidates'] if d['artist'] in c['scope']]
                ranked = ordered(score_tracks(Intent(c['artist']+' '+c['title'],'track',c['artist'],c['title']), pool, {}, load_languages(('en',))))
                selected = int(ranked[0]['track_id'].rsplit(':',1)[1]) if ranked else None
                records.append(dict(case=c['id'], variant=variant, correct=selected==c['expected'],
                    selected=selected, expected=c['expected'], found=reply['found'], returned=len(reply['candidates']), scoped=len(pool),
                    elapsed_ms=round((time.perf_counter()-started)*1000,3)))
        report = {'scope':'examined synthetic retrieval regression; not end-to-end acceptance', 'cases':cases,
                  'schema_signature':search.signature, 'rows':records}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(records,ensure_ascii=False,indent=2))
    finally:
        head = store.head('fixture')
        if head.get('collection'):
            await sdk.collections[head['collection']].delete()
        await sdk.api_call.aclose()
        store.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--port',type=int,default=18118)
    a=p.parse_args();asyncio.run(run(a.output,a.port))

if __name__=='__main__': main()
