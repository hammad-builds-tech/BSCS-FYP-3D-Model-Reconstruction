#!/usr/bin/env python3
"""Phase 3 — record the Collision Monitor's actual gating behaviour.

Subscribes to both ends of the velocity chain plus the monitor's own state
and the sensor it depends on, so a safety claim can be backed by measured
input/output pairs rather than by configuration.

    /cmd_vel_nav  (in)  <- controller_server / behavior_server
    /cmd_vel      (out) -> ros_gz_bridge -> Gazebo
    /collision_monitor_state
    /scan               <- the only observation source

Usage:
    python3 collision_monitor_probe.py --seconds 20 [--json out.json]

Reports, per window: command counts in/out, whether any outbound command
was non-zero while an inbound command was non-zero (i.e. pass-through), the
gating events (in != 0 while out == 0), scan rate, nearest scan return, and
every distinct monitor state with its action polygon.
"""

import argparse
import json
import time

import rclpy
from geometry_msgs.msg import Twist
from nav2_msgs.msg import CollisionMonitorState
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan

# CollisionMonitorState.action_type enum, per nav2_msgs
ACTION_NAMES = {0: "DO_NOTHING", 1: "STOP", 2: "SLOWDOWN", 3: "APPROACH", 4: "LIMIT"}


def magnitude(twist):
    return abs(twist.linear.x) + abs(twist.linear.y) + abs(twist.angular.z)


class Probe(Node):

    def __init__(self):
        super().__init__("collision_monitor_probe")
        sensor_qos = QoSProfile(
            depth=20,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
        )
        self.cmd_in = []
        self.cmd_out = []
        self.states = []
        self.scan_stamps = []
        self.scan_nearest = []
        self.create_subscription(Twist, "/cmd_vel_nav", self._in, 20)
        self.create_subscription(Twist, "/cmd_vel", self._out, 20)
        self.create_subscription(
            CollisionMonitorState, "/collision_monitor_state", self._state, 10
        )
        self.create_subscription(LaserScan, "/scan", self._scan, sensor_qos)

    def _in(self, msg):
        self.cmd_in.append((time.time(), magnitude(msg), msg.linear.x))

    def _out(self, msg):
        self.cmd_out.append((time.time(), magnitude(msg), msg.linear.x))

    def _state(self, msg):
        self.states.append(
            (time.time(), int(msg.action_type), str(msg.polygon_name))
        )

    def _scan(self, msg):
        self.scan_stamps.append(time.time())
        finite = [r for r in msg.ranges if r == r and r not in (float("inf"),)]
        self.scan_nearest.append(min(finite) if finite else float("inf"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--json")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    rclpy.init()
    probe = Probe()
    start = time.time()
    while time.time() - start < args.seconds:
        rclpy.spin_once(probe, timeout_sec=0.05)
    elapsed = time.time() - start

    moving_in = [c for c in probe.cmd_in if c[1] > 1e-6]
    moving_out = [c for c in probe.cmd_out if c[1] > 1e-6]
    zero_out = [c for c in probe.cmd_out if c[1] <= 1e-6]

    scan_hz = len(probe.scan_stamps) / elapsed if elapsed else 0.0
    nearest = min(probe.scan_nearest) if probe.scan_nearest else None

    seen_states = {}
    for _, action, poly in probe.states:
        seen_states.setdefault((action, poly), 0)
        seen_states[(action, poly)] += 1

    result = {
        "label": args.label,
        "window_s": round(elapsed, 2),
        "cmd_in_total": len(probe.cmd_in),
        "cmd_in_nonzero": len(moving_in),
        "cmd_out_total": len(probe.cmd_out),
        "cmd_out_nonzero": len(moving_out),
        "cmd_out_zero": len(zero_out),
        "scan_hz": round(scan_hz, 2),
        "scan_nearest_m": round(nearest, 3) if nearest not in (None, float("inf")) else None,
        "monitor_states": {
            f"{ACTION_NAMES.get(a, a)}|{p or '-'}": n for (a, p), n in seen_states.items()
        },
        "state_msgs": len(probe.states),
    }
    # Gating evidence: commands asked for motion but none came out.
    result["gated"] = bool(moving_in) and not moving_out
    result["passed_through"] = bool(moving_in) and bool(moving_out)

    print(json.dumps(result, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)

    probe.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
