"""Disposable real Typesense lexical/vector/hybrid comparison, no device transport."""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from types import SimpleNamespace

from experiments.disc_assistant.assistant.nlu.intents import parse
from experiments.disc_assistant.assistant.nlu.languages import load_languages
from experiments.disc_assistant.assistant.ranking import rank
from experiments.disc_assistant.assistant.resolver import infer
from experiments.disc_assistant.assistant.voice.catalog_evaluation import selection_matches
from library.catalog import Track
from library.artists import artist_names
from library.store import Store
from library.search.typesense import Search, create_client, FIELDS
from library.transliteration import fold, projected_aliases
from experiments.disc_assistant.assistant.nlu.evaluation.encoder import digest

ROOT = Path(__file__).resolve().parents[5]


class Retrieval:
    def __init__(self, base, client, collection, documents, encoder, mode, distance=.5, alpha=.5):
        self.signature = base.signature
        self.base, self.client, self.collection = base, client, collection
        self.documents, self.encoder, self.mode = documents, encoder, mode
        self.distance, self.alpha = distance, alpha
        self.semantic_query = None

    async def search(self, store, device, query, *, limit=10, fields=None):
        if self.mode == 'lexical':
            return await self.base.search(store, device, query, limit=limit, fields=fields)
        vector = self.encoder.encode([self.semantic_query or query])[0].tolist()
        params = {'collection': self.collection, 'per_page': limit,
                  'q': fold(query) if self.mode == 'hybrid' else '*',
                  'query_by': ','.join(fields or FIELDS), 'drop_tokens_threshold': 0,
                  'num_typos': 2, 'split_join_tokens': 'off', 'prefix': True,
                  'query_by_weights': ','.join(str(dict(zip(FIELDS,(6,5,2,4,3,1,5)))[f]) for f in (fields or FIELDS)),
                  'vector_query': 'embedding:('+json.dumps(vector)+f', k:{limit}, alpha:{self.alpha}, distance_threshold:{self.distance})',
                  'exclude_fields': 'embedding'}
        response = await self.client.multi_search.perform({'searches': [params]}, {})
        result = response['results'][0]
        if result.get('error') or result.get('search_cutoff'):
            raise ValueError('incomplete vector/hybrid response')
        candidates = []
        for hit in result['hits']:
            doc = hit['document']; expected = self.documents.get(doc['id'])
            if expected is None or any(doc[k] != expected[k] for k in ('generation','artist','title','album')):
                raise ValueError('vector result outside the pinned catalog')
            candidates.append(dict(expected, vector_distance=hit.get('vector_distance')))
        return {'generation': store.head(device)['generation'], 'found': result['found'], 'candidates': candidates}


def summary(rows):
    positives = [r for r in rows if r['expected'] is not None]
    negatives = [r for r in rows if r['expected'] is None]
    return {'total': len(rows), 'correct': sum(r['passed'] for r in rows),
            'positive_count': len(positives), 'correct_selections': sum(r['passed'] for r in positives),
            'absence_count': len(negatives), 'false_selections': sum(not r['passed'] for r in negatives),
            'raw_top1_correct': sum(r['raw_top1_correct'] for r in positives),
            'raw_recall_at_10_count': sum(r['raw_recall_at_10'] for r in positives)}


async def evaluate(corpus, encoder):
    env = {**os.environ, 'TYPESENSE_API_KEY': secrets.token_hex(32), 'TYPESENSE_PORT': '0'}
    compose = ['docker','compose','--env-file','/dev/null','-f',str(ROOT/'experiments/disc_assistant/assistant/compose.yaml'),
               '-p','disc-nlu-'+secrets.token_hex(5)]
    def docker(*args):
        return subprocess.run(compose+list(args),env=env,capture_output=True,text=True,check=True,timeout=90).stdout
    client = None
    try:
        docker('up','-d','--pull','never')
        deadline = time.monotonic()+60
        while True:
            host, port = docker('port','typesense','8108').strip().rsplit(':',1)
            if int(port)>0: break
            if time.monotonic()>deadline: raise TimeoutError('no Typesense port')
            await asyncio.sleep(.5)
        config = SimpleNamespace(search_host=host,search_port=int(port),search_protocol='http',timeout=8,
                                 aliases={},device_key='synthetic',locale='en')
        client = create_client(config, env['TYPESENSE_API_KEY'])
        while True:
            try:
                if (await client.api_call.get('/health', dict)).get('ok'): break
            except Exception:
                if time.monotonic()>deadline: raise
            if time.monotonic()>deadline: raise TimeoutError('Typesense readiness timed out')
            await asyncio.sleep(.5)
        with tempfile.TemporaryDirectory(prefix='disc-nlu-catalog-') as tmp, Store(tmp) as store:
            tracks = [Track(**doc, position=i, raw={'pos':i,'name':doc['title'],'author':doc['artist']})
                      for i,doc in enumerate(corpus['tracks'])]
            head = store.publish('synthetic',tracks,{},expected_generation=None)
            base = Search(client,{},['http',host,int(port)])
            await base.build(store,'synthetic')
            docs = store.documents(head['generation']); documents = {doc['id']:doc for doc in docs}
            texts = [doc['artist']+' — '+doc['title']+' — '+doc['album'] for doc in docs]
            vectors = encoder.encode(texts)
            collection = 'disc_nlu_vectors'
            await client.collections.create({'name':collection,'fields':[
                {'name':f,'type':'string[]' if f.endswith('_aliases') or f == 'artists' else 'string'} for f in FIELDS]+
                [{'name':'generation','type':'string','index':False},
                 {'name':'embedding','type':'float[]','num_dim':encoder.info['dimensions']}]})
            payload = []
            for doc,vector in zip(docs,vectors):
                projected = {**doc,'embedding':vector.tolist()}
                for name in ('title','artist','album'):
                    projected[name+'_aliases']=projected_aliases(doc[name],[])
                projected['artist_aliases'] = list(dict.fromkeys(alias
                    for name in artist_names(doc['artist']) for alias in projected_aliases(name, [])))
                payload.append(projected)
            imported=await client.collections[collection].documents.import_(payload,{'action':'create'})
            if len(imported)!=len(docs) or not all(r.get('success') for r in imported):
                raise ValueError('incomplete vector collection')
            async def run(mode, split, distance=.5, alpha=.5):
                search=Retrieval(base,client,collection,documents,encoder,mode,distance,alpha)
                rows=[]
                for case in corpus['queries']:
                    if case['split']!=split:continue
                    config.locale=case['locale']
                    intent=parse(case['text'],load_languages((case['locale'],)))
                    resolved=infer(intent,docs,{})
                    query=(resolved.artist+' '+resolved.title) if resolved.artist is not None else resolved.query
                    search.semantic_query = query
                    start=time.monotonic()
                    raw=await search.search(store,'synthetic',fold(query),limit=10)
                    result=await rank(config,store,search,intent)
                    selected=result['candidates'][0] if result['candidates'] else None
                    def match(doc):return selection_matches(dict(doc,kind='track'),case['expected']) if case['expected'] else False
                    rows.append({'id':case['id'],'text':case['text'],'expected':case['expected'],
                                 'passed':selection_matches(selected,case['expected']),'selection':selected,
                                 'raw_top1_correct':bool(raw['candidates']) and match(raw['candidates'][0]),
                                 'raw_recall_at_10':any(match(d) for d in raw['candidates']),
                                 'parsed_intent':asdict(intent), 'resolved_intent':asdict(resolved),
                                 'raw_candidates':[{k:d.get(k) for k in ('id','artist','title','album','vector_distance')} for d in raw['candidates']],
                                 'guarded_retrieval':result['retrieval'],
                                 'diagnostic_total_ms':round((time.monotonic()-start)*1000,3)})
                return rows
            report={'corpus_sha256':digest(corpus),'catalog_generation':head['generation'],
                    'embedding_pipeline':encoder.signature,'document_template':'artist — title — album; v1',
                    'scope':'Track candidates only. All variants share lexical-v4 constraints and exact-match fast path. No learned interpreter or player access.',
                    'variants':{}}
            # Choose distance/alpha using only artist-disjoint development queries.
            for mode in ('lexical','vector','hybrid'):
                settings=[(None,None)] if mode=='lexical' else [(d,a) for d in (.3,.5,.7) for a in ((.3,.7) if mode=='hybrid' else (.5,))]
                best=None; trials=[]
                for distance,alpha in settings:
                    rows=await run(mode,'development',distance,alpha);score=summary(rows)
                    trials.append({'distance':distance,'alpha':alpha,'metrics':score})
                    key=(-score['false_selections'],score['correct_selections'],score['raw_recall_at_10_count'])
                    if best is None or key>best[0]:best=(key,distance,alpha)
                _,distance,alpha=best
                rows=await run(mode,'test',distance,alpha)
                report['variants'][mode]={'development_trials':trials,'selected':{'distance':distance,'alpha':alpha},
                                          'test':summary(rows),'cases':rows}
            return report
    finally:
        try:
            if client is not None:await client.api_call.aclose()
        finally:
            docker('down','--volumes','--remove-orphans')
