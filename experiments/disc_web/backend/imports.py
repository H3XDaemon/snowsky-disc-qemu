"""Bounded transient upload staging and one foreground job; never replayed."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import PurePosixPath
import tempfile
import threading
import time

from controller.importing import AUDIO_EXTENSIONS
from experiments.disc_web.backend.device import BusyError

MAX_UPLOAD = 2**31 - 1


class Imports:
    def __init__(self, device):
        self.device = device
        self.gate = threading.Lock()
        self.guard = threading.Lock()
        self.job = None

    @contextmanager
    def foreground(self):
        if not self.gate.acquire(False):
            raise BusyError('An import or another request is in progress. Nothing was queued.')
        try:
            yield
        finally:
            self.gate.release()

    def state(self):
        with self.guard:
            return deepcopy(self.job)

    def update(self, **values):
        with self.guard:
            self.job.update(values)

    def reserve(self, kind, generation, request_id, name=''):
        if not self.gate.acquire(False):
            raise BusyError('Another operation is in progress. Nothing was queued.')
        try:
            state = self.device.state()
            if (state['connection'] != 'ready' or type(generation) is not int
                    or generation != state['generation'] or state.get('busy')):
                raise ValueError('Connection changed or device is busy; nothing was queued')
            with self.guard:
                self.job = dict(id=request_id, kind=kind, name=name, generation=generation,
                                phase='receiving' if kind == 'upload' else 'scanning',
                                bytes=0, total=0, discovered=0, result=None)
        except Exception:
            self.gate.release()
            raise

    def upload(self, stream, size, name, generation, request_id):
        if not isinstance(name, str) or not name or len(('/tmp/sdcard/' + name).encode('utf-8')) > 1023:
            raise ValueError('A bounded relative audio path is required')
        if (any(part in ('', '.', '..') or part != part.strip() or part.endswith('.')
                or len(part.encode('utf-8')) > 240 for part in name.split('/'))
                or any(ord(c) < 32 or ord(c) == 127 or c in '\\:*?"<>|' for c in name)
                or PurePosixPath(name).suffix.lower() not in AUDIO_EXTENSIONS):
            raise ValueError('A plain relative audio path is required')
        if not 0 < size <= MAX_UPLOAD:
            raise ValueError('File must be between 1 byte and 2 GiB minus 1 byte')
        self.reserve('upload', generation, request_id, name)
        staged = None
        try:
            self.update(total=size)
            # Demo consumes the body but never creates a file or touches a device.
            if not self.device.demo:
                staged = tempfile.NamedTemporaryFile()
            remaining, deadline = size, time.monotonic() + 300
            while remaining:
                if time.monotonic() > deadline:
                    raise TimeoutError('Browser transfer timed out before device dispatch')
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise ValueError('Incomplete browser upload; no device write')
                if staged:
                    staged.write(chunk)
                remaining -= len(chunk)
                self.update(bytes=size - remaining)
            if staged:
                staged.seek(0)
            self.update(phase='sending', bytes=0)
            worker = threading.Thread(target=self.run, args=(staged,), daemon=True, name='disc-import')
            worker.start()
        except Exception:
            if staged:
                staged.close()
            self.update(phase='not_sent')
            self.gate.release()
            raise
        return self.state()

    def scan(self, generation, request_id):
        self.reserve('scan', generation, request_id)
        threading.Thread(target=self.run, daemon=True, name='disc-scan').start()
        return self.state()

    def run(self, staged=None):
        try:
            job = self.state()
            state = self.device.state()
            if state['generation'] != job['generation'] or state['connection'] != 'ready':
                self.update(phase='not_sent')
                return
            if self.device.demo:
                # Explicit visual simulation, with no audio metadata inference.
                for step in range(1, 9):
                    time.sleep(.15)
                    self.update(**({'bytes': job['total'] * step // 8} if job['kind'] == 'upload'
                                   else {'discovered': len(self.device.tracks) * step // 8}))
                result = dict(status='confirmed', outcome='demo_only')
            elif job['kind'] == 'upload':
                if getattr(self.device, 'catalogue', None):
                    self.device.catalogue.invalidate()
                staged.flush()
                result = self.device.session.upload_audio(staged.name, '/tmp/sdcard/' + job['name'],
                    expected_generation=self.device.protocol_generation(job['generation']),
                    on_progress=lambda sent, total: self.update(bytes=sent, total=total,
                        phase='verifying' if sent == total else 'sending')).to_dict()
            else:
                if getattr(self.device, 'catalogue', None):
                    self.device.catalogue.invalidate()
                self.device.clear_sources()
                result = self.device.session.scan_library(expected_generation=self.device.protocol_generation(job['generation']),
                    on_progress=lambda count: self.update(discovered=count)).to_dict()
            self.update(phase='done' if result['status'] == 'confirmed' else result['status'], result=result)
        except (ValueError, OSError, RuntimeError):
            self.update(phase='uncertain')
        finally:
            if staged:
                staged.close()
            self.gate.release()
