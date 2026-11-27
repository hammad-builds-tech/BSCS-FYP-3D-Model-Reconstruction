from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import cv2
import numpy as np
from pathlib import Path
import asyncio
import io
import json
import os
import socket
import threading
from typing import Optional

from backend.core.paths import FYP_ROOT
from backend.depth.midas_processor import MiDaSProcessor


app = FastAPI(
    title="FYP 3D Indoor Mapping Backend",
    version="1.0.0"
)

UPLOAD_DIR = FYP_ROOT / "backend" / "uploads"
DEPTH_DIR = FYP_ROOT / "backend" / "depth" / "output"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEPTH_DIR.mkdir(parents=True, exist_ok=True)

API_PORT = int(os.environ.get("FYP_BACKEND_PORT", "8000"))
DISCOVERY_PORT = int(os.environ.get("FYP_DISCOVERY_PORT", "51315"))

latest_frame: Optional[np.ndarray] = None
latest_depth: Optional[np.ndarray] = None
latest_depth_png: Optional[bytes] = None  # encoded PNG served by /latest-depth-image
frame_count = 0
pending_frame: Optional[np.ndarray] = None
processing_lock = threading.Lock()
inference_active = False

# --- Phase 4B M2: per-frame metadata ----------------------------------
# The phone sends ONE JSON text message immediately before each binary JPEG.
# WebSocket preserves message order per connection, so the text describes the
# very next binary frame. The JPEG itself is still raw bytes with no envelope,
# so a client that sends binary only keeps working exactly as before.
latest_meta: Optional[dict] = None        # metadata of the most recent frame
depth_meta: Optional[dict] = None         # metadata of the frame `latest_depth` came from
# Raw float32 depth of the most recent inference, as model output -- NOT
# normalised. `latest_depth` is the same array; this name is kept separate so
# the float endpoint cannot be confused with the 8-bit PNG path.
latest_depth_npy: Optional[bytes] = None

# Hard offline switch: when True, ALL new video websocket connections are
# rejected with policy code 1008. Used to enforce the 30-second capture
# window so all post-processing runs purely OFFLINE on saved data.
video_stream_locked = os.environ.get("FYP_VIDEO_STREAM_LOCK", "0") == "1"


# =========================
# LAN AUTO-DISCOVERY
#
# The Android app can find this backend without any hard-coded IP.
# It broadcasts "FYP_DISCOVER_REQ" on the LAN; we answer with our
# address so the phone can connect on any Wi-Fi / hotspot network.
# =========================

def _lan_ip() -> str:
    """Best-effort local LAN IP (no packets are actually sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def discovery_responder():
    """Answer UDP discovery probes so the phone app needs no manual IP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", DISCOVERY_PORT))
    except OSError as exc:
        print(f"UDP discovery disabled (port {DISCOVERY_PORT} busy): {exc}")
        return

    while True:
        try:
            data, addr = sock.recvfrom(1024)
        except OSError:
            continue
        if data.strip() == b"FYP_DISCOVER_REQ":
            reply = f"FYP_BACKEND|{_lan_ip()}|{API_PORT}"
            try:
                sock.sendto(reply.encode("utf-8"), addr)
                print(f"Discovery probe answered for {addr[0]}")
            except OSError:
                pass


threading.Thread(target=discovery_responder, daemon=True).start()


# =========================
# LOAD MiDaS
# =========================

print("Initializing MiDaS...")

midas = MiDaSProcessor()

print("MiDaS ready.")


# =========================
# Background Inference Worker
# =========================

def inference_worker():
    """Background thread that processes frames from the buffer."""
    global latest_depth, pending_frame, inference_active, depth_meta, latest_depth_npy

    while True:
        frame_to_process = None
        meta_for_frame = None

        with processing_lock:
            if pending_frame is not None:
                frame_to_process = pending_frame
                # Capture the metadata of THIS frame together with the pixels,
                # under the same lock. Reading it afterwards would race with
                # the socket thread and could attribute a depth map to a
                # different capture -- exactly what the seq number exists to
                # make checkable.
                meta_for_frame = latest_meta
                pending_frame = None
                inference_active = True

        if frame_to_process is not None:
            # Run MiDaS inference (blocks this background thread only)
            depth = midas.predict(frame_to_process)

            # Serialise OUTSIDE the lock (np.save of ~1.2 MB takes a few ms),
            # then publish the array, its .npy bytes and its metadata in ONE
            # locked assignment. Previously the .npy was written after the
            # lock was released, so for that window /latest-depth-raw could
            # return the new frame's seq with the previous frame's depth.
            depth_npy = _encode_depth_float(depth)

            # Save latest depth
            with processing_lock:
                latest_depth = depth
                depth_meta = meta_for_frame
                latest_depth_npy = depth_npy
                inference_active = False

            # Persist normalized PNG for /latest-depth-image consumers
            # (Android viewer + the ROS depth bridge).
            _write_depth_png(depth)
        else:
            # No frame to process, sleep briefly
            threading.Event().wait(0.05)


def _encode_depth_float(depth: np.ndarray) -> bytes:
    """Keep the RAW float32 depth so it can be served unmodified.

    The existing PNG path applies cv2.NORM_MINMAX PER FRAME, which rescales
    every frame independently: the same physical distance becomes a different
    number as the scene's min/max move, and the result is quantised to 256
    levels. That is fine for a human preview and useless for geometry, so the
    float array is preserved here instead of being discarded.

    This is additive. /latest-depth-image and its 8-bit PNG are untouched.
    """
    buf = io.BytesIO()
    # .npy keeps dtype and shape, so the consumer needs no out-of-band
    # agreement about either.
    np.save(buf, depth.astype(np.float32), allow_pickle=False)
    return buf.getvalue()


def _write_depth_png(depth: np.ndarray) -> None:
    """Persist the latest depth as a normalized PNG for /latest-depth-image.

    The file is encoded in memory and moved into place atomically (os.replace)
    so a concurrent FileResponse reader can never observe an empty or
    half-written PNG while the worker rewrites it.
    """
    depth_normalized = cv2.normalize(
        depth,
        None,
        0,
        255,
        cv2.NORM_MINMAX,
    ).astype(np.uint8)
    ok, buf = cv2.imencode(".png", depth_normalized)
    if not ok:
        return
    data = buf.tobytes()

    # Keep the encoded PNG in memory: /latest-depth-image serves these exact
    # bytes, so consumers never see a half-written file. The on-disk copy is
    # only a convenience for human inspection / the Android viewer.
    global latest_depth_png
    latest_depth_png = data
    final_path = DEPTH_DIR / "latest_depth.png"
    tmp_path = DEPTH_DIR / ".latest_depth.png.tmp"
    tmp_path.write_bytes(data)
    os.replace(str(tmp_path), str(final_path))


# Start background inference thread
inference_thread = threading.Thread(target=inference_worker, daemon=True)
inference_thread.start()


# =========================
# ROOT
# =========================

@app.get("/")
def root():
    return {
        "project": "Smartphone-Based Real-Time 3D Indoor Mapping",
        "status": "running",
        "midas": "loaded"
    }


# =========================
# HEALTH
# =========================

@app.get("/health")
def health():
    with processing_lock:
        active = inference_active
        depth = latest_depth
        # Snapshot the M2 fields in the same critical section so latest_seq
        # and depth_seq describe one consistent instant.
        meta = latest_meta
        d_meta = depth_meta
        raw_available = latest_depth_npy is not None

    return {
        "status": "ok",
        "frames_received": frame_count,
        "midas": "loaded",
        "device": "cuda" if midas.device.type == "cuda" else "cpu",
        "depth_available": depth is not None,
        "depth_shape": list(depth.shape) if depth is not None else None,
        "inference_active": active,
        "discovery_port": DISCOVERY_PORT,
        "video_stream_locked": video_stream_locked,
        # Phase 4B M2
        "frame_metadata": meta is not None,
        "intrinsics_source": (meta or {}).get("intrinsics_source"),
        "latest_seq": (meta or {}).get("seq"),
        "depth_seq": (d_meta or {}).get("seq"),
        "depth_raw_available": raw_available,
    }


# =========================
# LIVE VIDEO
# =========================

@app.websocket("/ws/video")
async def video_websocket(websocket: WebSocket):

    global latest_frame
    global frame_count
    global pending_frame
    global latest_meta

    if video_stream_locked:
        await websocket.accept()
        await websocket.close(code=1008, reason="stream locked: capture window closed")
        print("PHONE REJECTED (stream locked - offline enforcement)")
        return

    await websocket.accept()

    print("PHONE CONNECTED")

    # Metadata awaiting its JPEG. Deliberately a LOCAL of this connection:
    # it was module-global in the first M2 cut, so metadata left dangling by
    # one client (sent, then disconnected before its JPEG) labelled the first
    # frame of the NEXT, unrelated connection. Scoping it here makes that
    # impossible by construction.
    pending_meta: Optional[dict] = None

    try:

        while True:

            message = await websocket.receive()

            # Phase 4B M2: the phone may precede each binary JPEG with ONE
            # JSON text message carrying seq, capture timestamp and the real
            # camera intrinsics for that exact frame.
            #
            # Backward compatible BY DESIGN: a client that sends only binary
            # frames (every version before M2, and scripts/test_backend_
            # pipeline.py) still works -- the metadata simply stays None.
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))

            text = message.get("text")
            if text is not None:
                try:
                    meta = json.loads(text)
                    if isinstance(meta, dict):
                        pending_meta = meta
                    else:
                        print(f"frame metadata ignored (not an object): {text[:120]}")
                except (ValueError, TypeError) as exc:
                    # Never drop the connection over bad metadata: the frames
                    # themselves are still useful, just unlabelled.
                    print(f"frame metadata unparseable, ignoring: {exc}")
                continue

            data = message.get("bytes")
            if data is None:
                continue

            # JPEG bytes → OpenCV image
            image_array = np.frombuffer(
                data,
                dtype=np.uint8
            )

            frame = cv2.imdecode(
                image_array,
                cv2.IMREAD_COLOR
            )

            if frame is None:

                # The metadata described THIS (bad) frame. Discard it now;
                # otherwise it stays pending and labels the next valid frame,
                # which is a different capture.
                pending_meta = None

                await websocket.send_json({
                    "status": "error",
                    "message": "Invalid JPEG frame"
                })

                continue

            frame_count += 1

            # Bind the metadata that arrived immediately before these bytes.
            # Consumed exactly once, so a frame can never inherit a previous
            # frame's label if the phone stops sending metadata mid-stream.
            frame_meta = pending_meta
            pending_meta = None

            latest_frame = frame

            # Submit frame for background processing (non-blocking)
            # Only keep the latest frame - drop old ones
            #
            # `latest_meta` MUST be published in the same critical section as
            # `pending_frame`: the inference worker reads the two together
            # under this lock. When it was assigned before the lock, a worker
            # acquiring the lock in between took the PREVIOUS, still-pending
            # frame's pixels paired with THIS frame's metadata, so the depth
            # map was labelled with the wrong seq/ts_ns (off by one).
            with processing_lock:
                pending_frame = frame.copy()
                latest_meta = frame_meta

            # Save every 10th RGB frame
            if frame_count % 10 == 0:

                rgb_file = (
                    UPLOAD_DIR /
                    f"frame_{frame_count:06d}.jpg"
                )

                cv2.imwrite(
                    str(rgb_file),
                    frame
                )

            # Get current depth status
            with processing_lock:
                depth_available = latest_depth is not None
                active = inference_active

            print(
                f"Frame {frame_count} | "
                f"RGB {frame.shape[1]}x{frame.shape[0]} | "
                f"Depth {'available' if depth_available else 'processing...'} | "
                f"Inference {'active' if active else 'idle'}"
            )

            await websocket.send_json({

                "status": "ok",

                "seq": (frame_meta or {}).get("seq"),

                "frame": frame_count,

                "width": frame.shape[1],

                "height": frame.shape[0],

                "depth_available": depth_available,

                "inference_active": active

            })

    except WebSocketDisconnect:

        print("PHONE DISCONNECTED")


# =========================
# RAW FLOAT DEPTH + FRAME METADATA  (Phase 4B M2)
# =========================

@app.get("/latest-depth-raw")
def get_latest_depth_raw():
    """Raw float32 MiDaS output as a .npy payload, with its source frame.

    This is the endpoint 3D reconstruction should use. /latest-depth-image
    remains the 8-bit preview and is unchanged, but it is per-frame
    NORM_MINMAX normalised, so its values are not comparable between frames.

    The `X-Frame-Seq` header names the phone-side sequence number of the RGB
    frame this depth was computed from, so a consumer can prove the pairing
    instead of assuming it. It is absent when the client sent no metadata.

    Values are MiDaS inverse RELATIVE depth -- larger means nearer, and there
    is NO metric scale. Nothing here converts it to metres.
    """
    with processing_lock:
        payload = latest_depth_npy
        meta = depth_meta

    if payload is None:
        return JSONResponse(
            status_code=404,
            content={"message": "No depth generated yet"},
        )

    headers = {"X-Depth-Units": "midas-inverse-relative-unscaled"}
    if meta is not None and meta.get("seq") is not None:
        headers["X-Frame-Seq"] = str(meta["seq"])
    if meta is not None and meta.get("ts_ns") is not None:
        headers["X-Frame-Timestamp-Ns"] = str(meta["ts_ns"])

    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers=headers,
    )


@app.get("/latest-frame-meta")
def get_latest_frame_meta():
    """Metadata of the most recent RGB frame, and of the frame behind the depth.

    `depth_frame` is what matters for reconstruction: it is the metadata of
    the capture `latest_depth` was actually computed from. Because inference
    is latest-frame-wins and slower than the uplink, it routinely lags
    `latest_frame` by several frames -- comparing the two seq numbers shows
    by how much, rather than leaving it to be assumed.
    """
    with processing_lock:
        latest = latest_meta
        d_meta = depth_meta

    return {
        "status": "ok",
        "latest_frame": latest,
        "depth_frame": d_meta,
        "seq_lag": (
            (latest or {}).get("seq", 0) - (d_meta or {}).get("seq", 0)
            if latest and d_meta
            and latest.get("seq") is not None and d_meta.get("seq") is not None
            else None
        ),
    }


# =========================
# LATEST FRAME
# =========================

@app.get("/latest-frame")
def get_latest_frame():

    if latest_frame is None:

        return JSONResponse(
            status_code=404,
            content={
                "message": "No frame received yet"
            }
        )

    filename = UPLOAD_DIR / "latest.jpg"

    cv2.imwrite(
        str(filename),
        latest_frame
    )

    return {
        "status": "ok",
        "file": str(filename),
        "frame": frame_count
    }


# =========================
# LATEST DEPTH
# =========================

@app.get("/latest-depth")
def get_latest_depth():

    with processing_lock:
        depth = latest_depth

    if depth is None:

        return JSONResponse(
            status_code=404,
            content={
                "message": "No depth generated yet"
            }
        )

    return {

        "status": "ok",

        "shape": list(depth.shape),

        "min": float(depth.min()),

        "max": float(depth.max()),

        "file": str(
            DEPTH_DIR / "latest_depth.png"
        )

    }


@app.get("/latest-depth-image")
def get_latest_depth_image():

    global latest_depth_png

    with processing_lock:
        depth = latest_depth
        png_bytes = latest_depth_png

    # Server restart recovery: the last phone-derived MiDaS depth PNG is
    # persisted on disk by the inference worker, so a backend restart (e.g.
    # uvicorn --reload) must not 404 and drop the /scan compatibility layer.
    if png_bytes is None:
        persisted = DEPTH_DIR / "latest_depth.png"
        if persisted.exists() and persisted.stat().st_size > 0:
            png_bytes = persisted.read_bytes()
            latest_depth_png = png_bytes

    # png_bytes alone is sufficient: after a restart the last phone-derived
    # depth is restored from disk even though no inference has run yet.
    if png_bytes is None:
        return JSONResponse(
            status_code=404,
            content={
                "message": "No depth image available yet"
            }
        )

    # Serve the exact encoded bytes produced by the worker (immutable
    # snapshot) so the response length always matches the body — a reader
    # can never hit an IncompleteRead from a concurrently rewritten file.
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-FYP-Depth-Sequence": str(frame_count),
        },
    )
