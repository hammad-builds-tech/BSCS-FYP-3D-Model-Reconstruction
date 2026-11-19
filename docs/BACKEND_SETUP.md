# Backend setup (FastAPI + MiDaS DPT-Hybrid on the GPU)

Phase 0 result: the real DPT-Hybrid-384 model loads through
`backend/depth/midas_processor.py` and runs on the RTX 4050. This file
describes how to recreate that environment.

## Tested configuration (2026-11-16)

| Item | Version |
|---|---|
| OS | Ubuntu 26.04.1, ROS 2 Lyrical (not touched) |
| GPU / driver | RTX 4050 Laptop 6 GB, NVIDIA driver 595.99.02 |
| Python | 3.14.4 (system interpreter, used only to create the venv) |
| torch / torchvision | 2.15.0+cu132 / 0.29.2+cu132 |
| CUDA runtime / cuDNN | 13.2 / 9.26 (bundled in the pip wheels) |
| timm | 0.6.13 |
| fastapi / uvicorn | 0.163.1 / 0.54.0 |
| opencv-python-headless / numpy | 5.0.0.93 / 2.5.5 |

The full list of exact versions is in `backend/requirements.lock.txt`.

### Compatibility scope of the lock file

`backend/requirements.lock.txt` has been tested **only** with:

- **Linux x86_64** (Ubuntu 26.04.1)
- **Python 3.14.4**
- **NVIDIA RTX 4050 Laptop GPU** (driver 595.99.02)
- the **CUDA-enabled PyTorch** build: on Linux x86_64, `torch==2.15.0`
  from PyPI is the CUDA 13.2 build, and the lock file also pins its
  `nvidia-*` CUDA libraries

Other operating systems, CPU architectures, Python versions and GPUs are
**untested**. Several locked packages (torch, numpy, opencv and the
`nvidia-*` libraries) are built separately for each platform and Python
version, so the lock file may not install elsewhere at all. On any other
setup:

1. Install from `backend/requirements.txt`.
2. Run the GPU smoke test (section 3).
3. Save that setup's own lock file with `venv/bin/pip freeze`.

The pip wheels include the CUDA and cuDNN libraries, so no system CUDA
toolkit is needed. The NVIDIA driver must be version 580 or newer for
CUDA 13.x.

## 1. Create the virtual environment

The environment is isolated from system Python and from the ROS Python
packages. `venv/` is listed in `.gitignore`.

### Standard install (online, recommended)

Run these from the root of your clone:

```bash
python3 -m venv venv
venv/bin/pip install -r backend/requirements.lock.txt   # exact tested versions
```

Installing from the lock file pulls everything from PyPI, including the
CUDA-enabled `torch` wheel and its `nvidia-*` libraries. Do **not** add
`--index-url https://download.pytorch.org/whl/cpu`, and do not set an
equivalent `PIP_INDEX_URL`: either one would install the CPU-only
build. The smoke test in section 3 catches that case.

`backend/requirements.txt` is the looser alternative for platforms
outside the tested scope. It pins only torch, torchvision and timm, so
the other packages may resolve to newer versions.

The download is about 3 GB, mostly CUDA libraries, and the installed venv
is about 5.7 GB.

### Optional: resumable download on a slow network

pip throws away partial downloads when it is interrupted.
`scripts/fetch_wheels.sh`, which is committed in this repository, works
around that:

1. It asks pip which packages the lock file needs. This fetches package
   information only.
2. It downloads each package with resumable `curl`.
3. It checks every file against the SHA-256 hash that PyPI publishes.

Then you install with no network:

```bash
python3 -m venv venv                       # the script uses the venv's pip
mkdir -p ~/FYP-data/wheels
setsid nohup bash scripts/fetch_wheels.sh >> ~/FYP-data/wheels/fetch.log 2>&1 < /dev/null &
tail -f ~/FYP-data/wheels/fetch.log        # wait for ALL-WHEELS-READY
venv/bin/pip install --no-index --find-links ~/FYP-data/wheels -r backend/requirements.lock.txt
```

`setsid nohup` keeps the download running after the terminal closes. If
the PC shuts down, run the same command again and it resumes.

**Machine-specific, not in Git:** everything the script writes lives on
your own machine, in `~/FYP-data/wheels/` (or the folder you set with
`WHEELS_DIR`):

- the downloaded `*.whl` files and any `*.part` partial files
- `urls.tsv`, `sizes.txt` and `resolve_report.json`
- `fetch.log`

Each machine builds its own cache. A cache only works for the same
platform and Python version it was resolved on.

## 2. MiDaS code and weights (kept out of Git)

```bash
git clone --depth 1 https://github.com/isl-org/MiDaS MiDaS     # gitignored
mkdir -p ~/FYP-data/midas_weights MiDaS/weights
curl -L -C - -o ~/FYP-data/midas_weights/dpt_hybrid_384.pt \
  https://github.com/isl-org/MiDaS/releases/download/v3/dpt_hybrid_384.pt
ln -s ~/FYP-data/midas_weights/dpt_hybrid_384.pt MiDaS/weights/dpt_hybrid_384.pt
sha256sum ~/FYP-data/midas_weights/dpt_hybrid_384.pt
# expected: 501f0c75b3bca7daec6b3682c5054c09b366765aef6fa3a09d03a5cb4b230853
```

The weights file is 492,757,791 bytes.

## 3. Verify the GPU

```bash
venv/bin/python scripts/smoke_test_midas_gpu.py          # FP32
venv/bin/python scripts/smoke_test_midas_gpu.py --fp16   # FP32, then FP16
```

The test exits with code 0 and prints `RESULT: PASS` when every check
passes. It checks the following:

- CUDA is available.
- The model is on the GPU.
- The output size matches the input.
- The values are finite and not constant.
- The backend's `predict()` matches a direct forward pass.

It also reports timing and GPU memory.

**These figures are per-GPU and do not transfer between machines.** Measure
on your own hardware before quoting any of them; the two platforms below
differ by about 4x.

### NVIDIA RTX 4050 Laptop GPU (Phase 0/1 reference, 2026-11-16)

640×480 image, model only, median of 10 runs:

| Precision | Time per frame | Throughput | Peak GPU memory |
|---|---|---|---|
| FP32 | ~40–45 ms | ~22–25 fps | 604 MiB |
| FP16 (autocast) | ~24–27 ms | ~37–42 fps | 868 MiB |

In FP16 the depth differs from FP32 by at most 0.16% of the depth range.

### NVIDIA Quadro T2000 (second verified platform, 2026-11-18)

HP ZBook 15 G6, i7-9850H, 4 GB VRAM (3716 MiB usable), compute sm_75,
driver 595.99.02. Same image size and method:

| Precision | Time per frame | Throughput | Peak GPU memory |
|---|---|---|---|
| FP32 | ~177–188 ms | ~5.3–5.6 fps | 604 MiB |
| FP16 (autocast) | **not usable — slower than FP32** | — | — |

`scripts/smoke_test_midas_gpu.py` reports `RESULT: PASS` here and the
backend's `predict()` matches a direct forward pass, so the model is
correct — only about 4x slower.

**Do not pass `--fp16` on this GPU.** A warmed 4096³ matmul measured
FP32 70 ms versus FP16 327 ms, i.e. FP16 is ~4.7x *slower*; BF16 is on par
with FP32 (74 ms). The Quadro T2000 is TU117-based and lacks the usable
tensor cores the RTX 4050 has, so cuBLAS falls back to a slow FP16 path.
`torch.cuda.get_device_properties(0).major >= 7` still reports `True`, so
that check cannot be used to decide. `sm_75` *is* in the CUDA 13.2 build's
arch list, so this is a performance characteristic, not a compatibility
problem.

Note that peak GPU memory is **604 MiB on both machines**: VRAM is not the
constraint, inference latency is.

Performance varies from run to run with the GPU clock speed, the GPU
temperature (laptop GPUs slow down as they heat up) and whatever else
the system is doing. Treat these numbers as typical ranges, not exact
benchmarks. Expect the full backend to be slower, because it also
decodes and encodes JPEGs and moves data over the network.

The backend itself always runs in FP32, so no code change is needed on
either machine.

## 4. Run the backend and simulate the phone

```bash
./run_backend.sh                                   # http://0.0.0.0:8000
curl http://127.0.0.1:8000/health                  # expect "device":"cuda"
venv/bin/python scripts/test_backend_pipeline.py   # streams video_frames/*.jpg
```

## Known issues

- On import, timm 0.6.13 prints a `torch.jit.script is not supported in
  Python 3.14+` FutureWarning. Inference is unaffected and every test
  passed. A future PyTorch release may turn this warning into an error;
  if that happens, the fix is to move to a newer timm and check that
  MiDaS still works with it.
- The official compatibility matrix has not been checked for the exact
  torch 2.15.0 + torchvision 0.29.2 pairing. pip accepted it
  (torchvision requires `torch>=2.14`), and it works in practice.
- `scripts/test_backend_pipeline.py` reads test frames from
  `video_frames/`, which is not committed. Put any JPEG images in that
  folder before running it.
