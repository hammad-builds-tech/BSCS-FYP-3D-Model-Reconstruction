#!/usr/bin/env python3
"""Focused checks for Phase 4B M2 frame-metadata association.

NOT a pytest suite. pytest/httpx are not in the backend venv, so this is a
standalone script that imports backend/api/main.py IN-PROCESS (loading MiDaS
exactly as the server does) and drives the real `video_websocket` coroutine
with a scripted fake WebSocket. Exit status 0 = all checks passed.

    venv/bin/python scripts/check_frame_metadata.py
    venv/bin/python scripts/check_frame_metadata.py --main /path/to/old/main.py

The second form loads a different main.py (e.g. an earlier commit's) so the
atomicity check can be shown to FAIL on the code that had the race. A check
that cannot fail proves nothing.

What is checked
  1. Frame/metadata atomic association. The inference worker reads
     `pending_frame` and `latest_meta` together under `processing_lock`. A
     probe wrapped around that lock snapshots both at every acquisition made
     by the socket handler -- i.e. at exactly the instants a worker could win
     the lock -- and asserts the pending pixels and the metadata belong to the
     same frame. The worker is held inside predict() so frames pile up as
     pending, which makes the interleaving deterministic, not timing-luck.
  2. An undecodable JPEG does not pass its metadata to the next frame.
  3. A new connection does not inherit another connection's pending metadata.
  4. Legacy binary-only clients still work (acks, seq null, no metadata).
  5. Float32 depth is served as .npy and its X-Frame-Seq / timestamp headers
     name the frame it was computed from; the 8-bit preview still works.

Runtime output (uploads, persisted depth PNG) is redirected to a temporary
directory so the server's real persisted preview is not overwritten.
"""
import argparse
import asyncio
import importlib.util
import io
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def jpeg(grey, h=120, w=160):
    """Solid-grey JPEG; the grey level is a tag that survives compression."""
    img = np.full((h, w, 3), grey, np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def tag_of(frame):
    return int(round(float(frame.mean()) / 20.0))


class FakeWebSocket:
    """Just enough of starlette's WebSocket for video_websocket()."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    async def accept(self):
        pass

    async def close(self, code=1000, reason=None):
        self.sent.append({"closed": code})

    async def receive(self):
        await asyncio.sleep(0)  # yield, as a real socket would
        if not self._messages:
            return {"type": "websocket.disconnect", "code": 1000}
        kind, payload = self._messages.pop(0)
        return {"type": "websocket.receive", kind: payload}

    async def send_json(self, obj):
        self.sent.append(obj)


def run_connection(m, messages):
    ws = FakeWebSocket(messages)
    asyncio.run(m.video_websocket(ws))
    return ws.sent


def text(obj):
    import json
    return ("text", json.dumps(obj))


def binary(b):
    return ("bytes", b)


class ProbeLock:
    """Wraps the real lock. On each acquisition by the socket handler,
    records what a worker taking the lock at that instant would read."""

    def __init__(self, real, module):
        self.real = real
        self.m = module
        self.armed = False
        self.samples = []

    def __enter__(self):
        if self.armed and sys._getframe(1).f_code.co_name == "video_websocket":
            pf = self.m.pending_frame
            if pf is not None:
                lm = self.m.latest_meta
                self.samples.append((tag_of(pf), (lm or {}).get("seq")))
        self.real.acquire()
        return self

    def __exit__(self, *exc):
        self.real.release()
        return False


def load_main(path):
    if path is None:
        import backend.api.main as m
        return m
    spec = importlib.util.spec_from_file_location("backend.api.main", path)
    m = importlib.util.module_from_spec(spec)
    sys.modules["backend.api.main"] = m
    spec.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default=None, help="alternative main.py to load")
    args = ap.parse_args()

    # Do not collide with a running backend's discovery port.
    os.environ.setdefault("FYP_DISCOVERY_PORT", "0")

    m = load_main(args.main)
    tmp = Path(tempfile.mkdtemp(prefix="fyp_meta_check_"))
    m.UPLOAD_DIR = tmp / "uploads"
    m.DEPTH_DIR = tmp / "depth"
    m.UPLOAD_DIR.mkdir()
    m.DEPTH_DIR.mkdir()

    # Hold the worker inside predict() so frames stay pending.
    gate = threading.Event()
    real_predict = m.midas.predict

    def gated_predict(img):
        gate.wait()
        return real_predict(img)

    m.midas.predict = gated_predict
    probe = ProbeLock(m.processing_lock, m)
    m.processing_lock = probe

    # ---------------------------------------------------------------- 1
    print("=== 1. frame/metadata atomic association ===")
    # tag k -> the seq sent with it (None = legacy frame without metadata)
    expected = {}
    msgs = []
    for k in range(1, 10):
        if k == 6:
            expected[k] = None            # a legacy frame mid-stream
        else:
            expected[k] = 100 + k
            msgs.append(text({"seq": 100 + k, "ts_ns": k * 1000}))
        msgs.append(binary(jpeg(20 * k)))
    probe.armed = True
    acks = run_connection(m, msgs)
    probe.armed = False

    ack_seqs = [a.get("seq") for a in acks if a.get("status") == "ok"]
    check("every frame acked with its own seq",
          ack_seqs == [expected[k] for k in range(1, 10)], str(ack_seqs))
    bad = [(t, s) for t, s in probe.samples if expected.get(t, "?") != s]
    # Samples where pending pixels came from an EARLIER frame are the ones a
    # racing worker could take; require plenty, or the check is vacuous.
    stale = [t for t, _ in probe.samples]
    check("probe observed pending frames at socket lock acquisitions",
          len(probe.samples) >= 12, f"{len(probe.samples)} samples")
    check("pending pixels and metadata always belong to the same frame",
          not bad, f"mismatches (pixel tag, meta seq): {bad}" if bad else
          f"0 mismatches in {len(stale)} samples")

    # ---------------------------------------------------------------- 2
    print("=== 2. invalid JPEG does not leak metadata ===")
    acks = run_connection(m, [
        text({"seq": 7001, "ts_ns": 1}),
        binary(b"definitely not a jpeg"),
        binary(jpeg(40)),
    ])
    check("undecodable bytes answered with an error",
          acks[0].get("status") == "error", str(acks[0]))
    check("next frame is unlabelled, not seq 7001",
          acks[1].get("status") == "ok" and acks[1].get("seq") is None,
          str(acks[1].get("seq")))

    # ---------------------------------------------------------------- 3
    print("=== 3. new connection starts with no pending metadata ===")
    run_connection(m, [text({"seq": 8001, "ts_ns": 2})])   # dangling, then closes
    acks = run_connection(m, [binary(jpeg(60))])
    check("first frame of the next connection is unlabelled",
          acks[0].get("seq") is None, str(acks[0].get("seq")))
    check("latest_meta is not the other connection's", m.latest_meta is None,
          str(m.latest_meta))

    # ---------------------------------------------------------------- 4
    print("=== 4. legacy binary-only client ===")
    before = m.frame_count
    acks = run_connection(m, [binary(jpeg(80)), binary(jpeg(100)), binary(jpeg(120))])
    check("three binary-only frames all acked ok",
          [a.get("status") for a in acks] == ["ok"] * 3, str(acks))
    check("acks carry seq null", all(a.get("seq") is None for a in acks))
    check("arrival counter advanced by 3", m.frame_count == before + 3,
          f"{before} -> {m.frame_count}")
    check("ack shape fields present",
          all({"frame", "width", "height", "depth_available", "inference_active"}
              <= a.keys() for a in acks))

    # ---------------------------------------------------------------- 5
    print("=== 5. float32 depth paired with its source frame ===")
    gate.set()                      # release the worker
    run_connection(m, [text({"seq": 9001, "ts_ns": 9001000}), binary(jpeg(140))])
    deadline = time.time() + 120
    while time.time() < deadline:
        with m.processing_lock:
            if (m.depth_meta or {}).get("seq") == 9001 and m.latest_depth_npy is not None:
                break
        time.sleep(0.05)
    resp = m.get_latest_depth_raw()
    hdr = resp.headers
    check("X-Frame-Seq names the source frame", hdr.get("x-frame-seq") == "9001",
          str(hdr.get("x-frame-seq")))
    check("X-Frame-Timestamp-Ns matches that frame",
          hdr.get("x-frame-timestamp-ns") == "9001000", str(hdr.get("x-frame-timestamp-ns")))
    check("units header declares relative inverse depth",
          hdr.get("x-depth-units") == "midas-inverse-relative-unscaled")
    arr = np.load(io.BytesIO(resp.body), allow_pickle=False)
    check("payload is float32", arr.dtype == np.float32, str(arr.dtype))
    check("shape equals the source frame (h, w)", arr.shape == (120, 160), str(arr.shape))
    check("all values finite", bool(np.isfinite(arr).all()))
    with m.processing_lock:
        same = m.latest_depth is not None and np.array_equal(
            arr, m.latest_depth.astype(np.float32))
    check(".npy equals the in-memory depth array", same)
    h = m.health()
    check("/health latest_seq == depth_seq after settling",
          h["latest_seq"] == h["depth_seq"] == 9001,
          f"{h['latest_seq']} / {h['depth_seq']}")

    # The 8-bit preview is written just after the lock; give it a moment.
    png = None
    for _ in range(100):
        r = m.get_latest_depth_image()
        if getattr(r, "media_type", None) == "image/png":
            png = cv2.imdecode(np.frombuffer(r.body, np.uint8), cv2.IMREAD_UNCHANGED)
            if png is not None and png.shape == (120, 160):
                break
        time.sleep(0.05)
    check("8-bit preview still served as single-channel uint8 PNG",
          png is not None and png.dtype == np.uint8 and png.ndim == 2,
          None if png is None else f"{png.dtype} {png.shape}")

    passed = sum(ok for _, ok in results)
    print(f"\nRESULT: {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
