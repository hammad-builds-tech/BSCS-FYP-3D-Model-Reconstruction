"""Phase 2 — reactive obstacle layer, applied as a launch-time overlay.

Phase 1 deliberately runs with both costmaps' ``obstacle_layer`` disabled:
the perception representation was an occupancy grid, and the live
depth-derived scan never reached the costmaps. Nav2 therefore could only
avoid obstacles that were already baked into the static map.

Phase 2 feeds the live ``/scan`` (produced by ``depth_to_scan``) into both
costmaps so the planner and controller react to obstacles that are *not* in
the static map, and the default BT's 1 Hz ``ComputePathToPose`` replans
around them.

Why an overlay instead of editing ``nav2_params.yaml``
------------------------------------------------------
The costmaps are not standalone launch nodes: ``global_costmap`` runs inside
``planner_server`` and ``local_costmap`` inside ``controller_server``. A
parameter appended to those nodes in the launch description (the trick Phase 1
used for the goal checker) therefore cannot reach them — the costmap reads its
own ``<name>.<name>.ros__parameters`` block from the YAML file. The only way
to change it without touching the committed file is to write a patched copy
and point the servers at that.

``nav2_params.yaml`` is left untouched, which keeps the Phase 1 acceptance
configuration reproducible. When ``FYP_REACTIVE_OBSTACLES`` is unset or false
this module returns the original path, so Phase 1 bring-up is bit-identical.

Enable with::

    export FYP_REACTIVE_OBSTACLES=1

Scope note
----------
Marking obstacles is only physically meaningful when the scan carries metric
ranges, i.e. ``depth_mode: metric`` (``FYP_DEPTH_SOURCE=gazebo``, Phase 1's
validated path). In ``relative`` mode the ranges come from MiDaS inverse
relative depth anchored by a heuristic (``near_range_anchor``), so they are
*not* calibrated distances; the layer still functions but the marked
positions are approximate. This is why the inflation radius (0.45 m) and the
collision-monitor stop polygon are never relaxed here — they remain the
safety net.
"""

import os
import tempfile

import yaml

#: Environment variable that turns the Phase 2 reactive layer on.
ENV_FLAG = "FYP_REACTIVE_OBSTACLES"

_TRUE = ("1", "true", "yes", "on")


def reactive_obstacles_enabled():
    """Return True when the Phase 2 reactive obstacle layer is requested."""
    return os.environ.get(ENV_FLAG, "0").strip().lower() in _TRUE


def _scan_source(obstacle_max_range, raytrace_max_range):
    """Observation-source block for the depth-derived ``/scan``.

    ``inf_is_valid`` is essential: ``depth_to_scan`` reports empty angular
    bins as ``+inf`` (REP 117). Without this flag ObstacleLayer discards those
    readings, so free space is never cleared and stale obstacles persist
    forever.

    ``expected_update_rate: 0.0`` disables the staleness warning. Depth on
    this hardware arrives at roughly 5 Hz (and 2-9 Hz under full load), well
    below any sensible default, and a stale-sensor warning would otherwise
    flood the logs.
    """
    return {
        "topic": "/scan",
        "data_type": "LaserScan",
        "clearing": True,
        "marking": True,
        "inf_is_valid": True,
        "obstacle_max_range": obstacle_max_range,
        "obstacle_min_range": 0.0,
        "raytrace_max_range": raytrace_max_range,
        "raytrace_min_range": 0.0,
        "expected_update_rate": 0.0,
        "observation_persistence": 0.0,
        # ObstacleLayer drops any observation point whose height in the
        # costmap's global frame falls outside this window. The defaults
        # (0.0 .. 2.0) assume a gravity-aligned lidar referenced to the
        # floor. This scan is neither: it originates 0.18 m up on a camera
        # and, in the *map* frame, appears pitched about -4.35 deg because
        # AMCL's map->odom is 2-D and absorbs the robot's nose-down rest
        # attitude (Phase 1 report section 9). A beam then sits at
        # z = 0.18 - r*sin(4.35 deg), which crosses 0.0 at only r = 2.37 m,
        # so with the default window everything past ~2.4 m is silently
        # discarded in the global costmap while the local costmap -- whose
        # global frame is odom, where the scan is level -- keeps it.
        #
        # Widening the window cannot invent floor obstacles: depth_to_scan
        # has already rejected floor returns geometrically with its
        # elevation filter before a range is ever emitted.
        "min_obstacle_height": -1.0,
        "max_obstacle_height": 2.0,
    }


def _patch_costmap(params, costmap_name, obstacle_max_range, raytrace_max_range):
    """Enable and configure ``obstacle_layer`` inside one costmap block.

    Returns True when the block was found and patched.
    """
    try:
        block = params[costmap_name][costmap_name]["ros__parameters"]
    except (KeyError, TypeError):
        return False

    layer = block.get("obstacle_layer")
    if not isinstance(layer, dict):
        return False

    if costmap_name == "global_costmap":
        # local_costmap sets this; global_costmap does not, so its full grid is
        # published only rarely and any tool reading the topic sees a stale
        # map. Purely an observability setting -- it changes no planning
        # behaviour -- and it is what made the OPEN ISSUE below measurable.
        #
        # OPEN ISSUE (Phase 2, measured 18 Nov 2026): with this layer enabled
        # identically in both costmaps, the LOCAL costmap marks an unmapped
        # obstacle (111-218 lethal cells within 0.5 m, sustained) while the
        # GLOBAL costmap marks none, confirmed through
        # /global_costmap/get_costmap. The global plan therefore still runs
        # straight through the obstacle (closest approach 0.01 m to its
        # centre) and DWB -- correctly -- refuses to follow it, aborting with
        # error 106 instead of routing around.
        #
        # Ruled out by measurement: scan->map TF (resolves; only 2 message
        # filter drops in a full run; no TF exceptions logged), QoS (both
        # costmaps subscribe BEST_EFFORT to a BEST_EFFORT publisher), the
        # update thread (costmap_updates at 1 Hz), /map republishing (published
        # once, transient local) and track_unknown_space (setting it False
        # changed nothing). Remaining structural difference is rolling_window.
        block["always_send_full_costmap"] = True

    # Also set the window at layer level: ObstacleLayer reads these per
    # source, but the layer-level values are what `ros2 param get
    # <costmap> obstacle_layer.min_obstacle_height` reports, and leaving the
    # two disagreeing is how this went unnoticed in the first place.
    layer["min_obstacle_height"] = -1.0
    layer["max_obstacle_height"] = 2.0
    layer["enabled"] = True
    # combination_method 1 = maximum: the static map's obstacles are kept and
    # live returns are added, never subtracted. A newly seen obstacle can only
    # make a cell more expensive, so enabling this layer cannot open a path
    # through a mapped wall.
    layer["combination_method"] = 1
    layer["observation_sources"] = "scan"
    layer["scan"] = _scan_source(obstacle_max_range, raytrace_max_range)
    return True


#: DWB obstacle-critic weight used when the reactive layer is on.
#: nav2_params.yaml ships BaseObstacle.scale 0.10 against PathAlign /
#: PathDist 32.0 — a 320x bias towards following the global path. That is
#: rational while obstacle_layer is disabled, because the critic then scores
#: nothing but static map cells the planner already routed around. With live
#: returns in the costmap it makes DWB drive straight through a newly seen
#: obstacle: measured on 18 Nov 2026, the robot entered an unmapped 0.4 m box
#: and ended with its own centre cell marked lethal, aborting with
#: "Failed to make progress" (error 105).
REACTIVE_BASE_OBSTACLE_SCALE = 32.0

#: Forward cruise used when the reactive layer is on.
#: Depth reaches the costmap about 0.4 s after the image on this hardware
#: (measured scan-stamp lag vs /clock) and arrives at only 5-10 Hz, so at the
#: committed 0.85 m/s the robot covers ~0.35 m before an obstacle is even
#: representable, before DWB's 1.2 s horizon is considered. Halving the cruise
#: halves that blind distance. The inflation radius (0.45 m) and the
#: collision-monitor stop polygon are deliberately NOT touched.
REACTIVE_MAX_VEL_X = 0.45


def _patch_controller(params):
    """Re-weight DWB for a costmap that now contains live obstacles.

    Returns True when the FollowPath block was found and patched.
    """
    try:
        follow = params["controller_server"]["ros__parameters"]["FollowPath"]
    except (KeyError, TypeError):
        return False
    if not isinstance(follow, dict):
        return False

    follow["BaseObstacle.scale"] = REACTIVE_BASE_OBSTACLE_SCALE
    follow["max_vel_x"] = REACTIVE_MAX_VEL_X
    # DWB enforces max_speed_xy independently of max_vel_x; leaving it at 0.85
    # would let sampled trajectories exceed the reduced cruise.
    follow["max_speed_xy"] = REACTIVE_MAX_VEL_X
    return True


def build_params(params_file):
    """Return the parameter file the Nav2 servers should load.

    With the Phase 2 flag off this is ``params_file`` itself. With it on a
    patched copy is written to a temporary file and that path is returned.
    The copy is not cleaned up explicitly: it lives in the system temp
    directory for the lifetime of the launch, which is what Nav2 needs.
    """
    if not reactive_obstacles_enabled():
        return params_file

    with open(params_file, "r", encoding="utf-8") as handle:
        params = yaml.safe_load(handle)

    # Metric mode carries true metres out to the wall (clearing_max_range 8.0
    # in localization.launch.py), so rays may clear the full depth range.
    # Relative mode is uncalibrated and capped at 3.5 m, so both ranges stay
    # inside it to avoid clearing or marking beyond what the data supports.
    if os.environ.get("FYP_DEPTH_SOURCE", "phone") == "gazebo":
        obstacle_max_range, raytrace_max_range = 3.0, 8.0
    else:
        obstacle_max_range, raytrace_max_range = 2.5, 3.5

    patched = [
        name
        for name in ("global_costmap", "local_costmap")
        if _patch_costmap(params, name, obstacle_max_range, raytrace_max_range)
    ]
    # Enabling the layer is not sufficient on its own: the controller must
    # also be willing to leave the global path to get around what it sees.
    _patch_controller(params)
    if not patched:
        # Nothing to patch: fall back to the committed file rather than
        # silently launching with a half-written copy.
        return params_file

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        suffix="_nav2_params_reactive.yaml",
        delete=False,
        encoding="utf-8",
    )
    with handle:
        yaml.safe_dump(params, handle, default_flow_style=False, sort_keys=False)
    return handle.name
