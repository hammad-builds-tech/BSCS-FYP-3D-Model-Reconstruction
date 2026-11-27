# Backend HTTP / WebSocket API

This file was previously empty (0 bytes). Source of truth is
`backend/api/main.py`; the behaviour below was exercised against a running
backend on 18 November 2026 (Quadro T2000, `device: cuda`).

Default bind: `http://0.0.0.0:8000` (`run_backend.sh`).

## `GET /`

Liveness. Returns the project name, `status` and whether MiDaS is loaded.

```json
{"project":"Smartphone-Based Real-Time 3D Indoor Mapping",
 "status":"running","midas":"loaded"}
```

## `GET /health`

The endpoint to check first — `run_system.sh` gates on it.

```json
{"status":"ok","frames_received":0,"midas":"loaded","device":"cuda",
 "depth_available":false,"depth_shape":null,"inference_active":false,
 "discovery_port":51315,"video_stream_locked":false}
```

| Field | Meaning |
|---|---|
| `device` | `cuda` or `cpu`. **If this says `cpu` the GPU setup is wrong** — see [`BACKEND_SETUP.md`](BACKEND_SETUP.md) |
| `midas` | `loaded` once the model is on the device |
| `frames_received` | Count since start |
| `depth_available` / `depth_shape` | Whether a depth map exists yet, and its size (e.g. `[480, 640]`) |
| `inference_active` | A frame is in the model right now |
| `discovery_port` | UDP port the discovery responder answers on |
| `video_stream_locked` | When true, new `/ws/video` connections are refused |
| `frame_metadata` | *(Phase 4B M2)* `true` if the most recent frame arrived with a metadata message |
| `intrinsics_source` | *(M2)* provenance of the intrinsics on the most recent frame, or `null` |
| `latest_seq` | *(M2)* phone-side sequence number of the most recent RGB frame, or `null` |
| `depth_seq` | *(M2)* sequence number of the frame the current depth map was computed from |
| `depth_raw_available` | *(M2)* `true` once `/latest-depth-raw` has data |

## `WS /ws/video`

The phone's uplink. **One endpoint, two compatible client behaviours.** There
is no `/ws/video/v2`: Phase 4B M2 extended this endpoint in place, and the
server distinguishes the two by WebSocket message *type*, not by URL.

### Legacy contract (every client before Phase 4B M2)

Send each frame as **one binary WebSocket message containing raw JPEG bytes**
-- no header, no length prefix, no envelope. The server replies with one JSON
text message per frame. This contract is unchanged and still works; it is
exercised by `scripts/test_backend_pipeline.py` and by the M2 regression.

### M2 extension: one metadata message before each JPEG

A client *may* precede each binary JPEG with **one JSON text message**
describing it. Each frame is therefore two WebSocket messages, in this order:

| # | WebSocket frame type | Payload |
|---|---|---|
| 1 | **text** | UTF-8 JSON object (schema below) |
| 2 | **binary** | raw JPEG bytes -- identical to the legacy format |

There is no binary framing of the metadata, and the JPEG is **not** wrapped:
the binary message is byte-for-byte what a legacy client sends.

**Pairing is positional.** WebSocket preserves message order on a connection,
and the Android app writes both messages from its single analyzer thread,
text first. The server holds the metadata and binds it to the **next binary
message that decodes as a JPEG**.

### Metadata schema (as emitted by the Android app)

The server stores the object **as received** and performs no schema
validation; the fields below are what `MainActivity.frameMetadata()` sends.

| Field | Type | Meaning |
|---|---|---|
| `seq` | int | Monotonic per-frame counter, starting at 1. Scoped to one `MainActivity` instance: it **restarts at 1 whenever the activity is recreated** (the manifest declares no `configChanges`, so any configuration change recreates it). It is not a globally unique frame ID -- `(seq, ts_ns)` together is. |
| `ts_ns` | int | `ImageProxy.imageInfo.timestamp` -- capture time in **nanoseconds** (timebase: see below) |
| `w`, `h` | int | Width and height of the **delivered JPEG**, i.e. after rotation |
| `raw_w`, `raw_h` | int | Width and height of the ImageAnalysis buffer **before** rotation |
| `rotation_deg` | int | Rotation applied to produce the JPEG: 0, 90, 180 or 270 |
| `fx`, `fy` | float | Focal lengths in pixels of the **delivered** image |
| `cx`, `cy` | float | Principal point in pixels of the **delivered** image |
| `distortion` | float[] | Present only if the device exposes `LENS_DISTORTION`; see below |
| `intrinsics_source` | string | `LENS_INTRINSIC_CALIBRATION`, `FOCAL_LENGTH+SENSOR_SIZE` or `unavailable` |

When `intrinsics_source` is `unavailable`, **`fx`, `fy`, `cx`, `cy` and
`distortion` are omitted** -- the app sends no matrix rather than an invented
one.

**Image coordinate convention.** The intrinsics follow the standard pinhole
convention for the delivered JPEG: `u` to the right, `v` downward, origin at
the top-left pixel. No extrinsics, camera pose or 3D frame are transmitted.

**Timestamp timebase.** `ts_ns` is a device-local monotonic counter, **not**
wall-clock time and **not** comparable with the laptop's clock. The app does
not read `SENSOR_INFO_TIMESTAMP_SOURCE`, so whether it is `REALTIME`
(`elapsedRealtimeNanos`) or `UNKNOWN` is not transmitted. It is suitable for
ordering frames and measuring intervals within one session only.

**Distortion order.** `distortion` is passed through exactly as Camera2's
`LENS_DISTORTION` reports it: `[k1, k2, k3, p1, p2]` -- three radial then two
tangential. **This is not OpenCV's order** (`[k1, k2, p1, p2, k3]`); reorder
before passing it to `cv2.undistort`. The coefficients are applied by nothing
in this project yet.

### Server behaviour

| Received | Behaviour |
|---|---|
| Text message, valid JSON **object** | Held as pending metadata; no reply |
| Text message, valid JSON but **not an object** | Logged and ignored; connection kept |
| Text message, **not JSON** | Logged and ignored; connection kept |
| A second text message before any JPEG | **Replaces** the first |
| Binary message that decodes as a JPEG | Accepted; pending metadata bound to it and cleared; ack sent |
| Binary message that does **not** decode | `{"status":"error","message":"Invalid JPEG frame"}`; the pending metadata is **discarded**, so it cannot label a later frame |
| Connection closes with metadata still pending | The metadata is discarded with the connection; it is never carried into another connection |

Every accepted frame is acknowledged with:

```json
{"status":"ok","seq":5004,"frame":12,"width":480,"height":640,
 "depth_available":true,"inference_active":false}
```

`seq` echoes the metadata bound to that frame, or is `null` for a frame sent
without metadata. `frame` is the server's own arrival counter.

Measured: acknowledgement in ~6 ms, and 60/60 frames accepted with no loss
at ~11 fps.

**The acknowledgement does not mean depth is ready.** Inference runs on a
separate thread and is **latest-frame-wins**: `pending_frame` is overwritten,
so stale frames are dropped rather than queued. Depth therefore appears at
the model's own rate — about 5.3 fps on the Quadro T2000, 22–25 fps on the
RTX 4050 — no matter how fast frames are pushed. Poll `/health` or
`/latest-depth-image` for depth; do not infer it from the ack.

Every 10th RGB frame is persisted under `backend/uploads/`.

If the stream is locked the server accepts then immediately closes with code
`1008` and reason `stream locked: capture window closed`.

### Metadata association defects found and fixed in Phase 4B M2

Three defects were found during M2 closeout and fixed before M2 was
committed. Each fix was verified with the same test that reproduced it.

1. **An undecodable JPEG left its metadata pending**, so it labelled the next
   valid frame. Fixed: the invalid-JPEG path now discards the metadata.
   Before: metadata `seq 7001` + garbage bytes, then a metadata-free JPEG, was
   acked as `seq 7001`. After: acked as `seq null`.
2. **Pending metadata survived across connections** -- it was a module-level
   variable. Fixed: it is now a local of each connection. Before: client A's
   dangling `seq 8001` labelled client B's first frame. After: `seq null`.
3. **The depth payload and its metadata were not published atomically** --
   the `.npy` was written after the lock was released. Fixed: it is now
   serialised outside the lock and assigned together with `depth_meta` inside
   it. This one was found by code review and was never reproduced (0
   mismatches in 739 polls before the fix, 0 in 616 after), so the fix is
   verified structurally rather than by a failing-then-passing test.

## `GET /latest-frame`

Most recent RGB frame received.

## `GET /latest-depth`

**Summary statistics only** -- not the depth data. Returns:

```json
{"status":"ok","shape":[640,480],"min":365.84,"max":1633.49,
 "file":"<repo>/backend/depth/output/latest_depth.png"}
```

`min`/`max` are taken from the raw float array, so they describe the same
values `/latest-depth-raw` serves. *(Corrected in Phase 4B M2: this section
previously described the endpoint as returning the depth map itself, which it
never did.)* Values are **MiDaS inverse relative depth**,
not metres: larger means closer, and there is no absolute scale. Anything
needing real distances must calibrate first — this is why
`depth_to_scan`'s `relative` mode is uncalibrated (see
[`ARCHITECTURE.md`](ARCHITECTURE.md) section 3).

## `GET /latest-depth-raw`  *(Phase 4B M2)*

**The raw float32 depth of the most recent inference**, unmodified model
output. This is the endpoint for any geometric use.

| Aspect | Value |
|---|---|
| Body | NumPy `.npy` format (`np.save`, `allow_pickle=False`) |
| Content-Type | `application/octet-stream` |
| dtype | **float32** |
| Shape | `(height, width)` of the delivered RGB frame -- `(640, 480)` for an upright portrait frame |
| Order | C / row-major: `arr[v, u]` is the pixel in row `v`, column `u` |
| Units | **MiDaS inverse relative depth. NOT metres.** |
| 404 | `{"message":"No depth generated yet"}` before the first inference |

Response headers:

| Header | Present | Meaning |
|---|---|---|
| `X-Depth-Units` | always | `midas-inverse-relative-unscaled` |
| `X-Frame-Seq` | only if the source frame carried metadata | `seq` of the RGB frame this depth was computed from |
| `X-Frame-Timestamp-Ns` | only if the source frame carried metadata | that frame's capture `ts_ns` |

Load it with `np.load(io.BytesIO(body), allow_pickle=False)`; the `.npy`
header carries dtype and shape, so no out-of-band agreement is needed.

**The values are relative, not metric.** Larger means nearer; the scale is
arbitrary and **can differ from frame to frame**, because MiDaS predicts
relative structure only. Nothing in the backend converts these values to
metres. Back-projecting them through the transmitted intrinsics gives a
correctly *shaped* point cloud at an arbitrary, per-frame scale.

**No backend inference timestamp is recorded.** The only timestamp available
is the phone's capture `ts_ns`. Capture-to-depth latency cannot be measured
from these outputs; only the frame lag (`seq_lag`, below) can.

## `GET /latest-frame-meta`  *(Phase 4B M2)*

```json
{"status":"ok",
 "latest_frame": { ...metadata of the most recent RGB frame... },
 "depth_frame":  { ...metadata of the frame the current depth came from... },
 "seq_lag": 2}
```

`depth_frame` is the one that matters for reconstruction. Because inference
is latest-frame-wins and slower than the uplink, depth routinely trails the
newest RGB frame; `seq_lag` reports by how many frames. Either object is
`null` when the corresponding frame arrived without metadata.

### Verifying an RGB/depth pairing

Two separate requests against a live stream are racy -- depth can advance
between them. A **single** `/latest-depth-raw` response is consistent: the
worker publishes the array, its `.npy` payload and its metadata in one locked
assignment, and the endpoint reads them under the same lock. (Before the M2
fix the payload was published a few milliseconds after the metadata; see the
fixed defects above.)

To compare across endpoints, verify against frozen state: stop sending, wait for
`/health` to report `inference_active: false`, then compare
`X-Frame-Seq == depth_frame.seq` and
`X-Frame-Timestamp-Ns == depth_frame.ts_ns`. Both matched exactly in the M2
regression and on the physical Pixel 7 Pro. *(The first physical comparison
was done live and reported a false mismatch -- seq 493 vs 496 -- for exactly
this reason.)*

## `GET /latest-depth-image`

**Visualisation and compatibility only -- unchanged by Phase 4B M2.** Depth as
an 8-bit PNG, min-max normalised **per frame** (`cv2.NORM_MINMAX` to 0-255).
This is what `smartphone_depth_bridge/depth_bridge_node.py` polls before
republishing it as a ROS `sensor_msgs/Image` on `/smartphone/depth`.

Per-frame normalisation means the same physical distance maps to different
pixel values in different frames, and the result is quantised to 256 levels.
Use it to look at depth; do not use it for geometry. The M2 regression
confirmed it is byte-for-byte `NORM_MINMAX` of the float array from the same
frame (max absolute difference 0).

## UDP discovery

A responder thread (`discovery_responder`, `backend/api/main.py`) answers
discovery probes so a phone can find the backend without a hard-coded IP;
the port is reported by `/health`.

The **backend side already exists**. The Android client side does not — the
app still hard-codes `ws://192.168.2.107:8000/ws/video` and implements no
discovery (Phase 1 limitation 13.3).

## Quick checks

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
venv/bin/python scripts/test_backend_pipeline.py   # needs frames in video_frames/
```
