"""Tests for the Phase 2 reactive-obstacle parameter overlay.

The critical property is that Phase 1 bring-up is unaffected: with the flag
off the committed parameter file must be handed to Nav2 untouched.
"""

import copy
import os

import pytest
import yaml

from indoor_nav_costmap.params_overlay import (
    ENV_FLAG,
    build_params,
    reactive_obstacles_enabled,
)

PARAMS = {
    "controller_server": {
        "ros__parameters": {
            "controller_frequency": 10.0,
            "FollowPath": {
                "plugin": "dwb_core::DWBLocalPlanner",
                "BaseObstacle.scale": 0.10,
                "PathAlign.scale": 32.0,
                "PathDist.scale": 32.0,
                "max_vel_x": 0.85,
                "max_speed_xy": 0.85,
            },
        }
    },
    "global_costmap": {
        "global_costmap": {
            "ros__parameters": {
                "footprint": "[[0.35, 0.25]]",
                "plugins": ["static_layer", "obstacle_layer", "inflation_layer"],
                "obstacle_layer": {
                    "plugin": "nav2_costmap_2d::ObstacleLayer",
                    "enabled": False,
                },
                "inflation_layer": {"inflation_radius": 0.45},
            }
        }
    },
    "local_costmap": {
        "local_costmap": {
            "ros__parameters": {
                "plugins": ["static_layer", "obstacle_layer", "inflation_layer"],
                "obstacle_layer": {
                    "plugin": "nav2_costmap_2d::ObstacleLayer",
                    "enabled": False,
                },
                "inflation_layer": {"inflation_radius": 0.45},
            }
        }
    },
}


@pytest.fixture
def params_file(tmp_path):
    path = tmp_path / "nav2_params.yaml"
    path.write_text(yaml.safe_dump(PARAMS), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def clean_env():
    saved = {k: os.environ.get(k) for k in (ENV_FLAG, "FYP_DEPTH_SOURCE")}
    for key in saved:
        os.environ.pop(key, None)
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_flag_defaults_to_off():
    assert reactive_obstacles_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_flag_accepts_truthy_spellings(value):
    os.environ[ENV_FLAG] = value
    assert reactive_obstacles_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_flag_rejects_falsy_spellings(value):
    os.environ[ENV_FLAG] = value
    assert reactive_obstacles_enabled() is False


def test_phase1_path_returns_the_committed_file_unchanged(params_file):
    """With the flag off Nav2 must load the committed file itself."""
    before = open(params_file, encoding="utf-8").read()
    assert build_params(params_file) == params_file
    assert open(params_file, encoding="utf-8").read() == before


def test_enabled_overlay_writes_a_copy_and_never_edits_the_original(params_file):
    os.environ[ENV_FLAG] = "1"
    before = open(params_file, encoding="utf-8").read()
    out = build_params(params_file)
    assert out != params_file
    assert open(params_file, encoding="utf-8").read() == before


def test_overlay_enables_obstacle_layer_in_both_costmaps(params_file):
    os.environ[ENV_FLAG] = "1"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))

    for name in ("global_costmap", "local_costmap"):
        layer = patched[name][name]["ros__parameters"]["obstacle_layer"]
        assert layer["enabled"] is True
        assert layer["observation_sources"] == "scan"
        # maximum: live returns can only add cost, never clear a mapped wall
        assert layer["combination_method"] == 1
        scan = layer["scan"]
        assert scan["topic"] == "/scan"
        assert scan["data_type"] == "LaserScan"
        assert scan["marking"] is True
        assert scan["clearing"] is True
        # depth_to_scan reports empty bins as +inf (REP 117); without this
        # the layer discards them and never clears freed space.
        assert scan["inf_is_valid"] is True


def test_overlay_preserves_the_safety_margins(params_file):
    """Inflation radius and footprint are the safety net; never relaxed."""
    os.environ[ENV_FLAG] = "1"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))

    for name in ("global_costmap", "local_costmap"):
        block = patched[name][name]["ros__parameters"]
        assert block["inflation_layer"]["inflation_radius"] == 0.45


def test_overlay_changes_only_its_documented_keys(params_file):
    """The overlay touches obstacle_layer plus three DWB keys and nothing else.

    This pins the blast radius: every other Phase 1 parameter -- AMCL, the
    planner, the behaviours, the footprint, the collision monitor -- must come
    through byte-identical.
    """
    os.environ[ENV_FLAG] = "1"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))

    allowed_follow_keys = {"BaseObstacle.scale", "max_vel_x", "max_speed_xy"}

    def strip(tree):
        out = copy.deepcopy(tree)
        for name in ("global_costmap", "local_costmap"):
            block = out[name][name]["ros__parameters"]
            block.pop("obstacle_layer", None)
            # observability only, global_costmap: makes the full grid
            # readable off the topic. No planning behaviour depends on it.
            block.pop("always_send_full_costmap", None)
        follow = out["controller_server"]["ros__parameters"]["FollowPath"]
        for key in allowed_follow_keys:
            follow.pop(key, None)
        return out

    assert strip(patched) == strip(PARAMS)


def test_relative_mode_keeps_ranges_inside_the_uncalibrated_limit(params_file):
    """Phone/relative depth is capped at 3.5 m and is not metric.

    Marking or clearing beyond that range would assert geometry the data
    cannot support.
    """
    os.environ[ENV_FLAG] = "1"
    os.environ["FYP_DEPTH_SOURCE"] = "phone"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))
    scan = patched["local_costmap"]["local_costmap"]["ros__parameters"][
        "obstacle_layer"
    ]["scan"]
    assert scan["obstacle_max_range"] <= 2.5
    assert scan["raytrace_max_range"] <= 3.5


def test_metric_mode_clears_out_to_the_full_depth_range(params_file):
    os.environ[ENV_FLAG] = "1"
    os.environ["FYP_DEPTH_SOURCE"] = "gazebo"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))
    scan = patched["local_costmap"]["local_costmap"]["ros__parameters"][
        "obstacle_layer"
    ]["scan"]
    assert scan["obstacle_max_range"] == 3.0
    assert scan["raytrace_max_range"] == 8.0


def test_missing_costmap_blocks_fall_back_to_the_committed_file(tmp_path):
    """A parameter file without costmap blocks must not yield a half copy."""
    path = tmp_path / "other.yaml"
    path.write_text(yaml.safe_dump({"amcl": {"ros__parameters": {}}}), encoding="utf-8")
    os.environ[ENV_FLAG] = "1"
    assert build_params(str(path)) == str(path)


def test_phase1_controller_weights_are_untouched_when_flag_is_off(params_file):
    """The committed BaseObstacle.scale 0.10 / 0.85 m/s must survive."""
    assert build_params(params_file) == params_file
    follow = PARAMS["controller_server"]["ros__parameters"]["FollowPath"]
    assert follow["BaseObstacle.scale"] == 0.10
    assert follow["max_vel_x"] == 0.85


def test_reactive_mode_raises_the_obstacle_critic_weight(params_file):
    """With live obstacles DWB must stop out-weighting avoidance 320:1.

    nav2_params.yaml ships BaseObstacle.scale 0.10 against PathDist 32.0. A
    measured run on 18 Nov 2026 drove into an unmapped box and aborted with
    error 105; this re-weighting is the fix.
    """
    os.environ[ENV_FLAG] = "1"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))
    follow = patched["controller_server"]["ros__parameters"]["FollowPath"]
    assert follow["BaseObstacle.scale"] >= follow["PathDist.scale"]


def test_reactive_mode_reduces_cruise_to_match_perception_latency(params_file):
    os.environ[ENV_FLAG] = "1"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))
    follow = patched["controller_server"]["ros__parameters"]["FollowPath"]
    assert follow["max_vel_x"] <= 0.5
    # DWB caps speed with max_speed_xy independently; both must move together
    assert follow["max_speed_xy"] == follow["max_vel_x"]


def test_reactive_mode_never_relaxes_the_safety_net(params_file):
    """Inflation radius is the safety net and must never be traded for speed."""
    os.environ[ENV_FLAG] = "1"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))
    for name in ("global_costmap", "local_costmap"):
        block = patched[name][name]["ros__parameters"]
        assert block["inflation_layer"]["inflation_radius"] == 0.45


def test_height_window_accommodates_the_pitched_scan(params_file):
    """The default 0.0 m floor silently discards this sensor's returns.

    ObstacleLayer drops observation points whose height in the costmap's
    global frame is outside [min_obstacle_height, max_obstacle_height]. The
    defaults (0.0 .. 2.0) assume a gravity-aligned lidar referenced to the
    floor. This scan starts 0.18 m up on a camera and, in the *map* frame,
    appears pitched about -4.35 deg because AMCL's map->odom is 2-D
    (Phase 1 report section 9), so a beam sits at
    z = 0.18 - r*sin(4.35 deg) and crosses 0.0 at r = 2.37 m.

    Measured 18 Nov 2026: with the default floor the global costmap marked
    ZERO cells for an unmapped box while the local costmap (global frame
    odom, where the scan is level) marked 111-218. Widening the window
    produced 17 lethal cells in the global costmap and turned a 1.754 m
    goal failure into 5/5 successes.
    """
    os.environ[ENV_FLAG] = "1"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))

    import math

    crossover = 0.18 / math.sin(math.radians(4.35))

    for name in ("global_costmap", "local_costmap"):
        layer = patched[name][name]["ros__parameters"]["obstacle_layer"]
        for scope in (layer, layer["scan"]):
            # must admit a beam at the far end of the metric range
            assert scope["min_obstacle_height"] < -(
                8.0 * math.sin(math.radians(4.35)) - 0.18
            )
            # and must still reject the ceiling
            assert scope["max_obstacle_height"] == 2.0
        # sanity: the default really would have cut the range this short
        assert crossover < 3.0


def test_height_window_is_set_at_both_layer_and_source_scope(params_file):
    """Layer-level and per-source values must agree.

    ObstacleLayer reads these per source, but `ros2 param get <costmap>
    obstacle_layer.min_obstacle_height` reports the layer-level value.
    Letting the two disagree is how the rejection went unnoticed.
    """
    os.environ[ENV_FLAG] = "1"
    patched = yaml.safe_load(open(build_params(params_file), encoding="utf-8"))
    for name in ("global_costmap", "local_costmap"):
        layer = patched[name][name]["ros__parameters"]["obstacle_layer"]
        for key in ("min_obstacle_height", "max_obstacle_height"):
            assert layer[key] == layer["scan"][key]
