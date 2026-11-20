"""Phase 3 — Nav2 navigation stack behind an independent Collision Monitor.

WHY THIS FILE EXISTS
--------------------
Phase 2's ``navigation.launch.py`` remaps both ``controller_server`` and
``behavior_server`` straight onto ``/cmd_vel``, which the ``ros_gz_bridge``
forwards to Gazebo. Nothing sits in between, so a velocity command is never
checked against live sensor data before it moves the robot. The Phase 3 audit
also found that ``nav2_params.yaml`` configures a ``collision_monitor`` block
whose package (``nav2_collision_monitor``) was not even installed, so that
node could never have run.

This launch inserts the official Nav2 Collision Monitor into the command
chain:

    controller_server ─┐
    behavior_server  ──┴─> /cmd_vel_nav ─> collision_monitor ─> /cmd_vel_safe
                                                                      │
                                                        cmd_vel_watchdog
                                                                      │
                                                                 /cmd_vel
                                                                      │
                                                        ros_gz_bridge ─┴─> Gazebo

The watchdog is last because gz::sim::systems::VelocityControl latches the
last command it received forever (no timeout element exists in the plugin).
Without it, a dead Collision Monitor leaves the robot driving: measured
4.4 m after a mid-motion kill, and 2.78-2.81 m across 3 runs after the
publisher simply stopped.

Phase 2 is untouched: this is a separate launch file, and
``navigation.launch.py``, ``nav2_params.yaml``, ``localization.launch.py``
and ``run_system.sh`` are not modified. Running Phase 2 still produces the
Phase 2 behaviour exactly.

WHY PARAMETERS ARE INLINE RATHER THAN A YAML FILE
-------------------------------------------------
``setup.py`` installs ``launch/*.py`` with a glob but lists ``config/``
files explicitly, so adding a Phase 3 YAML would require editing
``setup.py`` -- a Phase 2 file. Declaring the Collision Monitor parameters
here keeps the Phase 2 package definition untouched and matches how
``localization.launch.py`` already passes Gazebo-mode overrides inline.

VELOCITY SMOOTHER: DELIBERATELY NOT ADDED
-----------------------------------------
``nav2_velocity_smoother`` *is* installed and ``nav2_params.yaml`` configures
it, but it is not wired in here, for three reasons:

1. It provides no collision protection whatsoever. Adding it would make the
   motion look smoother without changing safety.
2. DWB already enforces this robot's acceleration limits
   (``acc_lim_x`` 2.5, ``decel_lim_x`` -3.0), and the Gazebo differential
   drive applies its own.
3. Placement matters for safety. The committed ``collision_monitor`` block
   expects ``cmd_vel_in_topic: cmd_vel_smoothed``, i.e. the original intent
   was controller -> smoother -> monitor. That ordering is the only safe one:
   a smoother placed *after* the monitor would ramp down the emergency stop
   instead of applying it immediately. If a smoother is added later it must
   sit upstream of the monitor so the monitor keeps final authority over
   what reaches the robot.

SAFETY ENVELOPE -- TWO COMMITTED VALUES HAD TO CHANGE
-----------------------------------------------------
The intent was to reuse the committed ``PolygonStop`` verbatim. Measurement
showed two of its values make the monitor non-functional on this robot, so
Phase 3 overrides them here (``nav2_params.yaml`` itself is NOT edited):

* ``PolygonStop`` front edge 0.45 m -> 0.60 m. The camera sits 0.35 m
  forward of ``base_link`` and ``min_range`` is 0.15 m, so the nearest
  reportable return is 0.500 m head-on -- outside a 0.45 m zone. The
  committed polygon can never fire.
* ``scan.source_timeout`` 0.5 s -> 1.0 s. Measured scan stamp lag peaks at
  0.591 s, above 0.5 s, which produced 7 spurious "invalid source" stops in
  45 s of clear-path navigation.

Both are derived from measurement and documented at their definitions
below. Neither is a tuned safety margin, and the resulting envelope needs
sign-off before being treated as the project's safety case. The polygon is
expressed in ``base_link``, the robot base frame.

The footprint, inflation radius, AMCL and DWB parameters are NOT touched.
"""

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from indoor_nav_costmap.params_overlay import build_params
from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node

#: Velocity topic the Nav2 servers publish on. Nothing bridges this to
#: Gazebo, so a command here cannot move the robot by itself.
CMD_VEL_NAV = "/cmd_vel_nav"

#: Collision Monitor output. This is NOT the topic the bridge listens on:
#: the watchdog sits between them (see CMD_VEL_BRIDGE).
CMD_VEL_SAFE = "/cmd_vel_safe"

#: Velocity topic the ros_gz_bridge forwards to Gazebo. Only the watchdog
#: publishes here.
#:
#: The watchdog is required because gz::sim::systems::VelocityControl latches
#: the last command forever -- it exposes no timeout element at all (verified
#: against libgz-sim-velocity-control-system.so.10.5.0). Measured: with the
#: publisher stopped the robot continued 2.78-2.81 m over 10 s across 3 runs
#: and was still moving; killing the Collision Monitor mid-motion gave 4.4 m.
CMD_VEL_BRIDGE = "/cmd_vel"

#: Watchdog silence tolerance. /cmd_vel_nav measured at 9.925 Hz against a
#: controller_frequency of 10.0 Hz, so ~0.10 s per command; 0.50 s allows
#: five consecutive misses before zeroing.
WATCHDOG_TIMEOUT_S = 0.5

#: Rate at which zeros are asserted once the input goes silent. Must be high
#: enough to overwrite the plugin's latched command promptly.
WATCHDOG_RATE_HZ = 20.0

#: Stop polygon front edge, in base_link.
#:
#: The committed nav2_params.yaml value is 0.45 m. That is UNREACHABLE by
#: this sensor and was measured to be so on 19 Nov 2026:
#:   - base_link -> sim_depth_scan is (0.350, 0, 0.100), i.e. the camera sits
#:     0.35 m forward of base_link (verified by tf2_echo);
#:   - depth_to_scan enforces min_range 0.15 m;
#:   - so the nearest point the sensor can report is x = 0.35 + 0.15 = 0.500 m
#:     head-on, and x = 0.474 m at the 34.5 deg FOV edge.
#: Both lie beyond a 0.45 m front edge, so no scan return can ever fall
#: inside the committed polygon and PolygonStop could never fire. Verified
#: empirically: with the committed value the monitor never left
#: DO_NOTHING/invalid-source even with an obstacle 0.17 m from the chassis.
#:
#: 0.60 m is used here: above the 0.500 m head-on detectability floor, giving
#: a 0.10 m band of detectable depth inside the zone, and 0.25 m clear of the
#: chassis front (footprint front is 0.35 m). This is a DERIVED minimum, not
#: a tuned safety margin -- see docs/PHASE3_COLLISION_MONITOR.md. It needs
#: sign-off before being treated as the project's safety envelope, because a
#: larger zone also stops the robot during legitimate close passes.
POLYGON_STOP_FRONT = 0.60
POLYGON_STOP_BACK = -0.20
POLYGON_STOP_HALF_WIDTH = 0.30
POLYGON_STOP_POINTS = (
    "[[%.2f, %.2f], [%.2f, %.2f], [%.2f, %.2f], [%.2f, %.2f]]"
    % (
        POLYGON_STOP_FRONT, POLYGON_STOP_HALF_WIDTH,
        POLYGON_STOP_FRONT, -POLYGON_STOP_HALF_WIDTH,
        POLYGON_STOP_BACK, -POLYGON_STOP_HALF_WIDTH,
        POLYGON_STOP_BACK, POLYGON_STOP_HALF_WIDTH,
    )
)

#: Per-source staleness tolerance.
#:
#: The committed nav2_params.yaml value is 0.5 s. Measured scan stamp lag
#: against /clock over 249 scans on 19 Nov 2026: median 0.403 s, p95 0.487 s,
#: MAX 0.591 s. The maximum exceeds 0.5 s, so the monitor declared "invalid
#: source" and stopped the robot 7 times in 45 s of otherwise clear-path
#: navigation. That is a nuisance stop, not a safety response, and it
#: degrades availability without improving safety.
#:
#: 1.0 s clears the measured maximum with ~0.4 s headroom and matches the
#: transform_tolerance already used by AMCL and both costmaps. The trade-off
#: is explicit: a genuinely dead sensor is now detected in up to 1.0 s
#: instead of 0.5 s.
SCAN_SOURCE_TIMEOUT = 1.0


def collision_monitor_parameters():
    """Parameters for the official nav2_collision_monitor node.

    Names verified against the installed 1.5.2 ``libcollision_monitor_core.so``
    rather than copied from documentation.
    """
    return {
        "use_sim_time": True,
        # nav2_params.yaml sets this false for controller_server and
        # behavior_server, so the monitor must agree or it will not
        # deserialize their messages.
        "enable_stamped_cmd_vel": False,
        "base_frame_id": "base_link",
        "odom_frame_id": "odom",
        "cmd_vel_in_topic": CMD_VEL_NAV,
        "cmd_vel_out_topic": CMD_VEL_SAFE,
        "state_topic": "/collision_monitor_state",
        # Matches the transform_tolerance used by AMCL and both costmaps in
        # nav2_params.yaml. The depth pipeline lags ~0.4 s on this hardware,
        # so a tighter value would reject valid observations.
        "transform_tolerance": 1.0,
        # Shifts the polygon by odometry between observations. Safe here
        # because Gazebo odometry reports the true pose.
        "base_shift_correction": True,
        # How long to keep republishing the zero command after a stop, so a
        # single dropped message cannot restart the robot.
        "stop_pub_timeout": 2.0,
        "polygons": ["PolygonStop"],
        "PolygonStop.type": "polygon",
        "PolygonStop.points": POLYGON_STOP_POINTS,
        "PolygonStop.action_type": "stop",
        # Three returns inside the polygon before stopping: one stray pixel
        # in a MiDaS-derived scan should not halt the robot.
        "PolygonStop.min_points": 3,
        "PolygonStop.visualize": True,
        "PolygonStop.polygon_pub_topic": "/collision_monitor_polygon",
        "observation_sources": ["scan"],
        "scan.type": "scan",
        # The depth-derived scan: this project has no lidar. In Gazebo mode
        # it arrives in the levelled sim_depth_scan frame at ~10.5 Hz; the
        # monitor transforms it into base_frame_id itself.
        "scan.topic": "/scan",
        # See SCAN_SOURCE_TIMEOUT: the committed 0.5 s is below the measured
        # worst-case pipeline lag and caused spurious stops. If the source
        # does go stale the monitor stops the robot (its own wording: "Robot
        # to stop due to invalid source").
        "scan.source_timeout": SCAN_SOURCE_TIMEOUT,
        "scan.enabled": True,
    }


def _watchdog_script():
    """Absolute path to the watchdog script.

    It lives in scripts/phase3/ and is NOT installed by setup.py, because
    adding a console_script entry point would mean editing setup.py -- a
    Phase 2 file. FYP_ROOT is exported by scripts/fyp_env.sh (which the
    Phase 3 bring-up script sources); the __file__ walk is the fallback for
    a --symlink-install tree.
    """
    root = os.environ.get("FYP_ROOT")
    if root:
        candidate = Path(root) / "scripts" / "phase3" / "cmd_vel_watchdog.py"
        if candidate.is_file():
            return str(candidate)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "scripts" / "phase3" / "cmd_vel_watchdog.py"
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError(
        "cmd_vel_watchdog.py not found; set FYP_ROOT to the repository root"
    )


def generate_launch_description():
    committed_params = str(
        Path(get_package_share_directory("indoor_nav_costmap"))
        / "config"
        / "nav2_params.yaml"
    )
    # Reuse the Phase 2 overlay unchanged, so Phase 3 inherits the verified
    # reactive obstacle layer when FYP_REACTIVE_OBSTACLES is set.
    params_file = build_params(committed_params)

    controller_params = [params_file]
    if os.environ.get("FYP_DEPTH_SOURCE", "phone") == "gazebo":
        # Identical to navigation.launch.py: the simulation-only goal checker
        # that Phase 1 validated. Repeated rather than imported because
        # Phase 2's launch file must not be modified.
        controller_params.append(
            {
                "goal_checker_plugins": ["general_goal_checker"],
                "general_goal_checker.plugin": "nav2_controller::SimpleGoalChecker",
                "general_goal_checker.xy_goal_tolerance": 0.05,
                "general_goal_checker.yaw_goal_tolerance": 0.25,
                "general_goal_checker.stateful": True,
                "FollowPath.xy_goal_tolerance": 0.05,
            }
        )

    # The only difference from Phase 2: cmd_vel goes to CMD_VEL_NAV, which
    # nothing bridges to Gazebo, instead of straight to /cmd_vel.
    controller_server = Node(
        package="nav2_controller",
        executable="controller_server",
        name="controller_server",
        output="screen",
        parameters=controller_params,
        remappings=[("cmd_vel", CMD_VEL_NAV)],
    )

    planner_server = Node(
        package="nav2_planner",
        executable="planner_server",
        name="planner_server",
        output="screen",
        parameters=[params_file],
    )

    # Recovery behaviours drive the robot too (spin, backup,
    # drive_on_heading), so they must be gated as well. Leaving this on
    # /cmd_vel would be an unprotected bypass during exactly the situations
    # where the robot is already in trouble.
    behavior_server = Node(
        package="nav2_behaviors",
        executable="behavior_server",
        name="behavior_server",
        output="screen",
        parameters=[params_file],
        remappings=[("cmd_vel", CMD_VEL_NAV)],
    )

    bt_navigator = Node(
        package="nav2_bt_navigator",
        executable="bt_navigator",
        name="bt_navigator",
        output="screen",
        parameters=[params_file],
    )

    collision_monitor = Node(
        package="nav2_collision_monitor",
        executable="collision_monitor",
        name="collision_monitor",
        output="screen",
        parameters=[collision_monitor_parameters()],
    )

    # Last element before the bridge. Run as a plain process rather than a
    # launch_ros Node: it has no setup.py entry point on purpose (see
    # _watchdog_script).
    cmd_vel_watchdog = ExecuteProcess(
        cmd=[
            "/usr/bin/python3",
            _watchdog_script(),
            "--in-topic", CMD_VEL_SAFE,
            "--out-topic", CMD_VEL_BRIDGE,
            "--timeout", str(WATCHDOG_TIMEOUT_S),
            "--rate", str(WATCHDOG_RATE_HZ),
        ],
        output="screen",
        respawn=True,
        respawn_delay=1.0,
    )

    # collision_monitor is a lifecycle node and will sit in `unconfigured`
    # forever unless a manager transitions it. It is listed last so the
    # Nav2 servers are active before commands can flow.
    navigation_manager = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_navigation",
        output="screen",
        parameters=[
            params_file,
            {
                "autostart": True,
                "node_names": [
                    "controller_server",
                    "planner_server",
                    "behavior_server",
                    "bt_navigator",
                    "collision_monitor",
                ],
                "use_sim_time": True,
            },
        ],
    )

    return LaunchDescription(
        [
            controller_server,
            planner_server,
            behavior_server,
            bt_navigator,
            collision_monitor,
            cmd_vel_watchdog,
            navigation_manager,
        ]
    )
