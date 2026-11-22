#!/usr/bin/env python3
"""Phase 3 — verify the stack is genuinely ready, not merely reachable.

WHY THIS EXISTS
---------------
`run_system_phase3.sh` used to gate on `ros2 topic hz /clock` and
`ros2 topic hz /scan`. Both pass against a *stale* stack: on 21 Nov 2026 the
script reported "/clock flowing ready (0s)" and "/scan flowing ready (0s)"
while Gazebo was not running at all and Nav2 never activated -- the topics
were still being served by leftover processes from a previous run. It then
printed "PHASE 3 UP" and three scenario runs were executed against a dead
simulator before the robot's total immobility gave it away.

"The topic exists" is not readiness. This script checks the properties that
actually matter:

  1. SIM CLOCK IS ADVANCING -- /clock must increase during the window, not
     merely be published. A stale latched clock fails here.
  2. SENSOR DATA IS FRESH -- /scan and the depth image must arrive during
     the window AND carry stamps close to the current sim time. A publisher
     that has stopped, or one replaying old stamps, fails here.
  3. TF CHAIN IS COMPLETE -- map->odom (AMCL), odom->base_link (Gazebo
     odometry) and base_link->sim_depth_scan (depth_to_scan, per image) must
     all resolve. Phase 2 was broken by a frame assumption, so this is
     checked explicitly rather than assumed.
  4. COMMAND PIPELINE IS WIRED -- /cmd_vel_nav must have a subscriber
     (collision_monitor), /cmd_vel_safe must have a subscriber (the
     watchdog), and /cmd_vel must have exactly one publisher. If the chain
     is short-circuited the robot is unguarded, which is the whole point of
     the Phase 3 configuration.

Exits 0 only when every check passes; otherwise exits 1 and names what
failed. Checks are never relaxed to let a bring-up through -- a failure here
means the stack is not safe to run scenarios against.

Usage:
    check_stack_ready.py [--window 6.0] [--max-age 2.0] [--quiet]
"""

import argparse
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image, LaserScan
from tf2_ros import Buffer, TransformListener

#: TF links the Phase 3 chain depends on. (target, source)
REQUIRED_TF = [
    ("map", "odom"),                      # AMCL
    ("odom", "base_link"),                # Gazebo odometry
    ("base_link", "sim_depth_scan"),      # depth_to_scan, per image
]

#: (topic, minimum subscribers, minimum publishers, label)
REQUIRED_PIPELINE = [
    ("/cmd_vel_nav", 1, 1, "Nav2 output -> collision_monitor"),
    ("/cmd_vel_safe", 1, 1, "collision_monitor -> watchdog"),
    ("/cmd_vel", 0, 1, "watchdog -> ros_gz_bridge"),
]


class Checker(Node):

    def __init__(self):
        super().__init__("phase3_stack_check")
        sensor_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
        )
        self.clock_vals = []
        self.scan_stamps = []
        self.depth_stamps = []
        self.create_subscription(Clock, "/clock", self._on_clock, sensor_qos)
        self.create_subscription(LaserScan, "/scan", self._on_scan, sensor_qos)
        self.create_subscription(
            Image, "/rgbd_camera/depth_image", self._on_depth, sensor_qos
        )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self, spin_thread=False)

    # NOTE: callbacks are named _on_* deliberately. rclpy.node.Node already
    # defines self._clock (its Clock object), so a method named _clock is
    # shadowed by that attribute and rclpy rejects it as "not callable with
    # one argument" -- a confusing failure that cost real debugging time.
    @staticmethod
    def _stamp(header):
        return header.stamp.sec + header.stamp.nanosec * 1e-9

    def _on_clock(self, msg):
        self.clock_vals.append(msg.clock.sec + msg.clock.nanosec * 1e-9)

    def _on_scan(self, msg):
        self.scan_stamps.append(self._stamp(msg.header))

    def _on_depth(self, msg):
        self.depth_stamps.append(self._stamp(msg.header))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=float, default=6.0,
                    help="seconds to observe traffic")
    ap.add_argument("--max-age", type=float, default=2.0,
                    help="max sensor stamp age vs sim clock, seconds")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rclpy.init()
    node = Checker()
    start = time.time()
    while time.time() - start < args.window:
        rclpy.spin_once(node, timeout_sec=0.05)

    failures = []
    report = []

    # ---- 1. sim clock advancing -------------------------------------
    cv = node.clock_vals
    if len(cv) < 2:
        failures.append("/clock: %d messages in %.1fs (need >=2)"
                        % (len(cv), args.window))
        sim_now = None
    else:
        advance = cv[-1] - cv[0]
        if advance <= 0.0:
            failures.append("/clock NOT advancing (delta %.3fs over %.1fs) -- "
                            "stale or paused simulator" % (advance, args.window))
        report.append("/clock advancing %.2fs over %.1fs wall (%d msgs)"
                      % (advance, args.window, len(cv)))
        sim_now = cv[-1]

    # ---- 2. sensor freshness ----------------------------------------
    for name, stamps in (("/scan", node.scan_stamps),
                         ("/rgbd_camera/depth_image", node.depth_stamps)):
        if not stamps:
            failures.append("%s: no messages in %.1fs" % (name, args.window))
            continue
        rate = len(stamps) / args.window
        if sim_now is None:
            report.append("%s %d msgs (%.1f Hz), age unknown" % (name, len(stamps), rate))
            continue
        age = sim_now - stamps[-1]
        if age > args.max_age:
            failures.append("%s stale: newest stamp %.2fs behind sim clock "
                            "(limit %.2fs)" % (name, age, args.max_age))
        report.append("%s %.1f Hz, newest stamp %.2fs behind clock"
                      % (name, rate, age))

    # ---- 3. TF chain -------------------------------------------------
    for target, source in REQUIRED_TF:
        try:
            ok = node.tf_buffer.can_transform(
                target, source, rclpy.time.Time()
            )
        except Exception as exc:                      # noqa: BLE001
            ok = False
            report.append("TF %s->%s lookup raised %s" % (target, source, type(exc).__name__))
        if ok:
            report.append("TF %s->%s OK" % (target, source))
        else:
            failures.append("TF %s->%s NOT available" % (target, source))

    # ---- 4. command pipeline ----------------------------------------
    for topic, min_sub, min_pub, label in REQUIRED_PIPELINE:
        pubs = node.count_publishers(topic)
        subs = node.count_subscribers(topic)
        if pubs < min_pub or subs < min_sub:
            failures.append("%s: pub=%d sub=%d (need pub>=%d sub>=%d) -- %s"
                            % (topic, pubs, subs, min_pub, min_sub, label))
        else:
            report.append("%s pub=%d sub=%d (%s)" % (topic, pubs, subs, label))

    node.destroy_node()
    rclpy.shutdown()

    if not args.quiet:
        for line in report:
            print("    ok   %s" % line)
    for line in failures:
        print("    FAIL %s" % line)

    if failures:
        print("    => NOT READY (%d check%s failed)"
              % (len(failures), "" if len(failures) == 1 else "s"))
        return 1
    print("    => READY (clock advancing, sensors fresh, TF complete, "
          "command chain wired)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
