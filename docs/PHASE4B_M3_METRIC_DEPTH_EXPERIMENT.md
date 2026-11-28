# Phase 4B Milestone 3 -- Metric depth calibration experiment

**Result:** a known-distance calibration of raw MiDaS output gives about
**5 cm median error and 13% mean relative error on held-out points in the
same capture**, over 0.29-1.16 m, in one table-top scene. The same
calibration **degrades to 20-23% mean relative error** after a lighting
change or one added object, with the camera unmoved. Even refitting in every
frame from three known points does not do better than about 12-13%.

**Verdict:**
- **Yes:** stable over frames within one capture (B).
- **Only roughly:** usable for the tested capture only (A).
- **No:** it does not generalise to changed conditions (C).
- **Overall: not accurate enough for metric reconstruction (D).**

**Scope.** These findings apply only to the conditions tested: one indoor
table-top scene; six points at optical-axis depths of 0.29-1.16 m; one Pixel
7 Pro in portrait at 480x640; MiDaS DPT-Hybrid 384 as currently deployed;
indoor artificial lighting; and one set of tape measurements. They are not
evidence about other scenes, longer ranges, other devices or other depth
models. In particular, accuracy beyond 1.2 m was not measured.

Date: 27-28 Nov 2026. Branch `phase-4-android` at `54ae36a`; no production
code changed. Raw evidence (frames, float32 depth, metadata, scripts, full
outputs) is kept outside the repository in
`~/FYP-data/phase4_evidence/phase4b_m3_metric_20261127/`.

## Success criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Multiple real-world distances measured | Met: 6 points, 0.32-1.30 m tape range |
| 2 | Raw float32 depth samples collected | Met: 70 frames in run 2 (A 30, B 20, C 20), plus 80 in run 1 |
| 3 | RGB/depth pairing verified | Met: exact by construction; served `.npy` equal to inference output for every frame |
| 4 | Calibration model evaluated | Met: scale-only, affine, robust affine, per-frame oracle |
| 5 | Held-out validation performed | Met: split fixed before distances were known |
| 6 | Accuracy metrics calculated | Met (section F/G) |
| 7 | Generalisation limitations documented | Met (sections H, I) |
| 8 | Evidence outside the public repository | Met |

## Depth semantics

- Model: MiDaS DPT-Hybrid 384 (`backend/depth/midas_processor.py`,
  unchanged). The checkpoint loads completely (368/368 tensors), despite
  `strict=False`.
- Output: float32 per pixel, bicubically upsampled to the 480x640 delivered
  frame; NaN/inf replaced by 0. Served by `GET /latest-depth-raw` as `.npy`.
  The 8-bit preview was not used.
- Meaning: **relative inverse depth -- larger is nearer**. MiDaS/DPT are trained
  with a scale-and-shift-invariant loss in disparity space (Ranftl et al.,
  *Towards Robust Monocular Depth Estimation*, TPAMI 2022; Ranftl,
  Bochkovskiy, Koltun, *Vision Transformers for Dense Prediction*, ICCV 2021),
  so `D ~ s*(1/Z) + t` with `s`, `t` unknown and free to vary per image. The
  calibration `1/Z = a*D + b` inverts that relation.

## Method

**Capture and pairing.** An experiment harness (`tools/capture_server.py`,
evidence directory) imported the unmodified `backend/api/main.py` and served
it on the normal port. The phone streamed over Wi-Fi only, with no USB and no
adb tunnels. The harness wraps `midas.predict` as a pure observer: it calls
the original, returns the identical array, and remembers `(input frame,
output)`. A frame is saved only when the published `latest_depth` **is** that
array. The saved RGB is therefore the exact pixels MiDaS consumed (lossless
PNG), and `depth_meta` (same locked publish, since `54ae36a`) is that frame's
metadata. `/latest-frame` was not used: it carries no `seq` and can change
mid-read. A synthetic check paired 5/5 encoded frames correctly.

**Camera stillness.** Each session is compared with the first frame of
session A using ORB features and a RANSAC similarity transform
(`tools/poscheck.py`). The limits were 6 px shift and |scale-1| <= 0.003.
These limits were validated on the earlier data: two known-still sessions
passed, and a known-moved session (16 px, scale 0.985) failed.

**Ground truth.** Tape range from the camera lens to six marked points,
straight line, 1 cm resolution, measured after sessions A-C. Range `R` is
converted to optical-axis depth `Z = R / sqrt(1 + x^2 + y^2)` with
`x = (u-cx)/fx`, `y = (v-cy)/fy` from the transmitted Pixel intrinsics. This
matters: ignoring the angle overstates `Z` by 2.7-19.8% at these points.

**Sampling.** Raw D at each point is the median of a 20x20 px box. The box
interiors are flat in D: p10-p90 spread 0.2-3.9% of the median.

**Models** (fitted in `w = 1/Z`, session A, calibration points only, all
frames pooled):
- S scale-only: `w = a*D`.
- F affine least squares: `w = a*D + b`.
- R affine Huber (IRLS, k = 1.345): `w = a*D + b`.
- Oracle per-frame affine: fitted in every frame on that frame's
  calibration points.

All fits require `a > 0` (monotonic). The split, **fit on points 1, 3, 5 and
validate on 2, 4, 6**, was fixed before any distance was received.

## A. Physical setup and measured distances

Pixel 7 Pro, rear main camera, portrait (`rotation_deg` 90, 480x640),
intrinsics `LENS_INTRINSIC_CALIBRATION` (fx 437.251, fy 438.966, cx 237.037,
cy 318.006). Phone propped still on a table facing a table-top scene and the
wall behind. Laptop: HP ZBook 15 G6 / Quadro T2000; MiDaS 148-204 ms per
frame.

| # | Point | Role | Tape range | Off-axis angle | Optical-axis Z |
|---|---|---|---|---|---|
| 1 | bottle label | cal | 0.32 m | 25.6 deg | 0.289 m |
| 2 | small white box | **val** | 0.64 m | 13.1 deg | 0.623 m |
| 3 | Vida-Z box | cal | 0.47 m | 22.8 deg | 0.433 m |
| 4 | plant pot (curved) | **val** | 0.55 m | 29.0 deg | 0.481 m |
| 5 | wall, left of window frame | cal | 1.22 m | 18.2 deg | 1.159 m |
| 6 | small picture frame on wall | **val** | 1.30 m | 33.4 deg | 1.085 m |

**Range covered: Z = 0.29-1.16 m.** Nothing beyond 1.2 m was measured, so no
claim is made there.

## B. Calibration sample collection

| Session | Condition | Frames | seq | Camera vs A |
|---|---|---|---|---|
| A | baseline | 30 | 2056-2086 | reference (0.0 px within session) |
| B | brighter lighting (+7% mean), light reflected in window glass, **and** a glasses case added | 20 | 2953-2972 | unmoved (<1.5 px, scale within 0.15%) |
| C | lighting restored (-5% vs A), glasses case kept, **helmet added** behind the bottle | 20 | 3369-3388 | about 2 px, scale +0.25% -- just over the scale limit |
| post | last frame after measuring | 1 | 4144 | 6.7 px sideways, scale -0.1% |

The C and post-measurement deviations are recorded rather than hidden. In
range terms, a +0.25% scale is under 3 mm at 1.2 m, and -0.1% is about 1 mm.
Both are below the 1 cm tape resolution, so the distances are treated as
valid for A, B and C. Every frame was an exact pair; maximum depth lag at
capture was 2 frames, which does not affect pairing.

B changed lighting and composition at the same time, so their effects cannot
be separated. C changes composition, with lighting close to A.

## C. Raw MiDaS depth statistics (session A)

| Point | Z | mean raw D | temporal CV |
|---|---|---|---|
| 1 bottle | 0.289 | 2210.1 | 1.60% |
| 3 Vida-Z | 0.433 | 1778.1 | 1.95% |
| 4 pot | 0.481 | 1571.8 | 2.16% |
| 2 small box | 0.623 | 1078.0 | 3.20% |
| 5 wall | 1.159 | 473.1 | 6.99% |
| 6 picture frame | 1.085 | 434.2 | 6.69% |

Correlation with `1/Z` over the six points: Pearson r = **0.975**, Spearman
rho = **0.943**. The rank is wrong in one place: MiDaS puts the picture frame
(6) behind the wall point (5), but by optical-axis Z it is 7 cm nearer. The
frame sits 33 deg off-axis, and the two points' D values (434 vs 473) differ
by less than their frame-to-frame spread. Raw D has no unit and cannot be
scored in metres.

## D/E. Calibration models and fitted parameters

| Model | a (m^-1 per unit D) | b (m^-1) |
|---|---|---|
| S scale-only | 1.4712e-3 | 0 |
| F affine LS | 1.4047e-3 | +0.1234 |
| R affine Huber | 1.4124e-3 | +0.1254 |

All have `a > 0` (monotonic) and `b > 0`. `1/Z` therefore stays positive for
every observed D: no non-physical predictions occurred. The robust fit is
within 0.6% (a) and 1.6% (b) of least squares, so there were no gross
outliers for it to suppress.

## F. Training accuracy (session A, calibration points 1, 3, 5; 90 samples)

| Model | MAE | RMSE | mean rel. error | median | max | bias |
|---|---|---|---|---|---|---|
| S | 11.8 cm | 17.7 cm | 14.3% | 5.0 cm | 46.1 cm | +8.4 cm |
| F | 6.3 cm | 8.5 cm | 9.8% | 4.7 cm | 24.4 cm | +2.8 cm |
| R | 6.1 cm | 8.1 cm | 9.6% | 4.8 cm | 23.4 cm | +2.4 cm |

## G. Held-out validation accuracy

Points 2, 4 and 6, session A, 90 samples:

| Model | MAE | RMSE | mean rel. error | median | max | bias |
|---|---|---|---|---|---|---|
| S | 18.5 cm | 28.9 cm | 19.3% | 4.9 cm | 66.7 cm | +14.9 cm |
| F | 11.7 cm | 17.2 cm | 13.2% | 5.2 cm | 41.1 cm | +7.3 cm |
| R | 11.5 cm | 16.7 cm | 13.2% | 5.5 cm | 40.0 cm | +6.7 cm |

Distance-wise, affine F (mean +- std over frames, cm). B and C use **A's**
parameters unchanged:

| Point | Role | Tape Z | A | B | C |
|---|---|---|---|---|---|
| 1 bottle | cal | 28.9 | 31.0 +- 0.5 | 35.4 +- 0.5 | 34.8 +- 0.3 |
| 3 Vida-Z | cal | 43.3 | 38.2 +- 0.7 | 36.9 +- 0.7 | 40.9 +- 0.4 |
| 4 pot | **val** | 48.1 | 42.9 +- 0.9 | 38.8 +- 0.8 | 47.0 +- 0.8 |
| 2 small box | **val** | 62.3 | 61.1 +- 1.8 | 70.1 +- 2.0 | 73.2 +- 1.4 |
| 6 picture frame | **val** | 108.5 | **136.8 +- 7.4** | 141.1 +- 5.5 | **168.6 +- 6.6** |
| 5 wall | cal | 115.9 | 127.3 +- 7.4 | 139.0 +- 6.3 | **159.9 +- 6.4** |

The scale-only model fails at the far end, predicting the wall at 144 cm
against 116 cm: the shift term `b` is needed. The worst point is the picture
frame, +28 cm (+26%) in A. Near points are within about 1-5 cm.

All conditions, all six points, A's parameters:

| Model | A all | B (lighting + case) | C (helmet) |
|---|---|---|---|
| S | MAE 15.1 cm, 16.8% | 22.0 cm, 27.1% | 32.1 cm, 33.6% |
| F | MAE 9.0 cm, 11.5% | 14.3 cm, 19.9% | 20.8 cm, 23.2% |
| R | MAE 8.8 cm, 11.4% | 13.9 cm, 19.5% | 20.3 cm, 22.8% |

**Per-frame oracle** (affine refitted in every frame on its own points 1, 3,
5; scored on 2, 4, 6): mean relative error 13.0% (A), 13.1% (B), 12.3% (C);
max 32 cm. This is the best possible with three perfect metric references per
frame. It is barely better than the fixed A calibration on A itself, so the
remaining error is **not** a per-image affine offset. It is local,
object-dependent error inside MiDaS: the pot is consistently 5 cm too near,
and the frame about 25 cm too far.

Leave-one-point-out (affine, five points, A): errors are +7.3, -1.5, -5.6,
-5.4, +5.4 and **+36.4 cm** for points 1-6. The picture frame is the outlier
in every analysis.

## H. Temporal consistency

Stationary camera, unchanged scene:
- Raw D temporal CV is 0.9-3.2% for objects at 0.3-0.6 m and **5-7% for
  the wall** (A, B, C).
- In metres, the affine prediction varies by +-0.3-2 cm at 0.3-0.6 m and
  +-5.5-7.4 cm at about 1.1 m.

Run 1 (two other stationary captures) agreed: 1.2-7.1% per surface, 3-4%
median per pixel.

Depth ordering was stable within each session. **One calibrated capture is
stable over frames; averaging frames reduces the jitter further.**

## I. Scene consistency

With the camera unmoved, raw D for **unchanged** surfaces changed between
sessions:

| Point | B/A | C/A |
|---|---|---|
| 1 bottle | 0.871 | 0.887 |
| 2 small box | 0.861 | 0.821 |
| 3 Vida-Z | 1.036 | 0.929 |
| 4 pot | **1.113** | 0.909 |
| 5 wall | 0.899 | **0.757** |
| 6 picture frame | 0.961 | 0.772 |

- In B, some surfaces rose by up to 11% while others fell by up to 14%. That
  is **not** a global rescale, so no single per-frame `(a, b)` can undo it.
- In C, a helmet placed beside (not in front of) the targets lowered every
  value by 7-24%, the wall most of all. The fit `D_C = 0.946*D_A - 86` shows
  a large shift change.
- Run 1 showed the same behaviour in a kitchen scene: unchanged surfaces
  shifted by up to +75% after a few centimetres of camera motion and a 7%
  lighting change (`D_B ~ 1.00*D_A + 62`).

**One calibration therefore does not transfer** to another capture of the
same scene once lighting or composition changes. It was not tested across
different rooms, but nothing here suggests it would transfer better.

## Task 8 -- intrinsics issues at the measured points

| Issue | Effect on Z (largest, at point 6) |
|---|---|
| fx about 0.39% low (crop not modelled) | 0.12% (0.13 cm) |
| radial distortion not applied | 0.80% (0.87 cm) |
| tangential distortion not rotated | none: this device reports p1 = p2 = 0 |
| range-to-axial conversion omitted | 19.8% -- **must** be applied |

The known intrinsics limitations are immaterial here, because they are
one to two orders of magnitude below MiDaS's own error. No intrinsics value
was altered.

## Limitations of this experiment

- One scene, six points, one set of tape measurements (no repeats), range
  0.29-1.16 m. Accuracy outside this range is unknown.
- Ground truth is about +-0.5 cm (0.4-1.6% of range). The lens-to-optical-
  centre offset (a few mm) was not modelled.
- Points 5 and 6 lie on the same wall, yet their Z differs by 7 cm. The
  camera faced the wall at an angle and the picture frame protrudes, so this
  is plausible, but measurement error at point 6 cannot be excluded. Without
  point 6, held-out error would be much lower. It is kept, because removing
  the worst point after seeing results would be cherry-picking.
- Session B changed two factors at once. The camera in C was just outside the
  scale limit (+0.25%), though below the tape resolution.
- Frames are correlated within a session, so `n` overstates independent
  evidence. Effectively there are 6 points and 3 conditions.

## J. Is metric depth sufficiently reliable?

| Option | Finding |
|---|---|
| A. Reliable for the tested scene only | **Partly.** In the capture it was fitted on: median about 5 cm, mean relative error 13% held-out, worst 41 cm, over 0.3-1.2 m. |
| B. Stable across frames in the same scene | **Yes.** Frame jitter is 1-2% near and 5-7% far; ordering is stable. |
| C. Generalisable to different conditions or scenes | **No.** Errors grow to 20-23% with the camera unmoved; raw D shifts non-uniformly by up to 24% (run 1: up to 75%). |
| D. Not sufficiently accurate for metric reconstruction | **Yes, this is the overall conclusion.** |

A 13-23% depth error, growing with distance and changing whenever the scene
changes, is not a sound basis for a metric occupancy grid. MiDaS output must
continue to be described as **relative depth** in the project documentation,
and must not be called metric.

## K. Recommended next step

Per-frame references alone would not fix this: even the oracle reached only
about 12-13%. The error is local to objects, not one scale and shift per
frame. Metric geometry therefore needs a **metric sensor source**, not a
better fit:

1. **ARCore** (recommended next milestone, as a feasibility study first).
   Visual-inertial tracking gives a metric 6-DoF pose and a sparse metric
   point cloud. On supported devices, the Depth API gives metric depth
   images. Options, in increasing ambition:
   - (a) use ARCore metric points to fit `(a, b)` per frame, accepting the
     roughly 12% residual measured here;
   - (b) use ARCore depth directly for the occupancy grid, with MiDaS only for
     densification or visualisation;
   - (c) use ARCore poses to fuse frames into one metric map.

   Before any code: confirm Pixel 7 Pro support for the Depth API, CPU and
   thermal cost alongside streaming, and how ARCore's camera session coexists
   with the current CameraX pipeline.
2. Keep the calibration harness and scripts. Any future metric source can be
   validated against tape measurements with the same split-and-score method.
3. Optional for the report: repeat with targets at 1.5-3 m and repeated tape
   readings, to bound the error at navigation-relevant ranges.

## Files

Evidence directory, not committed:
- `tools/capture_server.py` (observing harness), `tools/poscheck.py`,
  `tools/calibrate.py`, `tools/temporal_stability.py`,
  `tools/kitchen_analysis.py`, `tools/points_R2.json`
- `run2/ground_truth.json` (distances and the fixed split),
  `run2/calibration_results.txt` (full output)
- `run2/R2_{A,B,C,post}/` and the run 1 `captures/`: paired `_rgb.png`,
  `_depth.npy`, `_meta.json`

No production file, protocol, ROS 2, Nav2, or Phase 1-3 file was changed.
