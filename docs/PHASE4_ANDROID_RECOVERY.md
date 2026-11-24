# Phase 4A — Android application recovery

**Milestone 1: backup and preservation. No repairs are included in this
commit.** The application is imported exactly as found, so that every later
repair is a reviewable diff against the real broken state.

**Branch:** `phase-4-android`, based on the verified Phase 3 release
`02e2691d487b902ad78109489ae8f965b9cbebd4`.
**Date:** 24 November 2026. **Machine:** HP ZBook 15 G6 (Machine B).

## 1. Why this milestone exists

Before this commit the Android application existed **only** at
`/home/hammad/AndroidStudioProjects/FYP3D` on one laptop:

- outside the Git repository,
- not under any version control of its own (`git rev-parse` fails there),
- not archived anywhere.

A single `rm -rf`, a disk failure or an Android Studio "clean project" would
have destroyed the only copy of the app. It is also the component the whole
official FYP direction depends on — the smartphone camera is the primary
sensor — so losing it would have cost more than any other directory in the
project.

## 2. Backup

A complete archive of the project **including** build outputs, IDE state and
Gradle caches (i.e. more than is committed here):

```
/home/hammad/FYP-data/android_backup/FYP3D_pristine_20261124.tar.gz
sha256 acc89e97aba38acc2c87cb138d551ba65f242086481d42074e5967e32e7cdb34
size   40,226,267 bytes
```

Checksum recorded alongside it in `SHA256SUMS.txt`.

**The archive was verified by restoring it, not merely by creating it.** It
was extracted to a scratch directory and compared with `diff -r` against the
source tree: **753 files, zero differences**. A `tar` that cannot be
restored is not a backup, so this check is the point of the exercise rather
than a formality.

The archive lives under `FYP-data/`, outside the repository, because it
contains a 13.9 MB APK and ~40 MB of Gradle/IDE caches that do not belong in
Git history. **It is still on the same disk as the original**, so it
protects against accidental deletion and bad edits but **not** against disk
failure. Copying it to external or cloud storage is the user's call and has
not been done.

## 3. What is committed here

41 files under `android/` — source, resources, Gradle configuration and the
wrapper. Verified **byte-identical** to the original for all 40 files
(`cmp` per file); the only modified file is `android/.gitignore`, where
lines were **appended** and none changed.

Deliberately excluded (and why):

| Excluded | Reason |
|---|---|
| `app/build/`, `build/` | build outputs; regenerable, and `build/` is already ignored repo-wide |
| `.gradle/`, `.kotlin/` | Gradle/Kotlin caches, machine-specific |
| `.idea/` | Android Studio IDE state, machine-specific |
| `local.properties` | contains `sdk.dir=/home/hammad/Android/Sdk`, i.e. a path valid on this machine only |
| `app-debug.apk` | 13.9 MB binary, ignored repo-wide, and **functionally useless** (section 5) |

All five are preserved in the tar.gz. The APK's identity is recorded in
section 5 so the claim about it stays checkable.

A fresh clone therefore needs **either** a `android/local.properties`
containing `sdk.dir=<path to Android SDK>` **or** `ANDROID_HOME` exported.
This is the standard Android convention; the file is excluded on purpose.

### `.gitignore` negations were required

The repository root `.gitignore` line 62 is a blanket `*.backup` rule for
scratch files. It silently matched the two **most valuable** files in the
recovery (section 4). `git add android` skipped both without a word. Two
negations were appended to `android/.gitignore`, and the result verified
with `git check-ignore` — staged file count went from 39 to 41.

This is recorded because a silent `.gitignore` match is exactly the kind of
failure that would have made this whole milestone worthless while appearing
to succeed.

## 4. Forensic timeline of the breakage

Reconstructed from file modification times. This explains **why** the app is
broken, which determines how it should be repaired.

| When (2026) | Size | File |
|---|---|---|
| 4 Sep 11:40 | 616 B | `settings.gradle.kts` — project created by Android Studio |
| 4 Sep 11:40 | 1749 B | `gradle/libs.versions.toml` |
| 4 Sep 12:04 | **1585 B** | **`app/build.gradle.kts.backup`** — working Compose build script |
| 4 Sep 12:07 | 1183 B | `AndroidManifest.xml` |
| 5 Sep 10:15 | 13.9 MB | `app-debug.apk` built successfully |
| 5 Sep 10:25 | **0 B** | **`app/build.gradle.kts` truncated to empty** |
| 9 Sep 06:28 | 10255 B | `MainActivity.kt` overwritten with the WebSocket version |

Three conclusions follow, and they matter for the repair:

**1. The module build script was emptied ten minutes after the last
successful build.** `app/build.gradle.kts` is 0 bytes — `sha256
e3b0c442…b7852b855` is the hash of the empty file, so this is genuine
truncation, not a parse problem. Gradle cannot configure the `:app` module
at all.

**2. `MainActivity.kt` was pasted as a shell command, not as Kotlin.** The
file begins

```
cat > ~/FYP/MiDaS/mobile/android/app/src/main/java/com/fyp/reconstruction/MainActivity.kt <<'EOF'
```

and ends with `EOF`. A heredoc intended for a terminal was pasted into the
editor. Line 1 is a Kotlin syntax error. The embedded source additionally
declares `package com.fyp.reconstruction` while living in
`app/src/main/java/com/example/fyp3d/`, and the target path it names
(`~/FYP/MiDaS/...`) does not exist on this machine.

**3. The WebSocket code was written *after* the build was already broken, so
it has never been compiled even once.** The build script was emptied on
5 Sep; `MainActivity.kt` was replaced on 9 Sep. Nothing has verified that
the streaming code works — not a device test, not a compile.

## 5. The existing APK cannot be used, and cannot be reproduced

```
app/build/outputs/apk/debug/app-debug.apk   (5 Sep 2026, in the tar.gz only)
sha256 8791da082e98ff6caba369d853f0cf6acfa3d2d41f9355bb59aa6635d1c46f38
```

`aapt dump badging` and a `strings` scan of all **seven** dex files:

| Probe | Result |
|---|---|
| `okhttp` / `okio` entries | **absent** |
| `"WebSocket"` across all dex | **0 occurrences** |
| `ws://` or `192.168.*` strings | **none** |
| CameraX (`PreviewView`, `ProcessCameraProvider`) | 88 occurrences |
| Permissions | `CAMERA`, `RECORD_AUDIO` — **no `INTERNET`** |

Its dex references `MainActivity.CameraScreen (MainActivity.kt:54)` — a
Jetpack Compose camera screen, **not** the WebSocket activity in the current
source file. So the APK was built from source that has since been
overwritten, and it contains **no networking code of any kind**.

Two consequences:

- Installing it would give a camera preview that never contacts the backend.
  It cannot be used to demonstrate anything about physical integration.
- It is **not reproducible**: the build script that produced it is gone. Even
  `app/build.gradle.kts.backup` does not match it — that file declares only
  Compose dependencies, with no CameraX, yet the APK contains CameraX. So an
  intermediate version of the build script, now lost, added camera
  dependencies between 4 Sep 12:04 and 5 Sep 10:15.

The APK is therefore kept as **evidence of the as-found state only**, and is
not a baseline for the repair.

## 6. What the recovered `.backup` gives us

`app/build.gradle.kts.backup` is the project's own original, generated by
Android Studio and then edited by hand. It fixes the values that would
otherwise have to be guessed:

```
namespace / applicationId  com.example.fyp3d
compileSdk 37   minSdk 26   targetSdk 37
versionCode 1   versionName "1.0"
Java 11 source/target, Compose enabled
```

These agree with the APK's own badging (`sdkVersion:'26'`,
`targetSdkVersion:'37'`, `compileSdkVersion='37'`), so they are
cross-confirmed from two independent artefacts rather than assumed.

What it does **not** contain: CameraX and OkHttp. Both are imported by the
current `MainActivity.kt`, so both must be added — that is a genuine
addition, not a restoration, and is noted as such.

The wrapper backup also records a change worth knowing: the original pointed
at `https://services.gradle.org/.../gradle-9.6.0-bin.zip` with
`validateDistributionUrl=true`, whereas the live file points at
`file:///home/hammad/Downloads/gradle-9.6.0-bin.zip` with validation
disabled. The local zip exists (140 MB) and is already unpacked under
`~/.gradle/wrapper/dists/`, so the live setting builds offline on this
machine but **will fail on any other machine**. The SHA-256 is identical in
both, so the local zip is the genuine distribution. Not changed in this
milestone.

## 7. Backend protocol — unchanged, and read from source

The repair must match the backend that already exists; the protocol was
**not** invented and is **not** being modified. From `backend/api/main.py`
and confirmed against `docs/API.md`:

| Element | Implementation |
|---|---|
| Endpoint | `WS /ws/video` (`main.py:211`) |
| Bind | `0.0.0.0:8000` (`run_backend.sh`) |
| Uplink message | **binary only** — `await websocket.receive_bytes()` |
| Payload | **raw JPEG bytes, nothing else** — no header, no envelope |
| Decode | `np.frombuffer` → `cv2.imdecode(IMREAD_COLOR)` |
| Downlink | one JSON text message per frame |
| MiDaS | background thread, **latest-frame-wins** (`pending_frame` overwritten) |
| Depth out | `GET /latest-depth`, `GET /latest-depth-image` (PNG) |
| Discovery | UDP `51315`, probe `FYP_DISCOVER_REQ` → `FYP_BACKEND|<ip>|<port>` |

Two properties of this contract constrain what the app can do:

- **There is no sequence number or timestamp field.** `frame_count` is a
  server-side counter incremented on arrival. The phone has no way to send
  either, and the backend has nowhere to store them. Adding them is a
  **both-side protocol change** and is out of scope for this milestone.
- **The per-frame ack means "received", not "depth ready."** Inference is
  decoupled and drops stale frames, so depth appears at the model's own rate
  (~5.3 fps on this machine's Quadro T2000) regardless of uplink rate.

## 8. Verified state of this milestone

| Check | Result |
|---|---|
| Archive created and `gzip -t` clean | yes |
| Archive restores identically (`diff -r`, 753 files) | **0 differences** |
| Imported source vs original (`cmp`, per file) | **40/40 identical** |
| `.gitignore` negations effective (`git check-ignore`) | 41/41 staged |
| Branch base | `02e2691` exactly |
| Phase 1/2/3 files touched | **none** |
| Backend files touched | **none** |
| Repairs applied | **none — deliberately** |

## 9. Not yet true

Stated plainly so nothing here is mistaken for progress on the real goal:

- The app **still does not build.** This milestone preserved it; it did not
  fix it.
- **No physical Android device has ever been connected.** `adb devices` is
  empty and `lsusb` shows only internal peripherals.
- **No physical-device test has ever been run.** Every passing uplink figure
  in `docs/API.md` (60/60 frames, ~6 ms ack, ~11 fps) came from
  `scripts/test_backend_pipeline.py`, which replays three saved desktop JPEGs
  over localhost. Those results say nothing about a phone.
- The backup is on the **same physical disk** as the original.

## 10. Known blockers for the next milestone

Carried forward from the Phase 4A audit, all measured rather than assumed:

1. `app/build.gradle.kts` is empty — build impossible.
2. `MainActivity.kt` is a shell heredoc — compile impossible.
3. `INTERNET` permission absent from the manifest.
4. Cleartext blocked: `targetSdk 37` with no `usesCleartextTraffic` and no
   `networkSecurityConfig`, while the protocol is `ws://` (cleartext).
5. CameraX and OkHttp not declared in `libs.versions.toml`.
6. Server URL hard-coded to `ws://192.168.2.107:8000/ws/video`, while this
   laptop is `192.168.1.106` — **a different /24**, and DHCP-assigned, so it
   will drift again.
7. No UDP discovery client, although the backend responder exists.
8. `scripts/phone_stream_watchdog.sh` and `scripts/fyp30_record30.py`
   hard-code package `com.fyp.reconstruction`, but the real application id is
   `com.example.fyp3d`. Their `adb am start` calls fail silently.
9. `ufw` is active and its rules were **not** read (requires sudo), so
   whether ports 8000/51315 are open is **unknown**, not verified.
10. The NV21 conversion in `MainActivity.kt` ignores `pixelStride` and
    `rowStride`, which corrupts colour on many devices. MiDaS will still
    produce plausible-looking depth from a corrupted frame, so a saved
    `backend/uploads/` JPEG must be inspected **visually** rather than
    trusting that depth appeared.
