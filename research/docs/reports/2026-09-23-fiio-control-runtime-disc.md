# FiiO Control runtime data: DISC support — 2026-09-23

## Scope and inputs

Offline, read-only inspection of the owner-supplied Android application-data
folder `com.fiio.control`. This is runtime data, not another APK. The log identifies
FiiO Control 4.6.0 and reports an Android 13 / FiiO M21 user agent; that is the app
host description, not a change to the identity of the remote DISC.

SQLite was opened with `mode=ro`. No cloud requests, login, physical connection,
settings changes or command replay occurred. Private logs, profile databases,
artwork, addresses and catalog data are not copied into this report or committed.

| Relative input | Bytes | SHA-256 |
| --- | ---: | --- |
| `databases/sc_config.db` | 782336 | `fa9a5e88e7f4a00391516bb3b6261fbcf4e6e7715b28fcf5e8795a540dcaaa32` |
| `databases/sc_config_default.db` | 770048 | `1791f8a4210282d51ee7e5956f17bda3459b084fca9eaf8ad695aa5a0953fef9` |
| `app_flutter/logs/log_20260916_184607__running.log` | 901637 | `019772f226d7f14a567f8290eab141c373b15716a2878728fcd4864fda16f18a` |
| `app_flutter/l10n/sync_cache.json` | 941104 | `73d065ed97a5396d7e3b1424182bf62801678c7c41326b2c5ce04210b1194db3` |

The default database hash matches the previously inspected APK asset. The running
log has 4455 lines and spans multiple startup/activity periods despite its single
filename/session-start marker. Later time-only entries must not be assigned a
calendar date solely from that filename.

## Downloaded profiles are real, but DISC is on another path

| Table | Runtime DB | Bundled fallback |
| --- | ---: | ---: |
| `sc_product_info` | 67 | 70 |
| `sc_func_info` | 78 | 78 |
| `sc_update_time` | 2 | 0 |
| `home_save_device` | 1 | 0 |

The runtime table has neither a product nor a function row for type **306** or
DISC. The fallback tables also lack DISC. The one saved device is `SNOWSKY DISC`,
`device_type=306`, `transport_type=4`; this home-screen record is not a feature
profile. Do not confuse that transport enum with product-table `connect_mode`.

The runtime update timestamps are `2026-09-16T11:21:41Z` and
`2026-09-22T08:15:59Z`. These are stored profile-version timestamps, not proof of
when the owner downloaded the data. Product identity sets differ from fallback,
and all 78 function JSON records differ structurally after parsing; this is not
merely a filename or whitespace difference. It does not establish 78 new usable
capabilities, and none is a DISC descriptor.

The log supplies direct runtime evidence for the previously inferred workflow:

- Lines 51 / 487 and 3605 / 4045 request the production product/function endpoints.
  Adjacent records contain encrypted replies, decrypted data and database writes.
- Lines 774–780 discover DISC by UDP, resolve its name to 306, fail the primary
  product lookup and also fail the fallback lookup.
- Lines 782–801 still connect, send the Link handshake, identify type 306 and
  navigate to `device_linker_page`.
- Lines 817–828 open `linked_device_local_playback_page_v2` and
  `style_album_page_v2`.
- Lines 4298–4300 repeat the failed primary/fallback product lookup after the
  later refresh.

This confirms that, in this application build and captured state, DISC playback
works through the dedicated Link implementation despite the absent universal
profile. It is not waiting for a missing cloud function table. This extends the
[APK analysis](fiio-control-app.md#android-460-input-2026-09-15) without claiming
that future app versions or server datasets must use the same arrangement.

## Data actually received from DISC

The log contains three full song records (lines 832, 854 and 876), alongside
state-only updates. These include duration/path, sample rate, encoding depth,
reported rate, artist/album/genre, track number, channels and DSD/CUE/SACD/M3U
flags. The received examples report 44100 Hz, 16-bit, two-channel audio.

For the `.flac` paths in these observations, `song_bit_rate` is 1411. That matches
the rounded PCM data-rate scale for 44100 × 16 × 2, so the field must not simply
be labelled measured FLAC compressed bitrate. Exact semantics across formats
remain to be checked. Genre and metadata values are device observations, not
external enrichment.

Lines 837–842, 859–866 and 878–885 show the current-cover HTTP route on 12103 and
nonempty response bodies of 102113 or 145328 bytes. Requests/log messages appear
in duplicate, so six logged request lines are not evidence of six independent
transfers. This adds app-log evidence to the existing cover protocol evidence;
no image contents were exported in this investigation.

No `/currentLyric`, port 13488, lyric-text request or arbitrary audio-download
request is present in the supplied log. This is an observation of this activity
only: the log is not a complete packet capture, and a feature not exercised may
leave no trace. It does not independently prove the absence of a service.
The [firmware metadata audit](2026-09-23-library-metadata.md) remains the evidence
for the inspected stock HTTP boundary and local lyric pipeline.

## Other files do not supply a DISC capability profile

The localization cache has sequence 101 and 1496 entries. Its `disc_prefix` key
is a translated generic disc label, not a device-profile record. The image-cache
database has 63 entries, all using the vendor asset host; it is not a cache of
LAN `/image/cover/` responses. The native equalizer database and shared preferences
do not contain a universal DISC function table. Their unrelated values were not
used to derive supported DISC commands.

## Effect on the Web work proposal

No plan was changed by this inspection, and no new remote capability is enabled.
The supplied data strengthens the proposal to expose current-track audio fields
through the public Controller model and Library enrichment first. It provides no
new basis for bulk remote tag/artwork extraction or remote DISC lyric access.
Cloud profile import is therefore not a prerequisite for the current DISC Web
metadata work. If another static pass is desired, inspect the dedicated Link
pages and model gates, not the universal Bluetooth/USB function-table loader.

Only this report and its link from the metadata audit were changed. Markdown
links and diff whitespace were checked; no firmware/device test was run.
