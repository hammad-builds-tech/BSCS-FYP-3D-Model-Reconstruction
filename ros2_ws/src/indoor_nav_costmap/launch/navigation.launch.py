"""Phase 3 — Nav2 navigation stack.

Starts controller/planner/behavior servers, the BT navigator and their
lifecycle manager. Only start this phase after localization is healthy
(map -> odom available and /scan flowing), otherwise the global costmap
cannot resolve the robot pose in the map frame and activation fails — the
historical bringup failure of this project.
"""

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from indoor_nav_costmap.params_overlay import build_params
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    # Resolved from the installed package so the launch works from any clone
    # location (with --symlink-install this is the file in src/).
    committed_params = str(
        Path(get_package_share_directory("indoor_nav_costmap"))
        / "config"
        / "nav2_params.yaml"
    )
    # Phase 2: with FYP_REACTIVE_OBSTACLES set this returns a patched copy
    # that enables both costmaps' obstacle_layer from the live /scan. Without
    # it the committed file is returned unchanged, so Phase 1 is unaffected.
    params_file = build_params(committed_params)

    controller_params = [params_file]
    if os.environ.get("FYP_DEPTH_SOURCE", "phone") == "gazebo":
        # Simulation-only goal checker. nav2_params.yaml defines no goal
        # checker, so Nav2's default SimpleGoalChecker (xy 0.25 m) decides
        # SUCCEEDED; FollowPath.xy_goal_tolerance only feeds DWB's critics.
        # The robot stops as soon as the AMCL estimate is inside this radius,
        # so the true final error is up to (tolerance + localization error).
        # Measured AMCL error near the goal is ~5 cm (likelihood field scores
        # occupied-cell centres, 2.5 cm behind surfaces, plus ~1 cm
        # nearest-in-bin scan bias); 0.10 m left the true position 0.17 m
        # from the goal in two runs. 0.05 m keeps tolerance + error inside the
        # unchanged 0.15 m ground-truth acceptance.
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

    controller_server = Node(
        package="nav2_controller",
        executable="controller_server",
        name="controller_server",
        output="screen",
        parameters=controller_params,
        remappings=[("cmd_vel", "/cmd_vel")],
    )

    planner_server = Node(
        package="nav2_planner",
        executable="planner_server",
        name="planner_server",
        output="screen",
        parameters=[params_file],
    )

    behavior_server = Node(
        package="nav2_behaviors",
        executable="behavior_server",
        name="behavior_server",
        output="screen",
        parameters=[params_file],
        remappings=[("cmd_vel", "/cmd_vel")],
    )

    bt_navigator = Node(
        package="nav2_bt_navigator",
        executable="bt_navigator",
        name="bt_navigator",
        output="screen",
        parameters=[params_file],
    )

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
            navigation_manager,
        ]
    )
