from io import BytesIO
from contextlib import nullcontext
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from experiments.disc_web.backend.imports import Imports, MAX_UPLOAD
from experiments.disc_web.backend.demo import Demo
from experiments.disc_web.backend.device import BusyError


def finished(imports):
    deadline = time.monotonic() + 3
    while imports.gate.locked() and time.monotonic() < deadline:
        time.sleep(.01)
    if imports.gate.locked():
        raise AssertionError('job did not finish')


class ImportJobTests(unittest.TestCase):
    def test_folder_transfer_scan_and_snapshot_publication_require_separate_starts(self):
        from library.store import Store
        from library.tests.helpers import TRACKS
        from library.tests.test_enrichment import client_fixture, http_fixture
        from experiments.disc_web.backend.catalogue import Catalogue
        from experiments.disc_web.tests.test_device import DeviceTests

        device, session, _, _ = DeviceTests().fixture()
        imports = Imports(device)
        client = client_fixture()
        client.closed.is_set.return_value = False
        session.operation.side_effect = lambda **kwargs: nullcontext(client)
        session.upload_audio.return_value.to_dict.return_value = {'status': 'confirmed'}
        session.scan_library.return_value.to_dict.return_value = {'status': 'confirmed'}
        device.http = http_fixture()
        with tempfile.TemporaryDirectory() as directory:
            device.catalogue = Catalogue(device, imports.gate, directory)
            self.addCleanup(device.catalogue.close)
            key = device.catalogue.key()
            with Store(directory) as store:
                head = store.publish(key, TRACKS, {}, expected_generation=None)
            device.catalogue.verified = (key, 5)
            for index in (1, 2):
                imports.upload(BytesIO(b'RIFF'), 4, f'Album/Disc {index}/Track.wav', 5, f'upload-{index}')
                finished(imports)
                self.assertEqual(imports.state()['phase'], 'done')
            session.scan_library.assert_not_called()
            self.assertIsNone(device.catalogue.worker)
            self.assertTrue(device.catalogue.state()['stale'])
            imports.scan(5, 'scan')
            finished(imports)
            session.scan_library.assert_called_once()
            self.assertEqual(device.catalogue.state()['generation'], head['generation'])
            self.assertIsNone(device.catalogue.worker)
            device.catalogue.start(5, 'sync')
            device.catalogue.worker.join(3)
            result = device.catalogue.state()
            self.assertEqual(result['phase'], 'done')
            self.assertFalse(result['stale'])
            self.assertNotEqual(result['generation'], head['generation'])
            self.assertEqual(result['track_count'], len(TRACKS))
            self.assertEqual([call.args[1] for call in session.upload_audio.call_args_list],
                ['/tmp/sdcard/Album/Disc 1/Track.wav', '/tmp/sdcard/Album/Disc 2/Track.wav'])
            self.assertFalse(imports.gate.locked())

    def device(self):
        device = Mock(demo=False)
        device.protocol_generation.side_effect = lambda value: value
        device.state.return_value = {'connection': 'ready', 'generation': 7, 'busy': False}
        device.session.upload_audio.return_value.to_dict.return_value = {'status': 'confirmed'}
        return device

    def test_short_body_stale_generation_path_and_size_never_reach_controller(self):
        device = self.device()
        imports = Imports(device)
        for name, size, generation in [('test.wav', 4, 6), ('../test.wav', 4, 7),
                                        ('test.exe', 4, 7), ('test.wav', MAX_UPLOAD + 1, 7), ('test.wav', 0, 7)]:
            with self.assertRaises(ValueError):
                imports.upload(BytesIO(b'RIFF'), size, name, generation, 'testrequest')
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            imports.upload(BytesIO(b'RIFF'), 20, 'test.wav', 7, 'shortbody')
        device.session.upload_audio.assert_not_called()
        self.assertFalse(imports.gate.locked())
        self.assertEqual(imports.state()['phase'], 'not_sent')

    def test_one_private_staged_file_is_removed_after_uncertain_transfer(self):
        device = self.device()
        entered, release = threading.Event(), threading.Event()
        source_paths = []
        def upload(source, destination, **kwargs):
            source_paths.append(Path(source))
            self.assertEqual(Path(source).read_bytes(), b'RIFF')
            self.assertEqual(destination, '/tmp/sdcard/Album/Disc 1/Test — Ё.wav')
            self.assertEqual(kwargs['expected_generation'], 7)
            entered.set()
            release.wait(2)
            return Mock(to_dict=lambda: {'status': 'uncertain'})
        device.session.upload_audio.side_effect = upload
        imports = Imports(device)
        imports.upload(BytesIO(b'RIFF'), 4, 'Album/Disc 1/Test — Ё.wav', 7, 'unique-request')
        self.assertTrue(entered.wait(2))
        with self.assertRaises(BusyError):
            imports.scan(7, 'second-request')
        with self.assertRaises(BusyError):
            with imports.foreground():
                pass
        self.assertEqual(imports.state()['name'], 'Album/Disc 1/Test — Ё.wav')
        release.set()
        finished(imports)
        self.assertEqual(imports.state()['phase'], 'uncertain')
        self.assertFalse(source_paths[0].exists())
        device.session.upload_audio.assert_called_once()

    def test_reconnect_during_browser_staging_rejects_before_device_write(self):
        device = self.device()
        class Body(BytesIO):
            def read(self, size):
                device.state.return_value = {'connection': 'ready', 'generation': 8}
                return super().read(size)
        imports = Imports(device)
        imports.upload(Body(b'RIFF'), 4, 'Test.wav', 7, 'staged-generation')
        finished(imports)
        self.assertEqual(imports.state()['phase'], 'not_sent')
        device.session.upload_audio.assert_not_called()

    def test_demo_consumes_but_never_stores_files_or_changes_catalog(self):
        demo = Demo()
        imports = Imports(demo)
        before = demo.browse('tracks')
        with patch.object(tempfile, 'NamedTemporaryFile', side_effect=AssertionError('no demo files')):
            imports.upload(BytesIO(b'RIFF'), 4, 'Test.wav', 1, 'demo-upload')
            finished(imports)
            imports.scan(1, 'demo-scan')
            finished(imports)
        self.assertEqual(imports.state()['phase'], 'done')
        self.assertEqual(demo.browse('tracks'), before)


if __name__ == '__main__':
    unittest.main()
