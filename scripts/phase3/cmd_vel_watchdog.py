#!/usr/bin/env python3
"""Phase 3 — command watchdog for the Gazebo velocity interface.

WHY THIS EXISTS
---------------
`fyp_robot.sdf` drives the robot with `gz::sim::systems::VelocityControl`
(`gz-sim-velocity-control-system` 10.5.0). That plugin **latches the last
velocity command indefinitely**: it exposes no timeout element at all
(verified -- zero occurrences of "timeout" in
`libgz-sim-velocity-control-system.so.10.5.0`; the only SDF elements it
reads are `topic` and `link_name`). `DiffDrive` has no timeout either, and
no gz-sim 10.5.0 plugin exposes `cmd_vel_timeout`/`command_timeout`.

Measured consequence with nothing in the way (3 runs): after the publisher
stopped, the robot continued **2.78-2.81 m** over 10 s and was still moving.
Killing the Collision Monitor mid-motion let it travel 4.4 m.

Because the simulator cannot be made to time out, and because no SDF
parameter exists to add, a Phase 3 copy of the robot model would achieve
nothing. The gate has to live on the ROS side instead, as the LAST element
before the bridge:

    collision_monitor -> /cmd_vel_safe -> [this node] -> /cmd_vel -> ros_gz_bridge

Behaviour:
  * every message on the input topic is republished immediately (no added
    latency in the normal path);
  * if nothing arrives for `timeout` seconds, zero Twist messages are
    published continuously at `rate` Hz, which overwrites the plugin's
    latched command and brings the robot to rest;
  * zeros keep being published while the input stays silent, so a single
    dropped message cannot let a stale command resurface.

HONEST LIMITATION
-----------------
This node is now the last element in the chain, so if *it* dies the latch
problem returns. That cannot be fixed from ROS space: the simulator holds
the last command it received, whoever sent it. The watchdog converts the
realistic failures that were actually observed (Collision Monitor crash,
Nav2 crash, publisher stops) into a bounded stop. It is NOT an emergency
stop and must not be described as one.

It also cannot prevent a direct publish to the output topic: ROS 2 topics
are open. It does, however, keep asserting zeros, so a stale or hostile
command is overwritten within one watchdog period rather than persisting.
"""

import argparse
import sys

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy


class CmdVelWatchdog(Node):

    def __init__(self, in_topic, out_topic, timeout_s, rate_hz):
        super().__init__("cmd_vel_watchdog")
        self._timeout = float(timeout_s)
        self._last_rx = None          # ROS time of the last input message
        self._last_cmd_zero = True
        self._zero_bursts = 0
        self._forwarded = 0

        # Commands are control data: best-effort, shallow queue. A late
        # command is worse than a dropped one.
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._pub = self.create_publisher(Twist, out_topic, qos)
        self.create_subscription(Twist, in_topic, self._on_cmd, qos)
        self.create_timer(1.0 / float(rate_hz), self._tick)

        self.get_logger().info(
            "watchdog: %s -> %s, timeout %.2f s, zero-rate %.0f Hz"
            % (in_topic, out_topic, self._timeout, float(rate_hz))
        )
        # Assert a known-safe state at startup rather than inheriting
        # whatever the plugin was last told.
        self._publish_zero()

    def _on_cmd(self, msg):
        self._last_rx = self.get_clock().now()
        self._pub.publish(msg)
        self._forwarded += 1
        self._last_cmd_zero = (
            abs(msg.linear.x) + abs(msg.linear.y) + abs(msg.angular.z)
        ) < 1e-9

    def _publish_zero(self):
        self._pub.publish(Twist())

    def _tick(self):
        now = self.get_clock().now()
        if self._last_rx is None:
            # Nothing has ever arrived: hold the robot at rest.
            self._publish_zero()
            return
        age = (now - self._last_rx).nanoseconds * 1e-9
        if age > self._timeout:
            self._publish_zero()
            if self._zero_bursts == 0:
                self.get_logger().warning(
                    "input silent for %.2f s (> %.2f s timeout): "
                    "publishing zero velocity. Forwarded %d commands before "
                    "the gap." % (age, self._timeout, self._forwarded)
                )
            self._zero_bursts += 1
        elif self._zero_bursts:
            self.get_logger().info(
                "input resumed after %d zero publications" % self._zero_bursts
            )
            self._zero_bursts = 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-topic", default="/cmd_vel_safe")
    parser.add_argument("--out-topic", default="/cmd_vel")
    # Nav2's controller_frequency is 10.0 Hz and /cmd_vel_nav was measured at
    # 9.925 Hz, i.e. a ~0.10 s period. 0.50 s tolerates five consecutive
    # missed commands before zeroing, which at the Phase 3 cruise of
    # 0.45 m/s bounds post-loss travel to about 0.23 m.
    parser.add_argument("--timeout", type=float, default=0.5)
    parser.add_argument("--rate", type=float, default=20.0)
    # ROS injects its own args when launched; ignore the unknown ones.
    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    rclpy.init()
    node = CmdVelWatchdog(args.in_topic, args.out_topic, args.timeout, args.rate)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # Best effort: leave the robot commanded to stop on clean shutdown.
        try:
            node._publish_zero()
        except Exception:
            pass
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
