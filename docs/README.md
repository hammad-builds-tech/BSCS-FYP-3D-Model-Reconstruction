# Documentation index

Smartphone-Based Real-Time 3D Indoor Mapping and Autonomous Navigation.

This file was previously empty (0 bytes) and is an index only; it does not
restate the documents it points at.

## Start here

| Document | What it covers |
|---|---|
| [`../README.md`](../README.md) | Project overview and quick start |
| [`SETUP.md`](SETUP.md) | Getting a fresh clone running |
| [`BACKEND_SETUP.md`](BACKEND_SETUP.md) | Backend venv, MiDaS weights, per-GPU benchmarks |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How the pieces fit together |

## Running the system

| Document | What it covers |
|---|---|
| [`RUN_NAVIGATION.md`](RUN_NAVIGATION.md) | Recorded-video navigation pipeline |
| [`PIPELINE.md`](PIPELINE.md) | Reconstruction pipeline stages |
| [`API.md`](API.md) | Backend HTTP / WebSocket endpoints |
| [`../BRINGUP.md`](../BRINGUP.md) | Full simulated stack bring-up |

## Status and results

| Document | What it covers |
|---|---|
| [`PHASE1_COMPLETION_REPORT.md`](PHASE1_COMPLETION_REPORT.md) | Phase 1 results, method and known limitations |
| [`evidence/phase1/README.md`](evidence/phase1/README.md) | Raw Phase 1 test evidence |
| [`PHASE2_REACTIVE_OBSTACLES.md`](PHASE2_REACTIVE_OBSTACLES.md) | Phase 2 reactive obstacle avoidance: root cause, fix and 5-run evidence |
| [`TECHNICAL_ASSESSMENT.md`](TECHNICAL_ASSESSMENT.md) | Technical assessment |

## Conventions used in these documents

- A claim is only written down if there is a measurement or a file behind it.
  Proposed and implemented behaviour are named separately.
- Performance numbers are tagged with the machine they were measured on.
  The project is developed on two machines whose GPUs differ by about 4x
  (see [`BACKEND_SETUP.md`](BACKEND_SETUP.md) and `CLAUDE.md` section 6).
- Phase 1's validated configuration is the baseline. Later work is added
  behind an environment flag rather than by editing
  `ros2_ws/src/indoor_nav_costmap/config/nav2_params.yaml`, so Phase 1
  stays reproducible.
