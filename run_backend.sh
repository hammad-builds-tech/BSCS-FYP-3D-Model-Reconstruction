#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/scripts/fyp_env.sh"

# FYP Backend Startup Script

set -e

cd "$FYP_ROOT"

echo "======================================="
echo "FYP Backend Server"
echo "======================================="
echo

# Python interpreter with torch + FastAPI comes from scripts/fyp_env.sh
# (FYP_PY: explicit override, project venv, legacy conda env, system python3).
if ! "$FYP_PY" -c "import uvicorn, fastapi, torch" 2>/dev/null; then
    echo "ERROR: $FYP_PY is missing uvicorn/fastapi/torch"
    echo "Create the project venv at $FYP_ROOT/venv or export FYP_PY"
    exit 1
fi

# Verify Python version
PYTHON_VERSION=$("$FYP_PY" --version 2>&1)
echo "Using: $PYTHON_VERSION ($FYP_PY)"
echo

# Check if MiDaS directory exists. It is gitignored third-party code, so a
# fresh clone never has it; say how to get it instead of just failing.
if [ ! -d "MiDaS" ]; then
    echo "ERROR: MiDaS directory not found at $FYP_ROOT/MiDaS"
    echo "  MiDaS is a gitignored third-party dependency. From the repo root:"
    echo "    git clone --depth 1 https://github.com/isl-org/MiDaS MiDaS"
    echo "  Phase 0/1 used commit 4545977. See docs/BACKEND_SETUP.md section 2."
    exit 1
fi

# Check if weights exist
if [ ! -f "MiDaS/weights/dpt_hybrid_384.pt" ]; then
    echo "ERROR: MiDaS weights not found at MiDaS/weights/dpt_hybrid_384.pt"
    echo "  Download DPT-Hybrid-384 (492,757,791 bytes) and link it there:"
    echo "    mkdir -p \$HOME/FYP-data/midas_weights MiDaS/weights"
    echo "    curl -L -C - -o \$HOME/FYP-data/midas_weights/dpt_hybrid_384.pt \\"
    echo "      https://github.com/isl-org/MiDaS/releases/download/v3/dpt_hybrid_384.pt"
    echo "    ln -s \$HOME/FYP-data/midas_weights/dpt_hybrid_384.pt \\"
    echo "      MiDaS/weights/dpt_hybrid_384.pt"
    echo "  Expected sha256:"
    echo "    501f0c75b3bca7daec6b3682c5054c09b366765aef6fa3a09d03a5cb4b230853"
    echo "  See docs/BACKEND_SETUP.md section 2."
    exit 1
fi

# The backend venv must not be mixed with a ROS terminal: rclpy and cv_bridge
# are built against the system numpy/OpenCV, the venv carries its own.
if [ -n "${AMENT_PREFIX_PATH:-}" ]; then
    echo "WARNING: a ROS 2 environment is sourced in this shell."
    echo "         The backend and the ROS nodes are meant to run in separate"
    echo "         terminals and talk over HTTP only (docs/BACKEND_SETUP.md)."
fi

echo "Starting FastAPI backend on http://0.0.0.0:8000"
echo "MiDaS will load on startup..."
echo

# Start the backend with FYP environment
PYTHONPATH=$FYP_ROOT:$PYTHONPATH \
"$FYP_PY" -m uvicorn backend.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload
