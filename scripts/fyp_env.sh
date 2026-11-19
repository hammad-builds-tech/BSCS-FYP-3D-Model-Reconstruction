#!/bin/bash
# Shared environment for every FYP shell script. Source it, do not execute it:
#
#   source "$(dirname "${BASH_SOURCE[0]}")/fyp_env.sh"          # from scripts/
#   source "$(dirname "${BASH_SOURCE[0]}")/scripts/fyp_env.sh"  # from repo root
#
# FYP_ROOT  project root. Defaults to the clone this file lives in, so the
#           repository works from any location and for any user.
# FYP_PY    Python interpreter that has torch/FastAPI/OpenCV (backend, MiDaS,
#           reconstruction). First match wins: explicit FYP_PY, the project
#           venv, the legacy conda env, then the system python3.
#
# Both can be overridden by exporting them before running a script.

if [ -z "${FYP_ROOT:-}" ]; then
    FYP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
export FYP_ROOT

if [ -z "${FYP_PY:-}" ]; then
    for _fyp_cand in "$FYP_ROOT/venv/bin/python" \
                     "$HOME/miniconda3/envs/fyp/bin/python"; do
        if [ -x "$_fyp_cand" ]; then
            FYP_PY="$_fyp_cand"
            break
        fi
    done
    unset _fyp_cand
    FYP_PY="${FYP_PY:-$(command -v python3)}"

    # Say which interpreter won when it is NOT the project venv. The silent
    # fallback used to be the confusing failure here: with no venv the
    # scripts quietly ran on the legacy conda env or the system python, which
    # carry a different torch (or none), and the backend then failed much
    # later with an unrelated-looking error.
    case "$FYP_PY" in
        "$FYP_ROOT/venv/bin/python") : ;;
        *)
            echo "WARNING: $FYP_ROOT/venv not found; using $FYP_PY" >&2
            echo "         Expect a different torch/OpenCV than the tested" >&2
            echo "         environment. See docs/BACKEND_SETUP.md." >&2
            ;;
    esac
fi
export FYP_PY

# ROS 2 python packages (rclpy, cv_bridge) are built against the SYSTEM
# python, numpy and OpenCV. An active conda environment puts its own python
# first on PATH, which makes `import rclpy` fail with a misleading
# "No module named 'em'". Warn once rather than let it look like a ROS
# installation problem.
if [ -n "${CONDA_PREFIX:-}" ]; then
    echo "WARNING: conda env active (${CONDA_DEFAULT_ENV:-$CONDA_PREFIX})." >&2
    echo "         ROS 2 python may fail with \"No module named 'em'\"." >&2
    echo "         Run 'conda deactivate' in ROS terminals, or" >&2
    echo "         'conda config --set auto_activate_base false'." >&2
fi
