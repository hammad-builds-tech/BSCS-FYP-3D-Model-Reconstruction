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

---

# Milestone 2 — repair and first successful build

**Date:** 24 November 2026. **Branch:** `phase-4-android`.
**Baseline:** the as-found state preserved in `1ff73cb`.

**No physical device was connected at any point during this milestone, and no
physical-device test is claimed.** `adb devices` was empty throughout. What is
claimed is exactly this: the application now compiles, and the resulting APK
has been inspected and contains what it must.

## 11. Restored Gradle configuration

`app/build.gradle.kts` was restored from `app/build.gradle.kts.backup`. Every
value is carried over **unchanged**:

| Setting | Value | Confirmed by |
|---|---|---|
| `namespace` / `applicationId` | `com.example.fyp3d` | backup + APK badging |
| `compileSdk` | 37 | backup + `compileSdkVersion='37'` |
| `minSdk` | 26 | backup + `sdkVersion:'26'` |
| `targetSdk` | 37 | backup + `targetSdkVersion:'37'` |
| Java source/target | 11 | backup |
| Compose | enabled | backup |
| `versionCode` / `versionName` | 1 / "1.0" | backup |

Nothing was upgraded. AGP stays **9.4.0**, Kotlin **2.2.10**, Gradle
**9.6.0**, Compose BOM **2026.02.01**.

### No standalone Kotlin plugin was added

The backup declares only `com.android.application` and
`org.jetbrains.kotlin.plugin.compose` — there is no
`org.jetbrains.kotlin.android`. That looks wrong, but the 5 Sep APK contains
compiled Kotlin, so AGP 9.x evidently provides built-in Kotlin support. The
original plugin set was therefore preserved, and the build confirms it:
`compileDebugKotlin` executes and succeeds. Adding the standalone plugin would
have been an unrequested toolchain change made on a false premise.

### Gradle wrapper portability fixed

| | `distributionUrl` | `validateDistributionUrl` |
|---|---|---|
| As found | `file:///home/hammad/Downloads/gradle-9.6.0-bin.zip` | `false` |
| Now | `https://services.gradle.org/distributions/gradle-9.6.0-bin.zip` | `true` |

Restored from `gradle-wrapper.properties.backup` — i.e. the project's own
original — so the repository now builds on any machine. The version is
unchanged at 9.6.0 and `distributionSha256Sum` was already present.

**Why it had been repointed at a local file.** The Gradle dist cache shows
two entries for 9.6.0, one keyed by each URL. The HTTPS-keyed entry held a
`gradle-9.6.0-bin.zip.part` of **14,186,780 of 140,681,093 bytes** and no
`.ok` marker: the original download died about 10 % in. Switching to a
hand-downloaded `file://` zip was a reasonable workaround for a bad
connection, not carelessness — it just cannot be committed.

**Local cache seeded so the build stays offline-capable.** Changing the URL
changes Gradle's cache key, which would normally force a fresh 140 MB
download. The hand-downloaded zip's SHA-256 is
`bbaeb2fe…a529a01`, **identical to the `distributionSha256Sum` the wrapper
already declared**, so it is byte-for-byte the official distribution. It was
copied into the HTTPS-keyed cache entry and marked `.ok`, after confirming
with `diff -r` that the two already-extracted distributions were identical
(422 library jars each) and that `bin/gradle --version` reports Gradle 9.6.0.
This is a change to the local Gradle cache only — **no repository file and no
system package** — and it means this machine builds without network access
while the committed wrapper is fully portable.

## 12. Dependencies added

Added to `gradle/libs.versions.toml` with **exact pins**. The existing
Compose entries were not touched and nothing was upgraded.

| Dependency | Version | Why this version |
|---|---|---|
| `androidx.camera:camera-core` | **1.5.0** | already in this machine's Gradle cache **and present in the 5 Sep APK**, so proven against AGP 9.4.0 / compileSdk 37 |
| `androidx.camera:camera-camera2` | 1.5.0 | Camera2 backend for the above |
| `androidx.camera:camera-lifecycle` | 1.5.0 | `ProcessCameraProvider` |
| `androidx.camera:camera-view` | 1.5.0 | `PreviewView` |
| `com.squareup.okhttp3:okhttp` | **4.12.0** | cached, stable, Kotlin-native WebSocket client |
| `com.squareup.okio:okio` | **3.6.0** | **exactly what okhttp 4.12.0's POM declares** |

Checks made rather than assumed:

- `camera-core` 1.5.0's AAR declares `minSdkVersion 23` ≤ our 26.
- OkHttp 4.12.0's POM declares `okio 3.6.0`, so the explicit Okio pin cannot
  introduce a conflicting version. Okio is pinned at all because
  `MainActivity` uses `okio.ByteString` directly, not only through OkHttp.
- OkHttp 4.12.0's POM asks for `kotlin-stdlib-jdk8 1.8.21`; Gradle resolves
  that upward to the project's 2.2.10.

**`camera-video` was deliberately omitted** — nothing records video, and
leaving it out is what makes the `RECORD_AUDIO` removal clean.

## 13. Kotlin repairs

`MainActivity.kt`: 401 lines as found → 624 lines repaired and extended.

| # | Repair |
|---|---|
| 1 | Removed the shell heredoc: `cat > … <<'EOF'` (line 1) and `EOF` (line 401). **No shell command remains in any Kotlin file.** |
| 2 | `package com.fyp.reconstruction` → `package com.example.fyp3d`, matching both the `namespace` and the directory `com/example/fyp3d/`. |
| 3 | Added the missing imports the extended code needs; all imports resolve (clean compile, **zero warnings**). |
| 4 | Preserved the original approach: View-based UI, CameraX `ImageAnalysis`, OkHttp WebSocket, NV21 → JPEG. Not rewritten into Compose, not replaced with a placeholder. |
| 5 | Extracted the YUV conversion into `YuvConverter.kt` so it is unit-testable off-device (section 15). |

The `ui/theme/*.kt` Compose files are untouched and still compile, which is
why the Compose dependencies remain required.

`.MainActivity` in the manifest resolves against the `com.example.fyp3d`
namespace; the APK confirms
`launchable-activity: name='com.example.fyp3d.MainActivity'`.

## 14. Camera implementation

- `ImageAnalysis` with **`STRATEGY_KEEP_ONLY_LATEST`**: CameraX discards older
  frames instead of queuing them, so latency stays flat under a ~5 fps uplink
  against a ~30 fps camera.
- Analysis runs on a single-thread executor; **every path through
  `handleFrame` closes the `ImageProxy` exactly once** in a `finally`. A
  leaked proxy stalls the analyzer permanently, because CameraX will not
  deliver another frame until one is released.
- Resolution is left at the `ImageAnalysis` default (≈640×480) rather than
  configured, to avoid depending on API details of
  `ResolutionSelector` in this CameraX version.
- **Rotation is applied.** The analyzer delivers frames in *sensor*
  orientation, so on an upright phone the back sensor is typically 90°
  rotated. An unrotated frame would reach MiDaS on its side; MiDaS would
  still return a plausible depth map, and the downstream `depth_to_scan`
  geometry assumes an upright image. Frames are therefore rotated by
  `imageInfo.rotationDegrees` when non-zero. This costs a decode/re-encode,
  affordable at ~5 fps.

## 15. The YUV conversion is verified, not merely reviewed

This is the one part of the milestone that can fail **silently**: a stride
mistake still yields a decodable JPEG, so MiDaS produces plausible depth and
nothing reports an error. It was therefore extracted into
`YuvConverter.toNv21(...)` — which takes `ByteBuffer`s and strides, no Android
types — and tested on the JVM.

The recovered implementation made two assumptions that real hardware breaks:

1. `rowStride == width`. False when rows are hardware-aligned; a flat bulk
   copy then drags padding into the image and shears it progressively.
2. chroma `pixelStride == 1`. False on semi-planar devices, where U and V are
   views into one interleaved allocation with `pixelStride == 2`; reading them
   as packed duplicates and swaps chroma.

`./gradlew testDebugUnitTest` → **6 tests, 0 failures, 0 errors** (plus the
pre-existing `ExampleUnitTest`):

| Test | What it pins down |
|---|---|
| `packed planes round-trip exactly` | fast path correct; chroma interleaved **V first** |
| `row padding in the luma plane is not copied into the image` | padding filled with a poison byte must appear nowhere in the output |
| `semi-planar chroma with pixelStride 2 is de-interleaved correctly` | the real-device layout the original mishandled |
| `luma pixelStride greater than one is honoured` | slow path correct |
| `output size is always 12 bits per pixel` | 2×2 up to 1280×720 |
| `the recovered naive algorithm is provably wrong on padded rows` | **the suite is not vacuous** |

That last test reproduces the original buggy algorithm and asserts it
*disagrees* with the fixed converter on the same input — a test that cannot
fail would prove nothing, so the suite's discriminating power is itself
asserted. If anyone later "simplifies" the converter back to a bulk copy,
these tests fail.

**Limit of this evidence:** the tests prove the conversion is correct *for the
stride combinations they construct*. They cannot prove what strides a
particular phone's camera will actually report. A real frame must still be
inspected by eye in Milestone 3.

## 16. WebSocket implementation

Follows the existing contract exactly; **the backend was not modified**.

| Requirement | Implementation |
|---|---|
| Endpoint | `ws://<host>:<port>/ws/video` |
| Binary frames | `socket.send(ByteString.of(*jpeg))` |
| Raw JPEG only | no envelope, no header, no prefix |
| Ack handling | `onMessage(text)` increments an ack counter |
| Connection state | shown on screen, colour-coded |
| Frame counter | `sent · acked · dropped` |
| Graceful disconnect | `close(1000, reason)` → backend logs `PHONE DISCONNECTED` |
| Reconnect | 1 s, 2 s, 4 s, 8 s, capped at 10 s, only while streaming |

Deliberate choices:

- **No sequence numbers or timestamps.** The protocol has no field for either
  and `frame_count` is server-side; adding them is a coordinated both-side
  change (section 7) and was explicitly out of scope.
- **Rate limited, default 5 fps**, editable on screen and persisted. Matched
  to the measured ~5.3 fps backend inference rate. Sending faster is pure
  waste: the backend overwrites `pending_frame`, so surplus frames are
  dropped server-side anyway.
- **Bounded queue.** `OkHttp.send()` buffers without limit, so an unthrottled
  producer on a slow link grows the queue until the process dies. If
  `queueSize()` exceeds 2 MB the newest frame is dropped and counted — the
  same latest-frame-wins policy the backend uses.
- **5 s ping interval.** A half-open Wi-Fi socket is the usual failure when a
  phone walks out of range; pings turn that into an `onFailure` that the
  reconnect path can act on, instead of the stream silently stopping.
- **Errors are surfaced verbatim.** `ECONNREFUSED` (backend down),
  `ETIMEDOUT` (wrong subnet or AP isolation) and `CLEARTEXT communication not
  permitted` are three different faults that a generic "connection failed"
  would hide. The server's `1008 stream locked` close
  (`FYP_VIDEO_STREAM_LOCK=1`) is also reported as such.
- `onDestroy` closes the socket, shuts down the camera executor, and shuts
  down OkHttp's dispatcher and connection pool.

## 17. Backend address configuration

The hard-coded `ws://192.168.2.107:8000/ws/video` is **gone** — confirmed
absent from the built APK's dex.

- Editable **IPv4** field, validated by regex with per-octet 0–255 bounds.
- Editable **port**, default **8000**, validated to 1–65535.
- Editable **fps**, default 5, validated to 0 < fps ≤ 30.
- Persisted in `SharedPreferences` (`fyp3d_backend`), restored on launch.
- **Default host is empty**, never a developer's own address: the previous
  default pointed at a different `/24` from this laptop and was permanently
  unreachable. A wrong default is worse than no default.

## 18. Network configuration

| | Debug | Release |
|---|---|---|
| `cleartextTrafficPermitted` | **`true`** | **`false`** |
| Source | `app/src/debug/res/xml/network_security_config.xml` | `app/src/main/res/xml/network_security_config.xml` |

Implemented as a **source-set resource overlay** on one resource name, with
`android:networkSecurityConfig` declared once in the main manifest. **No
blanket `android:usesCleartextTraffic` is used anywhere.**

Verified in the built artefacts with `aapt2 dump xmltree` — not assumed from
the source:

- debug APK → `cleartextTrafficPermitted=true`
- release APK (`app-release-unsigned.apk`) → `cleartextTrafficPermitted=false`

**Why development uses unencrypted WebSocket.** The backend serves plain
`ws://` on `0.0.0.0:8000` with no TLS in front of it, and Android has blocked
cleartext by default since API 28 while this app targets API 37. Rather than
weaken the whole app, cleartext is enabled only in the debug build, for lab
use on a private RFC 1918 network between one phone and one laptop.

**Why production must use `wss://`.** Over `ws://` the stream is
unauthenticated and unencrypted: anyone on the same Wi-Fi can read the frames
of the room being mapped, and nothing stops them connecting to `/ws/video`
and injecting frames into the depth pipeline. Outside a controlled lab the
backend must terminate TLS and the app connect over `wss://` — at which point
the cleartext exception is **deleted**, not merely narrowed.

**Scope stated accurately.** The debug policy permits cleartext to **all**
destinations, not just the laptop's subnet. Android's Network Security
Configuration has **no CIDR or subnet rule** — `<domain>` matches hostnames
and literal addresses only — and the backend IP is entered at runtime and
DHCP-assigned, so it cannot be enumerated at build time. Claiming
"cleartext allowed for the local subnet" would be false; the honest statement
is "cleartext allowed in debug builds".

Manifest also changed: **`INTERNET` added** (it was missing, so socket
creation threw before any packet left the device), `CAMERA` retained,
`RECORD_AUDIO` **removed** — nothing records audio (no `MediaRecorder`, no
`AudioRecord`, no `camera-video`), so requesting it was a needless privacy ask.

## 19. Build instructions and results

```
cd android
export JAVA_HOME=/usr/lib/jvm/java-25-openjdk-amd64   # or Studio's JBR 25
echo "sdk.dir=$HOME/Android/Sdk" > local.properties    # gitignored, per machine
./gradlew clean assembleDebug
./gradlew testDebugUnitTest
```

`gradle/gradle-daemon-jvm.properties` pins `toolchainVersion=25`, so a JDK 25
is required; `java-25-openjdk-amd64` and `/opt/android-studio/jbr` both work.
`local.properties` is intentionally not committed (machine-specific
`sdk.dir`); `ANDROID_HOME` works instead.

| Run | Result |
|---|---|
| `./gradlew clean assembleDebug` | **BUILD SUCCESSFUL in 22 s**, 37 tasks |
| Kotlin compile warnings | **0** |
| `./gradlew testDebugUnitTest` | **BUILD SUCCESSFUL**, 6 + 1 tests, 0 failures |
| `./gradlew assembleRelease` | **BUILD SUCCESSFUL** (unsigned; built only to verify the cleartext policy) |

**APK location:** `android/app/build/outputs/apk/debug/app-debug.apk`
(14,461,127 bytes, sha256 `4848bc8b091ac991004962533b7e67c1906c78cefe7492cc7dbdc0d69de1d8eb`).
Gitignored, as build outputs should be.

Note the first build **failed**, and correctly: AGP rejected
`network_security_config.xml` because XML comments may not contain `--`, which
the explanatory comments used as underlines and in `uvicorn --host` / `aapt
--file` examples. Recorded because the fix is in the committed files and the
failure is reproducible from the logs.

## 20. APK verification

All probes run against the **newly built** APK, not the September one.

| Check | Result |
|---|---|
| APK produced from repaired source | ✅ sha256 `4848bc8b…`, differs from the Sep APK `8791da08…` |
| Application id | ✅ `com.example.fyp3d` |
| Launchable activity | ✅ `com.example.fyp3d.MainActivity` |
| `INTERNET` in merged manifest | ✅ present |
| `CAMERA` | ✅ present |
| `RECORD_AUDIO` | ✅ **0 occurrences** |
| OkHttp classes | ✅ **725** `okhttp3` references |
| `WebSocket` symbols | ✅ **96** (the Sep APK had **0**) |
| Okio classes | ✅ 196 `Lokio/` references |
| CameraX packages | ✅ all 4 (`core`, `camera2`, `lifecycle`, `view`) |
| `YuvConverter` class | ✅ present |
| `/ws/video` endpoint string | ✅ present |
| Old hard-coded IP | ✅ **0 occurrences** of `192.168.2.107` |
| `SharedPreferences` store | ✅ `fyp3d_backend` present |
| Unresolved imports / Kotlin errors | ✅ none — clean compile |

`android:networkSecurityConfig` was read from the **merged manifest** and via
`aapt2`. The system `aapt` (1:14~beta1-5) returns nothing for it and cannot
dump the compiled `res/xml` — a limitation of that old tool against
compileSdk 37 binary XML, not a build problem. `aapt2` from build-tools
36.0.0 reads both correctly. In the release APK resource paths are renamed,
so the config was located by scanning for the `network-security-config`
element rather than by filename.

## 21. Known limitations after Milestone 2

**Nothing below is a claim of success; these are the open items.**

1. **No physical-device test has happened.** No phone has ever been connected
   to this project. Everything above is a build-and-inspect result.
2. **The streaming path has never executed.** It compiles and the classes are
   in the APK; not one frame has been captured, converted, or sent. The
   WebSocket client, the reconnect logic, the rate limiter and the rotation
   path are all **unexecuted code**.
3. **The YUV conversion is verified only for constructed stride
   combinations.** What a given phone reports is unknown; a real uploaded
   frame must be checked by eye.
4. **Cleartext is permitted to all destinations in debug builds** — not
   subnet-scoped, because Android offers no such rule.
5. **The release build is unsigned** and has no signing config. It was built
   only to verify the cleartext policy; it is not a distributable artefact.
6. **No UDP discovery client.** The backend responder exists and is unused;
   manual IP entry is deliberate for the first connection.
7. **`ufw` is active and its rules were never read** (needs sudo), so whether
   ports 8000/51315 are reachable from the phone is **unknown**.
8. **Helper scripts still target the wrong package.**
   `scripts/phone_stream_watchdog.sh` and `scripts/fyp30_record30.py`
   hard-code `com.fyp.reconstruction`; the real id is `com.example.fyp3d`, so
   their `adb am start` calls fail silently. Left untouched here because they
   are Phase 1/2/3 files.
9. **No sequence numbers or timestamps**, by design — needs a both-side
   protocol change.
10. **`~/AndroidStudioProjects/FYP3D` still holds the original broken files.**
    Nothing there was deleted or modified. The repository's `android/`
    directory is now the canonical copy and is what should be opened in
    Android Studio. The stale directory is a trap for a future session.
11. **The rotation path decodes and re-encodes each frame**, costing CPU and a
    second lossy JPEG pass. Acceptable at 5 fps; it would need replacing with
    a YUV-domain rotation at higher rates.

---

# Milestone 4 — physical camera orientation correction

**Date:** 24 November 2026. **Branch:** `phase-4-android`.
**Device:** Google Pixel 7 Pro (`cheetah`), **Android 16** (SDK 36), CameraX 1.5.0.
**Baseline:** `d3e8441`.

Milestone 3 established that frames reach the backend, colours are correct and
the YUV stride handling works on real hardware, but that the transmitted image
was **90 degrees from upright**. This milestone measures why, fixes it, and
verifies the fix on the physical device.

## 22. The defect, as observed in Milestone 3

The app delivered a **480x640 portrait** JPEG whose contents were sideways.
Rotating the saved frame 90 degrees counter-clockwise produced a correct
upright image at **640x480 landscape** -- i.e. for that capture the correct
action was *no rotation at all*, and the app had rotated by 90 anyway.

## 23. Where rotation was applied (inspection, before any change)

- `ImageAnalysis.Builder()` set **only** `setBackpressureStrategy(...)`.
  **`targetRotation` was never set**, so CameraX used its default: the
  **display rotation at bind time**.
- Rotation was applied to **pixels**, once, in `imageProxyToJpeg`: the NV21
  frame is JPEG-encoded, then if `imageInfo.rotationDegrees != 0` the JPEG is
  decoded, rotated with a `Matrix`, and re-encoded.
- So the implementation used metadata (`rotationDegrees`) to decide **how
  much** to rotate, and then genuinely rotated pixels. There was no second,
  independent correction -- the single rotation was simply being given the
  wrong input.

## 24. Diagnostic measurements

Logging was added **first**, with no behaviour change, because the Milestone 3
root cause was explicitly a hypothesis. It records the physical orientation
(`OrientationEventListener`), the display rotation, `ImageAnalysis
.targetRotation`, `imageInfo.rotationDegrees`, the raw buffer size and the
**actual decoded output JPEG size**. It logs only when a value changes, never
per frame.

Measured on the Pixel 7 Pro with auto-rotate **locked to portrait**
(`accelerometer_rotation = 0`):

| # | physical bucket | display | targetRotation | rotationDegrees | raw | output JPEG |
|---|---|---|---|---|---|---|
| 1 | ROTATION_0 | ROTATION_0 | ROTATION_0 | **90** | 640x480 | 480x640 |
| 2 | **ROTATION_90** | ROTATION_0 | ROTATION_0 | **90** | 640x480 | 480x640 |

Row 2 is the proof. The device was physically turned to landscape -- the
sensor reported `physical=303deg -> ROTATION_90` -- and **`rotationDegrees`
did not change**, nor did the output geometry. The frame kept being rotated
90 degrees to suit a portrait *display* while the camera was physically
pointing at the world sideways.

`rotationDegrees` therefore tracks the **display**, not the device. The
Milestone 3 hypothesis is confirmed by measurement rather than assumed.

## 25. Root cause

`ImageAnalysis.targetRotation` defaulted to the display rotation. With
auto-rotate locked to portrait the display rotation is pinned at
`ROTATION_0` no matter how the phone is held, so CameraX computed a correction
appropriate for a portrait display and the app faithfully applied it. The
rotation code was correct; **its input was derived from the wrong thing**.

## 26. Correction implemented

`targetRotation` is now driven by the **physical** device orientation via
`OrientationEventListener`, following the official CameraX rotation guidance.
CameraX then recomputes `rotationDegrees` itself, and that value is still
applied exactly **once**, in pixels, where it always was.

- The azimuth-to-`Surface` mapping is the official one, and the inversion is
  deliberate: a device rotated clockwise needs the image rotated
  counter-clockwise, so 45..134 degrees maps to `ROTATION_270`, 135..224 to
  `ROTATION_180`, 225..314 to `ROTATION_90`, otherwise `ROTATION_0`. Getting
  this backwards converts a 90-degree error into a 270-degree one.
- `ORIENTATION_UNKNOWN` (-1) is ignored and the previous value retained. This
  is not a corner case: it is what the sensor reports with the phone lying
  flat, which is exactly how it sat at the start of the Milestone 3 test.
- `targetRotation` is written **only when the bucket changes**, not per event.
- The listener is enabled when the camera binds and disabled in `onDestroy`,
  alongside the other camera resources.
- `canDetectOrientation()` is checked; a device without the sensor logs a
  warning instead of silently doing nothing.
- **No independent display-based correction was added.** There is exactly one
  `targetRotation` assignment and exactly one pixel rotation in the file.

The backend, the WebSocket protocol and the 5 fps limit are untouched.

## 27. Physical verification

Every capture below is a real JPEG received by the FastAPI backend from the
Pixel 7 Pro and **inspected visually**, not inferred from metadata.

| Case | physical | targetRotation | rotationDegrees | output | upright? |
|---|---|---|---|---|---|
| Portrait, auto-rotate **locked** | ROTATION_0 | ROTATION_0 | **90** | **480x640** | ✅ |
| Landscape, auto-rotate **locked** | ROTATION_90 | **ROTATION_90** | **0** | **640x480** | ✅ |
| Landscape, auto-rotate **on** | ROTATION_90 | ROTATION_90 | 0 | 640x480 | ✅ |

`rotationDegrees` now responds to how the phone is **held**: 90 when upright,
0 when sideways. In the landscape case the correct action is no rotation, and
the app now does none -- the exact behaviour Milestone 3 showed was required.

Visual inspection:

- **Portrait** -- a desk scene: laptop screen upright with readable UI, a vase
  standing vertically with flowers up, the table surface horizontal, a folder
  lying flat. Colours natural (orange flowers orange, blue folder blue, white
  vase white). No shearing; straight edges remain straight. Aspect 0.750.
- **Landscape** -- a room: chair backs vertical with parallel vertical slats,
  a wall-mounted shelf horizontal, laptop upright, table horizontal. Colours
  natural. No shearing. Aspect 1.333.
- **Auto-rotate on** -- upright, though motion-blurred because the phone was
  being turned during capture.

The first two were captured with auto-rotate **locked to portrait**, which is
the condition that originally failed, so success criteria 1, 2 and 3 are all
satisfied under that setting.

## 28. Backend pipeline verification

Unmodified FastAPI backend, real phone frames:

| Check | Result |
|---|---|
| `/health` | `midas: loaded`, `device: cuda`, `video_stream_locked: false` |
| Frames received | 1636+ during this milestone |
| Depth shape | **[480, 640]** -- i.e. 640x480 landscape, matching the landscape input |
| Depth validity | finite, no NaN, no Inf, **256 distinct values** |
| Depth orientation | preserved; near/bright at the laptop screen and foreground table, far/dark at the back wall |
| Uplink rate | **4.70 fps** (limit 5.0, unchanged) |
| GPU memory | **1248 MiB** -- identical to Milestone 3, no growth |
| GPU utilisation / temp | 75% / 63 C |
| Unit tests | **7 tests, 0 failures, 0 errors** |

## 29. Wi-Fi blocked during this milestone (environmental)

Partway through, the phone could no longer reach the laptop over Wi-Fi.
Measured:

- phone -> gateway: **OK**; laptop -> gateway: **OK**
- phone <-> laptop: **100% packet loss, both directions**
- laptop ARP entry for the phone: **FAILED**, while the gateway is `REACHABLE`
- both still associated to the **same access point** (identical BSSID and
  SSID, redacted here), and the same IPs as Milestone 3 (laptop .106,
  phone .103)

A host firewall cannot break ARP, and neither IP changed, so this is **layer-2
AP/client isolation on the router**, enabled at some point after Milestone 3.
It is an environmental change, not a regression in this code, and no network
or firewall configuration was altered in response.

To finish the orientation work -- which is transport-independent -- the test
traffic was carried over USB with `adb reverse tcp:8000 tcp:8000`, and the
app's host field set to `127.0.0.1`. **Wi-Fi streaming itself was proven in
Milestone 3 and was not re-proven here.** The app's host was restored to the
LAN address afterwards.

## 30. Known limitations after Milestone 4

1. **Wi-Fi is currently blocked by AP client isolation** (section 29). It must
   be disabled on the router before wireless streaming works again.
2. The diagnostic logging is deliberately **left in**. It is change-triggered,
   not per frame, and it is what made this root cause provable; removing it
   would make the next orientation question unanswerable.
3. **180-degree and reverse-landscape cases were not physically tested.** Only
   `ROTATION_0` and `ROTATION_90` occurred during the session. The mapping for
   `ROTATION_180` and `ROTATION_270` is the official one but remains
   **unverified on hardware**.
4. A frame already in flight when the orientation changes may still carry the
   previous rotation. Harmless at 5 fps, but it means a single frame around a
   turn can be sideways.
5. The rotation still costs a **decode/rotate/re-encode** per frame whenever
   `rotationDegrees != 0` -- i.e. in portrait. In landscape it is now free.
6. The unexplained single disconnect from Milestone 3 was not reproduced and
   remains unexplained.
7. Streaming still stops when the app is backgrounded (no foreground service).

---

# Milestone 5 — direct Wi-Fi streaming validation

**Date:** 25 November 2026. **Branch:** `phase-4-android`, baseline `e3fff3b`.
**Device:** Pixel 7 Pro, Android 16. **No USB forwarding was used.**

Milestone 4's orientation tests had to run over `adb reverse` because the
router had enabled AP client isolation. This milestone re-establishes and
independently verifies **direct Wi-Fi** streaming, with USB used only for
device control (install, launch, typing the address, reading logcat).

## 31. What was already verified before this milestone

Carried forward, not re-proven here: APK build and install, camera permission
flow, the binary-JPEG protocol, ack handling, graceful disconnect, the
stride-correct YUV conversion, and orientation correctness for all four
rotation buckets (Milestones 2-4).

## 32. Newly verified in Milestone 5

### AP client isolation is gone

| Probe | Milestone 4 | Milestone 5 |
|---|---|---|
| laptop -> phone ICMP | 100% loss | **0% loss** |
| laptop ARP entry for the phone | `FAILED` | **resolved** to the phone's MAC |
| phone -> laptop `GET /health` | not possible | **HTTP 200** |

The resolved MAC matched the address recorded in Milestone 3, so this is
the same handset. The address itself is redacted: it identifies a personal
device and is not needed to follow the argument.
No router, firewall or network setting was changed by this project; the
isolation was lifted externally.

### The laptop's IP had changed

**`192.168.1.106` -> `192.168.1.107`** (DHCP). The phone stayed at
`192.168.1.103`. Any test reusing the old address would have failed with
`EHOSTUNREACH` and looked like an application fault. The app's stored host was
also still `127.0.0.1` from the Milestone 4 USB workaround.

### Direct Wi-Fi streaming, proven by the peer address

The decisive evidence is the backend's own connection log:

```
INFO:  192.168.1.103:45408 - "WebSocket /ws/video" [accepted]
PHONE CONNECTED
```

The peer is the phone's **Wi-Fi address**. Over an `adb reverse` tunnel the
peer appears as `127.0.0.1`, as it did throughout Milestone 4. Across the
whole session the backend logged **no loopback WebSocket peer at all**, and
`adb reverse --list` / `adb forward --list` were confirmed **empty** before,
during and after the test.

### Five-minute sustained test (direct Wi-Fi)

| Metric | Value |
|---|---|
| Duration | **301 s** |
| Frames received by the backend | **1402** (368 -> 1770) |
| Effective FPS | **4.66** (limit 5.0, unchanged) |
| Per-interval FPS | 4.52 - 4.70 across all ten intervals |
| **Stalls** | **0** |
| App counters | **sent 1984, acked 1983, dropped 0** |
| Disconnect / reconnect events | **0** app-side; backend saw 1 connect, **0 disconnects** |
| Invalid JPEGs rejected by the backend | **0** |
| JPEGs written | 168 files touched in the window (the backend reuses filenames after its counter restarts, so the file *count* stays flat while mtimes advance) |
| GPU utilisation | mean **83%**, range 75-92% |
| GPU memory | **1248 MiB, constant -- no leak** |
| GPU temperature | 60-63 C, no throttling |
| MiDaS | `loaded`, `device: cuda`, `inference_active: true` throughout |

The one-frame gap between sent and acked is simply the frame in flight.

Screen-sleep was suppressed for the test window (`svc power stayon usb`,
reverted afterwards). That is a *known, already-diagnosed* interruption from
Milestone 4, not an unexplained one; suppressing it lets the five minutes
measure network and stream stability rather than re-measuring the Android
doze timer.

### Physical frame inspection

A received JPEG was opened and examined: a glass dining table with a pink
basket of bananas, a spectacle case, wooden chairs and a bamboo mat.

- **Orientation** upright -- chair slats vertical, table horizontal. 480x640
  portrait, matching `physicalBucket=ROTATION_0`.
- **Colours** correct -- yellow bananas, pink basket, brown wood, white wall.
  A U/V swap would not survive this.
- **No shearing** -- chair slats straight and parallel.
- **No corruption** -- clean decode, full dynamic range, 68.7% bright pixels.

### MiDaS verification

| Check | Result |
|---|---|
| `/health` | `midas: loaded`, `device: cuda`, `depth_available: true` |
| `/latest-depth` | `shape [640, 480]`, min 340.69, max 2372.57 |
| `/latest-depth-image` | HTTP 200, PNG 480x640 8-bit grayscale |
| Finite values | yes -- 0 NaN, 0 Inf |
| Distinct depth values | **256** |
| RGB / depth orientation | **agree**, dimensions identical (480x640) |

Visually the depth reproduces the scene: nearest at the laptop in the
foreground, receding to the far table and background, with the diagonal
boundary matching the laptop screen edge in the RGB.

## 33. Failed tests

None. Every test attempted in this milestone passed.

## 34. Environmental limitations observed

1. **The laptop IP is DHCP-assigned and moved between milestones.** It must be
   re-checked before every session; the app has no discovery client.
2. **AP client isolation can reappear.** It blocked Milestone 4 entirely and
   cleared without any action from this project, so it is outside our control
   and must be re-verified each session (`ping` plus a phone-side `/health`).
3. `ufw` is active; its rules were never read (needs `sudo`). Port 8000 is
   demonstrably reachable from the phone, which is the behaviour that matters.

## 35. Remaining defects

1. **Streaming stops when the screen sleeps** (Activity pauses, CameraX
   unbinds). Worked around for the test; a foreground service and wake lock
   are the real fix.
2. **Bucket-boundary flapping at ~45 degrees** between orientation buckets;
   hysteresis would fix it.
3. **No UDP discovery client**, so the backend IP must be typed in by hand
   after every DHCP change. The backend responder already exists and is unused.
4. The app's stored host persists across reinstalls and silently goes stale
   when the laptop IP changes -- the failure then looks like a bug rather than
   a configuration drift.
5. Portrait orientation still costs a JPEG decode/rotate/re-encode per frame.

## 36. Evidence

Kept **outside** the public repository, at
`FYP-data/phase4_evidence/milestone5_wifi_20261125/`: the inspected RGB frame,
the paired RGB/depth pair, the depth PNG and colour-mapped render, the app
counter capture, and the raw five-minute log. `backend/uploads/` and
`backend/depth/output/` remain gitignored with zero tracked files, so no
photographs of the room enter Git.

---

# Phase 4B Milestone 1 — orientation hysteresis at bucket boundaries

**Date:** 25-26 November 2026. **Branch:** `phase-4-android`, baseline `0faf8c9`.
**Device:** Pixel 7 Pro, Android 16, CameraX 1.5.0.

**ACCEPTED WITH A KNOWN LIMITATION.** Two of the four orientation boundaries
were physically verified; two were not. This section says which, and does not
describe the four boundaries as fully validated.

## 37. The defect

Milestone 4's gate suppressed only *repeats*:

```
if (bucket != lastOrientationBucket) { apply() }
```

An A->B->A->B alternation passes that test on every sample, so a phone held
astride a boundary rewrote `targetRotation` continuously. That decides
`rotationDegrees`, which decides whether the JPEG is 480x640 or 640x480, so
consecutive frames in one stream could differ in aspect ratio and MiDaS (and
later `depth_to_scan`) would inherit the flip. Measured on hardware at
**physical 43-46 degrees**.

## 38. Implementation

`OrientationStabiliser` is a small, deterministic state machine requiring
**three consecutive agreeing samples** before the accepted orientation
changes:

- the first valid sample is accepted immediately (otherwise the camera would
  sit on CameraX's display-derived default, which is the Milestone 3 defect);
- `ORIENTATION_UNKNOWN` (-1) is discarded and never counted -- it is what the
  sensor reports with the device lying flat;
- a sample agreeing with the current orientation cancels any pending
  candidate, which is precisely what makes an alternation stable;
- a non-null return means "changed", so a duplicate can never be emitted;
- the threshold is configurable (`DEFAULT_SAMPLES_TO_CHANGE = 3`).

It counts **samples, not milliseconds**: sample counting is deterministic and
testable, whereas a wall-clock delay would make the tests timing-dependent.

The class carries no Android imports, so the whole decision is exercised in
plain JVM tests. The four-bucket mapping was **moved, not rewritten** --
`MainActivity.surfaceRotationFor` now delegates to it, so the two cannot
drift -- and a `check()` at camera-bind time asserts the redeclared
`ROTATION_*` constants still equal `android.view.Surface`'s.

`rotationDegrees` is still applied exactly once, in pixels, where it always
was. There is exactly one `targetRotation` assignment in the codebase.

## 39. Automated verification

`./gradlew testDebugUnitTest` -> **27 tests, 0 failures, 0 errors**
(`OrientationStabiliserTest` 20, `YuvConverterTest` 6, `ExampleUnitTest` 1).
`./gradlew assembleDebug` -> **BUILD SUCCESSFUL, 0 warnings.**

The 20 new tests assert the **sequence of emitted changes** over a stream of
samples, not per-angle mapping: the defect was a wrong decision over time,
which per-angle assertions cannot catch. One test reproduces the OLD gate and
asserts it flips 11 times where the stabiliser emits 1, so the suite cannot
quietly become vacuous.

## 40. Physical tests that WERE completed

A temporary diagnostic build (logging every valid sample, its bucket, the
pending candidate and its count) was used to make the state machine
observable, then **completely removed**; the rebuilt APK is bit-for-bit
identical to the pre-diagnostic one.

Measured accelerometer sampling period: **200.00 ms** (`dumpsys
sensorservice`). Note `OrientationEventListener` delivers *on change*, not at
a fixed rate, so three samples arrive faster than 3 x 200 ms during motion.

| Boundary | Status | Evidence |
|---|---|---|
| **45 deg** | **VERIFIED** | crossed 3x, each `1/3 -> 2/3 -> ACCEPTED`, both directions |
| **315 deg** | **VERIFIED** | crossed 2x, each `1/3 -> 2/3 -> ACCEPTED`, both directions |

Five accepted transitions in total, each preceded by exactly one `1/3` and
one `2/3` sample. **Settle times: 241, 274, 273, 273, 273 ms** (mean 267 ms,
max 274 ms) -- comfortably inside the one-second target.

Anti-flapping evidence: a 30-second hold at **316-324 degrees**, 91 samples,
produced **zero** candidate activity and **zero** accepted transitions. Across
roughly 700 logged samples the counter reached `1/3` five times and `2/3`
five times -- once per genuine crossing, never otherwise.

No streaming regression: direct Wi-Fi throughout (backend peer was the
phone's LAN address, never loopback), 4.62 fps against the unchanged 5.0
limit, `adb reverse`/`forward` empty before, during and after. RGB and depth
agreed exactly (480x640 both, finite, 256 distinct values). Inspected frames
were upright with natural colours and no shearing.

## 41. Physical tests NOT completed -- the accepted limitation

1. **The 135 deg and 225 deg boundaries remain PHYSICALLY UNVERIFIED.** Both
   require passing through upside-down; the `ROTATION_180` bucket was never
   entered in any test window. They are covered by unit tests only, which is
   weaker evidence and is not treated as equivalent.
2. **Sustained diagonal-boundary jitter testing was not completed.** The
   verified crossings were observed *in transit* during deliberate rotations.
   The closest sustained evidence is the 316-324 degree hold, which sits
   beside the 315 boundary without straddling it. No window captured a phone
   held steady *on* a boundary with the reading oscillating across it.
3. **No JPEG was inspected while the phone was held at a true diagonal.** The
   four "hold" captures measured only 2.0-3.5 degrees off-cardinal, which
   proves the phone was cardinal, not diagonal.

**This milestone is accepted with those limitations.** The hysteresis is
proven correct in simulation for all four boundaries and on hardware for two
of them.

## 42. Other limitations carried forward

- A frame already in flight when the orientation changes still carries the
  previous rotation -- unchanged by this work, harmless at 5 fps.
- One unexplained `websocket failure: timeout` during testing, auto-recovered
  in ~2 s by the existing reconnect path.
- Settle time varies with rotation speed, because the listener is
  change-driven; 267 ms was measured during deliberate turns.
- Screen-sleep still stops streaming, and there is still no UDP discovery
  client. Both remain open by design.

---

# Phase 4B Milestone 2 — camera metadata and float32 depth

**Date:** 26-27 November 2026. **Branch:** `phase-4-android`, baseline `bf86c9e`.
**Device:** Pixel 7 Pro, Android 16, CameraX 1.5.0. **Status:** implemented,
physically tested, awaiting acceptance review.

The Phase 4B audit found that the live phone path back-projected depth through
**fabricated** intrinsics (`fx = fy = 500`, `cx = 40`, `cy = 30` in
`depth_to_pointcloud.py`), discarded the float depth at the HTTP boundary, and
had no way to tell which RGB frame a depth map came from. This milestone fixes
the first and third and makes the second available. The full wire contract is
in [`API.md`](API.md); this section records provenance, verification and
limitations.

## 43. What changed

| File | Change |
|---|---|
| `android/.../CameraIntrinsics.kt` | **new** -- pure-Kotlin intrinsics with scaling, rotation and provenance |
| `android/.../CameraIntrinsicsTest.kt` | **new** -- 17 JVM tests |
| `android/.../MainActivity.kt` | reads real Camera2 characteristics; sends one metadata message before each JPEG |
| `backend/api/main.py` | accepts metadata; keeps float32 depth; two new endpoints; three association fixes (section 47); +179 / -6 lines |

Four of the six deleted backend lines are whitespace-only. The other two are
the `global` declaration of the inference worker (extended) and
`receive_bytes()` (replaced by a dispatching `receive()`).

**The existing protocol was extended, not versioned.** There is no
`/ws/video/v2`. `/ws/video` now also accepts an optional JSON text message
before each binary JPEG, and a client that sends binary only behaves exactly
as before.

Unchanged: `/latest-depth-image` (its PNG writer is byte-identical to
baseline), the depth algorithm, ROS 2, Nav2, and Phases 1-3.

## 44. Camera calibration -- genuine hardware values

### 44.1 Source

The Pixel 7 Pro populates `LENS_INTRINSIC_CALIBRATION`, which the Camera2
specification makes **optional**. These are therefore genuine device
calibration values. The app logged, at camera bind:

```
intrinsics CALIBRATED  source=LENS_INTRINSIC_CALIBRATION
```

The `FOCAL_LENGTH+SENSOR_SIZE` fallback and the `unavailable` path exist in the
code but **were not exercised on this device** -- every number below is
hardware calibration, none is a fallback estimate.

### 44.2 Original values, in active-array pixels

| | Value |
|---|---|
| Reference array (`SENSOR_INFO_ACTIVE_ARRAY_SIZE`) | **4080 x 3072** |
| `fx` | 2798.407470703125 |
| `fy` | 2798.407470703125 |
| `cx` | 2027.28955078125 |
| `cy` | 1548.5643310546875 |
| `LENS_DISTORTION` | `[0.12367305159568787, -0.18618865311145782, 0.11130569875240326, 0.0, 0.0]` |

`cx` sits about 12 px off the geometric centre (2039.5); a fabricated matrix
would typically be exactly centred. `fx == fy` exactly, i.e. square pixels.

The distortion array is in Camera2's order **`[k1, k2, k3, p1, p2]`** (three
radial, two tangential). Here both tangential terms are zero.

### 44.3 Resolution scaling

The transmitted frames come from ImageAnalysis at 640 x 480, not the 4080 x 3072
array. `CameraIntrinsics.scaledTo()` applies **independent** factors:

```
sx = 640 / 4080 = 0.156863        sy = 480 / 3072 = 0.156250
```

Forwarding the array-pixel matrix unscaled would overstate `fx` by about 6.4x;
the transmitted value is 6.4x smaller, confirming the scaling is applied.

### 44.4 Crop handling -- NOT implemented

The active array (4080 / 3072 = 1.3281) and the analysis stream
(640 / 480 = 1.3333) differ in aspect ratio by **0.39%**, so CameraX must crop
the sensor slightly to produce 4:3. **The code does not model that crop.** It
scales each axis independently instead of applying one uniform scale plus a
crop offset, and it does not read `SCALER_CROP_REGION` or any capture-result
crop.

The evidence that this matters is internal to the data: the sensor reports
square pixels (`fx == fy`), yet the transmitted matrix has
`fx / fy = 0.99609` -- **exactly** the aspect mismatch. That non-squareness is
an artefact of independent scaling, not a property of the camera.

If the actual crop is the obvious one -- full width kept, height centre-cropped
from 3072 to 3060 rows -- the transmitted values compare as follows:

| | transmitted | centred-crop model | difference |
|---|---|---|---|
| `fx` | 437.2512 | 438.9659 | **-1.71 px (-0.39%)** |
| `fy` | 438.9659 | 438.9659 | 0 |
| `cx` | 237.0368 | 237.0291 | +0.008 px |
| `cy` | 318.0062 | 318.0062 | 0 |

This crop geometry is **inferred, not measured**: the real crop region was not
read from the device. The error is small, but it is systematic.

### 44.5 Rotation

The JPEG is rotated by `imageInfo.rotationDegrees` before transmission, so the
matrix is rotated to match. For 90 degrees, axes swap:

```
fx' = fy     fy' = fx     cx' = (H - 1) - cy     cy' = cx     (W', H') = (H, W)
```

180 and 270 are handled likewise and covered by tests. Pixel convention is
`u` right, `v` down, origin at the top-left of the delivered image.

### 44.6 Final transmitted calibration -- upright portrait, 480 x 640

| | Value |
|---|---|
| `w x h` | 480 x 640 |
| `fx` | 437.2511672973633 |
| `fy` | 438.9658777573529 |
| `cx` | 237.03682327270508 |
| `cy` | 318.0062040441176 |
| `distortion` | passed through unchanged |
| `intrinsics_source` | `LENS_INTRINSIC_CALIBRATION` |

All four values matched an independent hand computation to better than
1e-6 px on the physical device.

### 44.7 Provenance limitations

1. **Crop not modelled** (44.4) -- `fx` is likely 0.39% low.
2. **Reference array assumed.** The code scales from
   `SENSOR_INFO_ACTIVE_ARRAY_SIZE`. It does not read
   `SENSOR_INFO_PRE_CORRECTION_ACTIVE_ARRAY_SIZE` or the distortion-correction
   mode, so if the calibration is expressed relative to a different array on
   this device, the offset is not accounted for. Not verified either way.
3. **Distortion is not rotated.** Radial terms are rotation-invariant, but
   tangential terms change under a 90-degree rotation. They are zero on this
   device, so there is no numeric effect here -- on a device with non-zero
   `p1`/`p2` the transmitted values would be wrong for rotated frames.
4. **Distortion is applied nowhere.** It is transmitted only.
5. **Order differs from OpenCV.** Camera2 gives `[k1, k2, k3, p1, p2]`;
   OpenCV expects `[k1, k2, p1, p2, k3]`.
6. **The fallback picks the first listed focal length**
   (`LENS_INFO_AVAILABLE_FOCAL_LENGTHS.firstOrNull()`). Not exercised here,
   but on a multi-focal camera that need not be the active one.

## 45. Float32 depth preservation

`GET /latest-depth-raw` serves the unmodified model output as a NumPy `.npy`
payload: **float32**, shape `(height, width)` of the delivered frame,
C / row-major. Headers name the source frame (`X-Frame-Seq`,
`X-Frame-Timestamp-Ns`) and the units (`X-Depth-Units:
midas-inverse-relative-unscaled`).

**The values are MiDaS relative inverse depth, not metric distance.** Larger
means nearer; the scale is arbitrary and may differ between frames. Real
intrinsics make a back-projected cloud correctly *shaped*, but its scale
remains unknown. Metric calibration was explicitly out of scope.

On the physical device the float array carried **305,774** distinct values,
against **256** in the 8-bit preview.

`/latest-depth-image` is unchanged and remains for visualisation and for the
ROS depth bridge. Its PNG is per-frame `NORM_MINMAX`, which is why it cannot
be used for geometry; the regression confirmed it is byte-for-byte that
normalisation of the float array from the same frame (max absolute
difference 0).

**No backend inference timestamp is recorded.** The only timestamp is the
phone's capture `ts_ns` -- a device-local monotonic counter whose timebase is
not transmitted. Capture-to-depth latency is not measurable from current
outputs; only the frame lag is (`seq_lag` in `/latest-frame-meta`, observed
at 0-2 frames, because inference is latest-frame-wins).

## 46. Test results -- reconciled

The M2 physical-test report stated **61** passing tests while enumerating
suites that sum to 44. **The 61 was an arithmetic error in that report**;
there are no further suites. It appeared only in the chat report and in no
committed document. Fresh run, results directory cleared first:

```
cd android && ./gradlew testDebugUnitTest --rerun-tasks
```

| Suite | Tests | Failures | Errors | Skipped |
|---|---|---|---|---|
| `CameraIntrinsicsTest` | 17 | 0 | 0 | 0 |
| `OrientationStabiliserTest` | 20 | 0 | 0 | 0 |
| `YuvConverterTest` | 6 | 0 | 0 | 0 |
| `ExampleUnitTest` | 1 | 0 | 0 | 0 |
| **Total** | **44** | **0** | **0** | **0** |

Other test assets in the repository, and why they are not in that total:

| Asset | Status |
|---|---|
| `androidTest/ExampleInstrumentedTest.kt` | 1 instrumented test; needs a device; not run in M2 |
| Backend pytest | none exist |
| `scripts/test_backend_pipeline.py` | legacy smoke client; needs a `video_frames/` directory that is absent, so it cannot run as-is |
| ROS 2 colcon tests | 17 files; untouched by M2; not re-run |

`./gradlew assembleDebug`: BUILD SUCCESSFUL, 0 warnings. ~~The rebuilt APK is
bit-identical (`17425475...`) to the one physically tested.~~ **Corrected in
section 49:** that build reported `assembleDebug UP-TO-DATE`, so it re-hashed
the already-installed file rather than rebuilding it; it did not demonstrate
a reproducible build.

### Integration regression (ad-hoc, not a test suite)

A scripted WebSocket client exercised the backend against frozen state:
**26 of 26 checks passed** -- legacy binary-only frames, metadata pairing and
`seq` echo, `X-Frame-Seq`/`ts_ns` consistency, float32 dtype/shape/order/
finiteness, min/max agreement with `/latest-depth`, preview unchanged, and
survival of malformed metadata.

## 47. Defects found during closeout -- fixed before commit

Closeout testing found three metadata-association defects. The 26/26
regression had passed while all three were present, because it did not
exercise these paths. All three were fixed in `backend/api/main.py` before
M2 was committed.

| # | Defect | Fix | Verification |
|---|---|---|---|
| 1 | An undecodable JPEG left its metadata pending; it attached to the next valid frame | invalid-JPEG branch discards the metadata | **Reproduced, then fixed:** `seq 7001` leak -> `seq null` |
| 2 | Pending metadata was a module global and survived across connections | now a local of each connection | **Reproduced, then fixed:** client A's `seq 8001` on client B's frame -> `seq null` |
| 3 | Depth `.npy` was published just after the lock that published its metadata | serialised outside the lock, assigned with `depth_meta` inside it | **Structural only:** never reproduced (0/739 before, 0/616 after) |

After the fixes the full regression still passes 26/26.

The M2 physical-test report had claimed that a frame "can never inherit a
previous frame's label". Defects 1 and 2 showed that claim was false when it
was made; with the fixes it now holds for the paths tested here.

A related caveat, **not** fixed because it is app-side and outside this scope:
`seq` is scoped to one `MainActivity` instance and restarts at 1 whenever the
activity is recreated, because the manifest declares no `configChanges`. It is
not a globally unique frame ID; `(seq, ts_ns)` is.

## 48. Remaining limitations

*Superseded by section 50, which keeps this list and adds to it.*

1. Depth is **relative, not metric**. No calibration against known distances.
2. Crop not modelled; `fx` likely 0.39% low (44.4).
3. ROS 2 still consumes the 8-bit preview; nothing downstream uses the
   intrinsics or the float depth yet.
4. Distortion transmitted but not applied, and not rotated.
5. No camera pose -- frames still cannot be fused into one coordinate system.
6. Capture timebase not transmitted; no backend inference timestamp.
7. `seq` restarts when the activity is recreated (section 47).

## 49. Commit review: a fourth association defect, fixed separately

Reviewing the M2 commit `d2376a9` before pushing found one more defect of
the same kind as section 47. `d2376a9` is kept as it is; the fix is a
separate commit on top of it.

### The race

In `video_websocket`, the accepted frame was published in two steps:

```python
latest_meta = frame_meta          # outside the lock
latest_frame = frame
with processing_lock:
    pending_frame = frame.copy()
```

The inference worker reads `pending_frame` and `latest_meta` **together**
under `processing_lock`. If frame *k-1* was still pending when frame *k*
arrived, and the worker took the lock between those two statements, it
received frame *k-1*'s pixels with frame *k*'s metadata. The depth map was
then served with the wrong `X-Frame-Seq` and `X-Frame-Timestamp-Ns`, one
frame late. That is exactly the error M2 exists to make detectable.

### The fix

`latest_meta = frame_meta` moved inside the existing `with processing_lock:`
block, next to `pending_frame = frame.copy()`. No new lock, no nested
acquisition, and latest-frame-wins is unchanged: `pending_frame` is still
overwritten, never queued. `pending_meta` stays a local of each connection,
and the invalid-JPEG path still discards it.

`/health` previously read `latest_meta`, `depth_meta` and `latest_depth_npy`
outside the lock it already takes. It now reads them inside, so
`latest_seq` and `depth_seq` describe one instant.

### Why the earlier tests passed

The window is a few Python statements wide. Neither the 26-check regression
nor the 87-second Wi-Fi run on the Pixel 7 Pro could make the worker take the
lock at precisely that point. Passing those tests showed the race was rare;
it did not show the race was absent.

### Focused checks: `scripts/check_frame_metadata.py`

This is a standalone script, **not** a pytest suite. pytest and httpx are not
installed in the backend venv, and no dependency was added. It imports
`backend/api/main.py` in-process, loading MiDaS as the server does, and
drives the real `video_websocket` coroutine with a scripted fake WebSocket.
Runtime output is redirected to a temporary directory.

To make the race deterministic, it holds the worker inside `predict()` so
frames stay pending. It also wraps `processing_lock` in a probe that, at
every acquisition by the socket handler, records what a worker taking the
lock at that instant would read.

| Check | On `d2376a9` | After the fix |
|---|---|---|
| 1. pending pixels and metadata belong to the same frame | **FAIL**: 8 mismatches, pixels of frame *k* with the metadata of *k*+1 (and frame 5 with the legacy frame's `None`) | PASS: 0 of 17 |
| 2. invalid JPEG does not label the next frame | PASS | PASS |
| 3. new connection inherits no pending metadata | PASS | PASS |
| 4. legacy binary-only client (acks, `seq` null, counter) | PASS | PASS |
| 5. `.npy` is float32 with the source frame's shape; `X-Frame-Seq` and `X-Frame-Timestamp-Ns` name that frame; 8-bit preview still served | PASS | PASS |
| **Total** | **19/20, exit 1** | **20/20, exit 0** |

Checks 2 and 3 already passed on `d2376a9`, because those defects were fixed
in that commit (section 47). Here they are regression guards, not
before-and-after evidence.

```
venv/bin/python scripts/check_frame_metadata.py                     # 20/20
venv/bin/python scripts/check_frame_metadata.py --main <d2376a9 copy> # 19/20
```

### Other verification after the fix

| Suite | Command | Result |
|---|---|---|
| Integration regression, 26 checks (ad-hoc script kept outside the repo, against a dedicated `uvicorn` on 127.0.0.1:8000) | `venv/bin/python regress.py` | **26/26** |
| Android JVM tests | `cd android && ./gradlew testDebugUnitTest --rerun-tasks` | **44/44**: CameraIntrinsics 17, OrientationStabiliser 20, YuvConverter 6, Example 1 |
| Debug build | `./gradlew assembleDebug --rerun-tasks` | BUILD SUCCESSFUL, 0 warnings |

These are three separate suites; their counts are not added together.
Android source is unchanged by this fix.

**APK hash correction.** The APK physically tested over Wi-Fi was
`17425475...`, installed and verified on the device. Two forced rebuilds
from the unchanged committed source today both produced `f74467d2...`. No
Android source file was edited after that install, so the difference comes
from the build, not the code. The tested APK was not kept, so the byte-level
cause was not identified. Do not cite APK hashes from different builds as
evidence that they are the same build.

### Not affected by the fix

Android code, the transmitted intrinsics (the Pixel 7 Pro's genuine
`LENS_INTRINSIC_CALIBRATION` values in section 44), the `seq` and `ts_ns`
semantics, the float32 payload, `/latest-depth-image`, the depth algorithm,
ROS 2, Nav2 and Phases 1-3. No physical retest was run for this change,
because it touches only backend thread ordering, which the in-process check
exercises deterministically.

### Protocol wording

The protocol is **not versioned**: there is no version field in the
metadata and no `/ws/video/v2`. `/ws/video` accepts an optional JSON text
message before each binary JPEG, and binary-only clients are unaffected. The
committed docs already said so (section 43, `docs/API.md`); only a chat
report had called it versioned.

## 50. Remaining limitations (current list; supersedes section 48)

1. **Depth is MiDaS relative inverse depth, not metric.** Larger means
   nearer; the scale is unknown and can change between frames. Nothing
   converts it to metres.
2. **Crop correction is incomplete.** The scaling from the sensor array to
   the 640x480 analysis image does not model the crop CameraX applies when
   the aspect ratios differ, so `fx` is likely about 0.39% low (section 44).
3. **Distortion is transmitted but not applied.** Nothing in the project
   undistorts frames or depth. The order is Camera2's `[k1, k2, k3, p1, p2]`,
   not OpenCV's.
4. **Distortion is not transformed for rotated images.** The intrinsics are
   rotated with the JPEG, but the tangential terms `p1` and `p2` are sent in
   sensor orientation. For a 90° or 270° frame they would need swapping and
   sign changes before use.
5. **The capture clock source must stay explicit.** `ts_ns` is the device's
   sensor timestamp. `SENSOR_INFO_TIMESTAMP_SOURCE` is not read or sent, so
   whether that is `REALTIME` or `UNKNOWN` is not recorded. It is not
   wall-clock time and cannot be compared with the laptop's clock. The
   backend records no inference timestamp.
6. **`seq` restarts at 1 when the Android activity is recreated.** The
   manifest declares no `configChanges`. Only `(seq, ts_ns)` together
   identify a frame.
7. **ROS 2 still consumes the 8-bit preview.** Nothing downstream uses the
   float depth or the intrinsics yet.
8. No camera pose is transmitted, so frames cannot yet be fused into one
   coordinate system.
9. The 135° and 225° hysteresis boundaries are tested on the JVM only, not
   physically.
