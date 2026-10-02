#!/usr/bin/env python3
"""Read tinyshim's current capture and export a frame-aligned WAV snapshot."""
import argparse
import os
from pathlib import Path
import struct
import wave


def capture_info(rootfs):
    root = Path(rootfs)
    with (root / 'audio.fmt').open('rb') as f:
        channels, sample_bytes, rate = struct.unpack('<III', f.read(12))
        stamp = os.fstat(f.fileno()).st_mtime_ns
    if not (1 <= channels <= 8 and sample_bytes in (1, 2, 3, 4) and 1 <= rate <= 768000):
        raise ValueError('Invalid capture format')
    stat = (root / 'audio.pcm').stat()
    frame_bytes = channels * sample_bytes
    size = stat.st_size // frame_bytes * frame_bytes
    return dict(generation=f'{stat.st_ino}-{stamp}', channels=channels,
                sample_bytes=sample_bytes, rate=rate, bytes=size,
                seconds=size / (frame_bytes * rate))


STREAM = 'emu/asound/card0/pcm3p/sub0'
ACTIVITY = {b'c': 'closed', b's': 'silence', b'p': 'samples'}


def output_state(rootfs):
    """The stock output stream as the audio shim last reported it. Never raises.

    `stream` is the ALSA state a program on the player reads in
    /proc/asound/card0/pcm3p/sub0/status (closed, PREPARED, RUNNING). Stock keeps
    the stream RUNNING while paused and feeds it zeros, so `activity` tells
    silence from samples.
    """
    root = Path(rootfs)
    closed = dict(stream='closed', activity='closed', format=None, rate=None, channels=None)
    for _ in range(3):
        try:
            status = (root / STREAM / 'status').read_text()
            parameters = (root / STREAM / 'hw_params').read_text()
            activity = ACTIVITY.get((root / 'emu/audio-state').read_bytes()[:1], 'closed')
            if (root / STREAM / 'status').read_text() != status:
                continue                    # the shim replaced the pair between the two reads
        except OSError:
            return closed
        fields = dict(line.split(':', 1) for line in (status + parameters).splitlines() if ':' in line)
        try:
            return dict(stream=fields['state'].strip(), activity=activity, format=fields['format'].strip(),
                        rate=int(fields['rate'].split()[0]), channels=int(fields['channels']))
        except (KeyError, ValueError, IndexError):
            if 'state' not in fields:
                return closed               # both files say "closed"
    return closed                           # still changing: report the settled state next time


def reset_output(rootfs):
    """After the guest was stopped without pcm_close: nothing is playing any more."""
    root = Path(rootfs)
    for name in ('status', 'hw_params'):
        path = root / STREAM / name
        if path.parent.is_dir():
            path.write_text('closed\n')
    marker = root / 'emu/audio-state'
    if marker.exists():
        marker.write_bytes(b'c')


def read_chunk(rootfs, generation, offset, limit=262144):
    info = capture_info(rootfs)
    frame_bytes = info['channels'] * info['sample_bytes']
    if generation != info['generation']:
        raise ValueError('Capture changed')
    if offset < 0 or offset % frame_bytes:
        raise ValueError('Offset must be a nonnegative frame boundary')
    if offset >= info['bytes']:
        return b''
    count = min(limit, max(0, info['bytes'] - offset)) // frame_bytes * frame_bytes
    with (Path(rootfs) / 'audio.pcm').open('rb') as f:
        f.seek(offset)
        data = f.read(count)
    if capture_info(rootfs)['generation'] != generation:
        raise ValueError('Capture changed')
    return data[:len(data) // frame_bytes * frame_bytes]


def export_wav(rootfs, output):
    info = capture_info(rootfs)
    with wave.open(str(output), 'wb') as wav:
        wav.setparams((info['channels'], info['sample_bytes'], info['rate'], 0, 'NONE', 'NONE'))
        offset = 0
        while offset < info['bytes']:
            data = read_chunk(rootfs, info['generation'], offset, min(262144, info['bytes']-offset))
            if not data:
                raise ValueError('Capture truncated during export')
            offset += len(data)
            if info['sample_bytes'] == 1:  # WAV stores 8-bit PCM unsigned.
                data = bytes(b ^ 128 for b in data)
            wav.writeframesraw(data)
    return info


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--rootfs', default=os.environ.get('ROOTFS', '/work/rootfs'))
    args = parser.parse_args()
    try:
        info = export_wav(args.rootfs, args.output)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f'Audio capture unavailable: {error}\n')
    print(f"{args.output}: {info['seconds']:.2f}s, {info['rate']} Hz, "
          f"{info['channels']} channels, {info['sample_bytes']*8}-bit PCM")
