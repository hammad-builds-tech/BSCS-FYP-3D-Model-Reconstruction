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

## `WS /ws/video`

The phone's uplink. Send each frame as a **binary** JPEG message; the server
replies with one JSON message per frame.

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

## `GET /latest-frame`

Most recent RGB frame received.

## `GET /latest-depth`

Most recent depth map as data. Values are **MiDaS inverse relative depth**,
not metres: larger means closer, and there is no absolute scale. Anything
needing real distances must calibrate first — this is why
`depth_to_scan`'s `relative` mode is uncalibrated (see
[`ARCHITECTURE.md`](ARCHITECTURE.md) section 3).

## `GET /latest-depth-image`

Depth as a normalised PNG. This is what
`smartphone_depth_bridge/depth_bridge_node.py` polls before republishing it
as a ROS `sensor_msgs/Image` on `/smartphone/depth`.

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
