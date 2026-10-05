# Audio capture and browser playback

Local playback works through the stock firmware decoder → tinyalsa → `emulator/shims/tinyshim.c`.
No audio patches to `mq_player` are needed; the key-enable patch is unrelated.

```sh
./emulator/run.sh boot
./emulator/run.sh view                 # http://localhost:8080 → click the lower-left headphone jack
# Browse files → select a track in the device UI.
./emulator/run.sh audio                # snapshot → shots/audio.wav
```

The lower-left headphone jack (**Enable sound**) joins the current captured PCM
through Web Audio with a 300 ms look-back; it does not replay the recording from
its beginning. Click the jack again to mute. **Debug → Replay capture** starts
the current recording again. These viewer controls do
not change firmware play/pause state. Browser playback buffers a little and can pause if
emulation cannot supply data fast enough. If live playback falls more than two seconds
behind (for example after a background-tab stall), it drops queued history and rejoins
the current output. Replay mode deliberately preserves its position. PCM decoding and
DAC gains are unchanged. Debug labels the mode `live` / `replay`, and adds `silence`
when the decoded chunk contains only zero samples. The captured duration includes
stock service silence while paused; it is not proof of music playback.
WAV export also works without a browser.
Each `pcm_open` starts a new recording, replacing `/audio.pcm`; export before switching
tracks if you want to keep it.

## Output stream state

On the player `/proc/asound/card0/pcm3p/sub0/status` and `hw_params` show the
stock output stream. A real procfs cannot be extended, so the audio shim keeps
the same two files under **`/emu/asound/card0/pcm3p/sub0/`** in the guest
(`closed`, or `state: PREPARED|RUNNING` with `owner_pid`, and the negotiated
`format`, `channels`, `rate`, `period_size`, `buffer_size`). A program that
takes the card directory as a parameter reads the output there; a path fixed to
`/proc/asound` cannot be served to a static program.

Stock keeps the stream **RUNNING while paused** and feeds it zeros, so the stream
state alone does not tell playing from paused. `emu/audio-state` holds one byte:
`c` closed, `s` silence, `p` samples. From Python:

```python
from emulator.runtime.audio import output_state
output_state('/work/rootfs')
# {'stream': 'RUNNING', 'activity': 'samples', 'format': 'S32_LE', 'rate': 44100, 'channels': 2}
```

The reader never fails: while the shim replaces the two files it reports the
settled state, and stopping the guest resets the tree to `closed` (a killed
player never closes its stream). The viewer's `/audio.json` carries the same
object as `output`. A 16-bit 44.1 kHz
file is fed to the DAC as `S32_LE` at 44100 Hz. A silent passage of a track is
reported as silence too.

## Analog output (jack) model

Stock detects its outputs in the `adc_check` thread, three times a second with
about a second of debounce (V2.57, read from the binary and confirmed live):

| Output | What stock reads | Plugged when |
| --- | --- | --- |
| 3.5 mm | `/dev/gpio` level of `pb20` | 1 |
| 4.4 mm balanced | ADC channel 2 (`/dev/jz_adc_aux_2`) | 801–949 or ≥ 1501; 1151–1349 is "none" |

The result selects the volume curve, and an **unplug pauses local playback**.
It does not gate playback: with nothing plugged from boot, stock still plays.

The model is V2.57 data (`JACK` is refused for another firmware profile). By
default it is off and stock sees unmodelled pins (the `pb20` request
fails, the ADC read returns no sample). `JACK=3.5`, `4.4` or `none` at setup or
boot turns it on; the state is stored. At runtime:

```sh
curl -H 'Content-Type: application/json' -d '{"name":"jack","state":"none"}' \
  http://localhost:8080/peripheral        # or Peripherals.set_jack('none')
```

`JACK=off` removes the model. Observed with it on: stock's own flags follow the
plug (`83a775` 3.5 mm, `83a774` balanced); pulling the plug while a track plays
pauses it (`a202` state 1, the stream keeps running on zeros); a 4.4 mm plug sets
the balanced flag and does not resume; Play resumes. Plugging emits no message.

Not reproduced: on a player with no output connected stock was seen to show
"playing" while holding no file and with ALSA closed. Here an unplug before or
during playback only pauses, and Play or a new selection plays normally. That
state needs a hardware probe; the values above are threshold fixtures, not
measured voltages, and line-out has no detector in the binary.

## Physical volume and browser sound

The physical controls now honor the app's volume-gesture assignments ([KEYS.md](keys.md)).
`fbshim` mirrors the stock DAC attenuation writes (`0x80014d2d` / `0x80014d2f`) into
`emu/dac-left` / `emu/dac-right`; `/audio.json` reports the corresponding `output_gain`.
Web Audio applies these gains independently to the two output channels, with a short ramp.
CS43131 attenuation uses 0.5 dB steps and value 255 for digital mute, per the
[Cirrus Logic datasheet](https://statics.cirrus.com/pubs/proDatasheet/CS43131_DS1155F2.pdf).

Verified live while paused: volume 115 → 114 → 115 gives gains
0.37584 → 0.35481 → 0.37584. Browser graph wiring, gain updates and stopping queued audio
when the guest powers off are covered by `viewer/tests/test_audio_browser.js`.
Raw capture and WAV export remain pre-DAC samples: changing output gain does not rewrite
the recording. This models digital volume, not the analog amplifier/output circuitry.

## The actual blocker

`get_i2s3_pcm_device` (`FUN_0047670c`) scans `/proc/asound/cards` for **x2000 - x2000**.
It extracts the card number from the second character of the matching line and uses device 3.
LinuxKit has no such card, so `set_out_device` (`FUN_00474f84`) left `ctx+0x58` at
**0 = NO_OUT_DEV**, instead of **6 = I2S3_OUT**.

The fix is `emulator/shims/asound.cards`, installed as `/etc/asound.cards`. The preload shim redirects
only `fopen("/proc/asound/cards", ...)` to that file and forwards other paths to the guest
libc's `fopen64`. No host procfs changes or firmware instruction patches are involved.
The firmware discovers **hw:0,3** and selects its normal I2S3 route.
Its format table at `0x82e010` already supports 16/24/32 bits.

Corrections to the previous investigation:

- The caps table was not globally empty: the selected **NO_OUT_DEV** entry was empty.
  GDB confirmed populated entries for LOCAL_ANALOG (1) and I2S3_OUT (6).
- `0x10000000` is **PCM_IN**, not local playback. Output uses `flags=0`,
  `ctx+0x58`, and mask `0x5a`; `ctx+0x5c` / mask `0xc4` belong to input.
- Changing the route inside format lookup is too late: the caller has cached its old value.
  GDB observed rate=0 at PCM configuration in that experiment. Discovery must succeed first.

## Capture implementation

`pcm_params_get/min/max` emulate capabilities. `pcm_open` records channels, sample bytes,
and rate as three little-endian u32 values in `/audio.fmt`.
`pcm_write` takes a **byte count**, writes signed interleaved PCM to `/audio.pcm`, handles
short writes/EINTR, and returns failure on write errors.

`pcm_frames_to_bytes` and `pcm_bytes_to_frames` must also be intercepted: the real library
would dereference the fake handle. Buffer size is period size × period count.
The firmware's format enum differs from the initial assumption: playback uses **0 for
16-bit, 5 for packed 24-bit, 7 for 32-bit**.

Writes sleep for their audio duration, approximating a blocking DAC. Without pacing,
firmware-generated silence can grow the capture rapidly. Input is not implemented.
`asndshim.c` remains the separate USB/BT interposer; those routes and native
DSD/DoP output are unvalidated. DSD source metadata/selection is covered separately
in [FORMATS.md](../../docs/protocol/formats.md).

The shim uses `-nostdlib`, raw MIPS syscalls and the nan2008 ELF flag. Its only unresolved
dependency is `fopen64`, supplied by firmware libc. Do not link against the newer toolchain
glibc. Setup also creates `/dev/cs43131*` stubs. The absent mixer can log
`mixer_open failed`; this does not prevent capture.

## Verification and tools

On V2.40, stock audio code selected I2S3_OUT and opened 44,100 Hz stereo 32-bit PCM.
The two-second `01 - Tone A.wav` produced about 2.15 seconds including service silence.
A 1,000-frame region matched the source **byte for byte** after shifting its signed 16-bit
samples into 32-bit samples. Peak amplitude was about 0.300018.

Browser Enable sound / Replay capture / Mute sound were exercised without console errors.
Capture integrity tests cover signed stereo, frame boundaries, growing captures, stale
generations, and WAV's unsigned 8-bit convention:

```sh
python3 -m ci.unit
```

`emulator/runtime/audio.py` exports a bounded WAV snapshot. `/audio.json` reports generation, format,
and available bytes; `/audio.pcm?generation=…&offset=…` returns bounded, frame-aligned chunks
and rejects stale generations. `viewer/static/audio.js` converts PCM to float samples and schedules
them in Web Audio. Timing depends on decoder cost and host load; the earlier blanket claim
that qemu cannot play FLAC in real time was not established.

`tinyshim` paces `pcm_write` like a DAC: it keeps the time at which everything written so
far will have played and returns once at most the configured buffer (period size × period
count) is left to play. V2.57 playing a 48 kHz file opens 1920-frame periods and a
3840-frame buffer, i.e. two periods (80 ms). An earlier version slept for the length of
each write after the writer's own work, so output ran slower than real time by the
per-period work. In `emulator/tests/test_output_stream.py` (40 writes of 1024 frames at
44.1 kHz, 928 ms of audio, 2 ms of work before each) the last write returned after
1009-1011 ms with that version and after 837-839 ms with this one, 92 ms (the 4096-frame
buffer) before the audio finished, in Docker under qemu-user. On a slower host (an Android
phone running this firmware under qemu-user, outside this repository) the earlier version
played 29.2 s of audio per 30 s (0.973×); the browser loses 0.027 s of lag per second at
that rate, so a 0.15 s lag would be used up after about 6 s. A draft of the current pacing
that returned one period later measured 29.96 s per 30.05 s on that phone, and with the
0.3 s look-back above one 70 s browser run there recorded no gaps; the phone was not
measured again with the current pacing. When the host cannot decode in real time, every
write starts the clock again and `pcm_write` returns without sleeping.

Future firmware analysis: [RE.md](../../research/docs/methods.md), [Ghidra tooling](../../research/ghidra/README.md).

## Format coverage (validated) and remaining caveats

**PCM, multiple formats — ✅ validated end-to-end** (play → firmware decode/resample → tinyalsa →
capture → WAV, tone faithful):

| source | captured `/audio.fmt` | tone |
|---|---|---|
| 16-bit / 44.1 kHz (`Tone A.wav`, 440 Hz) | 2ch · 32-bit · 44100 | 441 Hz ✓ (byte-exact after 16→32 shift) |
| 24-bit / 96 kHz (1 kHz) | 2ch · 32-bit · **96000** | ~1000 Hz ✓ |

The DAC (I2S3) runs 32-bit at the source rate; the firmware up-converts sample depth and keeps the
rate. Regenerate hi-res test tones with sox (in the container, into `/sdcard/...`):

```sh
sox -n -b 24 -r 96000 -c 2 "03 - HiRes 1kHz 24b96k.wav" synth 2 sine 1000 gain -6
```

**Remaining caveats (not done; scoped honestly):**
- **DSD output** — a separate route (`set_pcm_config` branches on DSD rates
  `0x2b110/0x56220/0xac440` and `is_dsd`). Generated DSD64 `.dsf/.dff` files now
  exercise indexing, source metadata and selection/pause; see [FORMATS.md](../../docs/protocol/formats.md).
  This does not validate native DSD/DoP, bit-exact conversion or hardware audio.
- **USB-DAC (device as USB audio sink)** — out of scope under qemu-user: there is no USB host to
  send audio to the emulated gadget. `asndshim.c` covers the libasound (USB/BT) *playback* path if
  those routes are ever driven, but the USB-input direction can't be emulated here.
- **Recording / input (`PCM_IN`, `pcm_read`)** — not implemented (`pcm_read` returns `-1`,
  not synthetic silence); niche for this project.
