"""Local HTTP boundary, explicit locale, bounded hints and failure behavior."""
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from aiohttp import web
from experiments.disc_assistant.assistant.local_service import endpoint
from experiments.disc_assistant.assistant.voice.resident import WhisperServer
from experiments.disc_assistant.assistant.voice.vocabulary import catalog_vocabulary, prompt
from experiments.disc_assistant.assistant.speech import Audio, SpeechContext, InvalidSpeech, SpeechUnavailable
from library.store import Store
from library.tests.helpers import TRACKS


class ResidentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'model.bin').write_bytes(b'fixture')
        self.result={'task':'transcribe','language':'english','text':'Play Numb'}
        self.status=200;self.form=None
        async def infer(request):
            self.form=await request.post()
            return web.json_response(self.result,status=self.status)
        app=web.Application();app.router.add_post('/inference',infer)
        self.runner=web.AppRunner(app);await self.runner.setup();self.addAsyncCleanup(self.runner.cleanup)
        site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        self.provider=WhisperServer(dict(model=str(self.root/'model.bin'),server_url=f'http://127.0.0.1:{port}/inference',timeout=1))
        self.audio=Audio(b'fixture','audio/wav',16000,1)

    async def test_explicit_language_no_translation_and_hints_reset_per_request(self):
        result=await self.provider.transcribe(self.audio,SpeechContext('en','id',('Numb','Linkin Park')))
        self.assertEqual(result.text,'Play Numb')
        self.assertEqual(self.form['language'],'en');self.assertEqual(self.form['translate'],'false')
        self.assertEqual(self.form['prompt'],'Numb, Linkin Park')
        self.assertEqual(self.form['beam_size'],'5')
        await self.provider.transcribe(self.audio,SpeechContext('en','id2'))
        self.assertEqual(self.form['prompt'],'')

    async def test_wrong_language_malformed_body_and_http_errors_are_not_transcripts(self):
        for result in ({'task':'translate','language':'english','text':'Play'},
                       {'task':'transcribe','language':'russian','text':'Play'},
                       {'task':'transcribe','language':'english','text':[]}):
            self.result=result
            with self.assertRaises(InvalidSpeech):
                await self.provider.transcribe(self.audio,SpeechContext('en','id'))
        self.status=503
        with self.assertRaises(SpeechUnavailable):
            await self.provider.transcribe(self.audio,SpeechContext('en','id'))

    async def test_comparison_decoder_is_explicit_and_runtime_default_stays_five(self):
        fast = WhisperServer(self.provider.settings, beam_size=1, best_of=1)
        await fast.transcribe(self.audio, SpeechContext('en', 'fast'))
        self.assertEqual((self.form['beam_size'], self.form['best_of']), ('1', '1'))
        self.assertEqual(fast.evidence()['decoder']['beam_size'], 1)
        await self.provider.transcribe(self.audio, SpeechContext('en', 'default'))
        self.assertEqual((self.form['beam_size'], self.form['best_of']), ('5', '5'))
        for value in (True, 0, 17, '1'):
            with self.assertRaises(ValueError):
                WhisperServer(self.provider.settings, beam_size=value)

    def test_only_explicit_loopback_service_urls(self):
        for value in ('http://localhost:1/inference','http://example.com:1/inference',
                      'http://127.0.0.1:1/load','http://user:pass@127.0.0.1:1/inference',
                      'http://127.0.0.1:1/inference?url=other'):
            with self.assertRaises(ValueError):endpoint(value,'/inference')

    def test_catalog_hints_are_opt_in_bounded_and_snapshot_specific(self):
        config=SimpleNamespace(data_dir=self.root,device_key='test',speech={})
        self.assertEqual(catalog_vocabulary(config)[0],())
        with Store(self.root) as store:
            store.publish('test',TRACKS,{},expected_generation=None)
            config.speech={'catalog_hints':True}
            terms,evidence=catalog_vocabulary(config)
            self.assertIn('Linkin Park',terms);self.assertIn('Numb',terms)
            old=evidence['sha256']
            tracks=[replace(TRACKS[0],title='Title '+str(i),artist='Artist '+str(i)) for i in range(600)]
            store.publish('test',tracks,{},expected_generation=store.head('test')['generation'])
            terms,evidence=catalog_vocabulary(config)
            self.assertTrue(evidence['truncated']);self.assertLessEqual(len(terms),64)
            self.assertLessEqual(len(prompt(terms)),800);self.assertNotEqual(old,evidence['sha256'])
