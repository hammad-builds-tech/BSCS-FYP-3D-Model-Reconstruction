import math

import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from geometry_msgs.msg import TransformStamped
from sensor_msgs.msg import CameraInfo, Image, LaserScan
from cv_bridge import CvBridge
import numpy as np
from tf2_ros import Buffer, TransformBroadcaster, TransformException, TransformListener


class DepthToScan(Node):

    def __init__(self):
        super().__init__("depth_to_scan")

        self.bridge = CvBridge()

        self.declare_parameter("depth_topic", "/smartphone/depth")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("scan_frame_id", "base_link")
        self.declare_parameter("horizontal_fov_rad", 2.09439510239)
        self.declare_parameter("scan_yaw_offset_rad", 0.0)
        self.declare_parameter("vertical_roi_top", 0.20)
        self.declare_parameter("vertical_roi_bottom", 0.85)
        self.declare_parameter("target_beams", 120)
        self.declare_parameter("min_range", 0.15)
        self.declare_parameter("obstacle_max_range", 3.0)
        self.declare_parameter("clearing_max_range", 3.5)
        self.declare_parameter("inverse_depth", True)
        # MiDaS depth is RELATIVE: the nearest visible surface can only be
        # placed at some assumed metric distance. near_range_anchor is the
        # distance assigned to the closest 5th-percentile surface. Anchoring
        # it at min_range makes every indoor wall a bumper-distance obstacle
        # (navigation stalls); a moderate anchor stays conservative (reported
        # ranges are shorter than reality) yet allows forward progress.
        self.declare_parameter("near_range_anchor", 0.15)
        # "relative": MiDaS relative depth (smartphone path, default).
        # "metric": true depth in metres along the optical axis (32FC1), e.g.
        # the Gazebo depth camera. Every pixel is back-projected with the
        # camera's real intrinsics, rotated into a gravity-levelled frame and
        # binned into a horizontal planar scan (see levelled_scan_from_depth).
        self.declare_parameter("depth_mode", "relative")
        # --- metric mode only ---------------------------------------------
        self.declare_parameter("camera_info_topic", "/rgbd_camera/camera_info")
        # TF frame rigidly attached to the camera, REP 103 body axes
        # (x forward along the optical axis, y left, z up).
        self.declare_parameter("camera_frame", "sim_depth_camera")
        # Gravity-aligned frame used to measure the camera's roll and pitch
        # at each image's timestamp. "" assumes the camera is level.
        self.declare_parameter("level_reference_frame", "odom")
        # Vertical filter, as elevation angles above the horizontal plane
        # through the camera. A point is used only if its elevation lies in
        # [min, max]. With min > 0 every accepted ray rises, so it can never
        # reach the floor (floor points are always below the camera). At
        # horizontal distance d an accepted point lies between
        # d*tan(min) and d*tan(max) above the camera, so surfaces lower than
        # camera_height + d*tan(min) are not seen (walls and obstacles taller
        # than the camera are).
        self.declare_parameter("min_elevation_rad", 0.02)
        self.declare_parameter("max_elevation_rad", 0.15)
        self.declare_parameter("tf_timeout_s", 0.2)
        # Use every n-th pixel in u and v (1 = all pixels).
        self.declare_parameter("pixel_stride", 1)

        depth_topic = self.get_parameter("depth_topic").value
        scan_topic = self.get_parameter("scan_topic").value
        self.scan_frame_id = self.get_parameter("scan_frame_id").value
        self.horizontal_fov_rad = float(
            self.get_parameter("horizontal_fov_rad").value
        )
        self.scan_yaw_offset_rad = float(
            self.get_parameter("scan_yaw_offset_rad").value
        )
        self.vertical_roi_top = float(
            self.get_parameter("vertical_roi_top").value
        )
        self.vertical_roi_bottom = float(
            self.get_parameter("vertical_roi_bottom").value
        )
        self.target_beams = int(self.get_parameter("target_beams").value)
        self.min_range = float(self.get_parameter("min_range").value)
        self.obstacle_max_range = float(
            self.get_parameter("obstacle_max_range").value
        )
        self.clearing_max_range = float(
            self.get_parameter("clearing_max_range").value
        )
        self.inverse_depth = bool(self.get_parameter("inverse_depth").value)
        self.near_range_anchor = float(
            self.get_parameter("near_range_anchor").value
        )
        self.depth_mode = str(self.get_parameter("depth_mode").value)
        if self.depth_mode not in ("relative", "metric"):
            raise ValueError("depth_mode must be 'relative' or 'metric'")
        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.level_reference_frame = str(
            self.get_parameter("level_reference_frame").value
        )
        self.min_elevation = float(self.get_parameter("min_elevation_rad").value)
        self.max_elevation = float(self.get_parameter("max_elevation_rad").value)
        self.tf_timeout = Duration(
            seconds=float(self.get_parameter("tf_timeout_s").value)
        )
        self.pixel_stride = int(self.get_parameter("pixel_stride").value)
        self.intrinsics = None  # (fx, fy, cx, cy, width) from CameraInfo
        if self.depth_mode == "metric":
            if not (-math.pi / 2 < self.min_elevation < self.max_elevation < math.pi / 2):
                raise ValueError("elevation limits must satisfy -pi/2 < min < max < pi/2")
            if self.pixel_stride < 1:
                raise ValueError("pixel_stride must be >= 1")
            self.tf_buffer = Buffer()
            # TF callbacks live in the listener's own reentrant group; with the
            # MultiThreadedExecutor in main() they keep filling the buffer while
            # a depth callback waits for the transform at its image time.
            self.tf_listener = TransformListener(self.tf_buffer, self)
            self.tf_broadcaster = TransformBroadcaster(self)
            self.create_subscription(
                CameraInfo,
                str(self.get_parameter("camera_info_topic").value),
                self.camera_info_callback,
                qos_profile_sensor_data,
            )

        if not (
            0.0 <= self.vertical_roi_top < self.vertical_roi_bottom <= 1.0
        ):
            raise ValueError("vertical ROI fractions must satisfy 0 <= top < bottom <= 1")
        if self.horizontal_fov_rad <= 0.0 or self.target_beams < 2:
            raise ValueError("horizontal FOV must be positive and target_beams must be at least 2")
        if not (
            0.0 < self.min_range < self.obstacle_max_range < self.clearing_max_range
        ):
            raise ValueError(
                "range limits must satisfy 0 < min < obstacle_max < clearing_max"
            )
        if not (
            self.min_range <= self.near_range_anchor <= self.clearing_max_range
        ):
            raise ValueError(
                "near_range_anchor must lie within [min_range, clearing_max_range]"
            )

        self.sub = self.create_subscription(
            Image,
            depth_topic,
            self.depth_callback,
            qos_profile_sensor_data,
            callback_group=MutuallyExclusiveCallbackGroup(),
        )

        self.pub = self.create_publisher(
            LaserScan,
            scan_topic,
            qos_profile_sensor_data,
        )

        self.get_logger().info(
            f"DepthToScan ready: {depth_topic} -> {scan_topic} "
            f"in {self.scan_frame_id}"
        )

    @staticmethod
    def ranges_from_relative_depth(
        depth,
        vertical_roi_top,
        vertical_roi_bottom,
        target_beams,
        min_range,
        clearing_max_range,
        inverse_depth,
        near_range_anchor=None,
    ):
        """Convert a MiDaS relative-depth image into conservative scan ranges.

        MiDaS returns inverse relative depth: larger values are closer. The
        conversion preserves the nearest value in each output beam so a narrow
        obstacle cannot disappear when the image is downsampled.

        near_range_anchor is the metric distance assigned to the nearest
        visible surface. It defaults to min_range (legacy behaviour) when not
        supplied, e.g. by older unit-test callers.
        """
        depth = np.asarray(depth, dtype=np.float32)
        if depth.ndim != 2:
            return None

        height, width = depth.shape
        if height < 2 or width < 2:
            return None

        y1 = int(height * vertical_roi_top)
        y2 = int(height * vertical_roi_bottom)
        if y2 <= y1:
            return None

        column_depth = np.nanmedian(depth[y1:y2, :], axis=0)
        valid = column_depth[np.isfinite(column_depth)]
        beam_count = min(target_beams, width)

        if valid.size < 2:
            return np.full(beam_count, clearing_max_range, dtype=np.float32)

        low = float(np.percentile(valid, 5))
        high = float(np.percentile(valid, 95))
        if high - low < 1e-6:
            return np.full(beam_count, clearing_max_range, dtype=np.float32)

        # Anchor the nearest visible surface at near_range_anchor instead of
        # min_range: MiDaS depth is relative, so "closest" has no absolute
        # metric meaning. Pinning it at min_range makes every wall a
        # bumper-distance obstacle; a moderate anchor keeps every reported
        # range an underestimate of the true scene geometry (conservative)
        # while remaining navigable. The farthest surface maps to
        # clearing_max_range.
        nearest = (
            min_range
            if near_range_anchor is None
            else min(max(float(near_range_anchor), min_range), clearing_max_range)
        )
        normalized = np.clip((column_depth - low) / (high - low), 0.0, 1.0)
        if inverse_depth:
            ranges = clearing_max_range - normalized * (
                clearing_max_range - nearest
            )
        else:
            ranges = nearest + normalized * (
                clearing_max_range - nearest
            )
        ranges[~np.isfinite(ranges)] = clearing_max_range

        # Keep the nearest range in each angular bucket to avoid missing a
        # thin obstacle between evenly spaced image samples.
        edges = np.linspace(0, width, beam_count + 1, dtype=np.int32)
        downsampled = np.empty(beam_count, dtype=np.float32)
        for index in range(beam_count):
            start, end = edges[index], edges[index + 1]
            downsampled[index] = np.min(ranges[start:end])

        return np.clip(downsampled, min_range, clearing_max_range)

    @staticmethod
    def levelled_scan_from_depth(
        depth,
        fx,
        fy,
        cx,
        cy,
        roll,
        pitch,
        min_elevation,
        max_elevation,
        angle_min,
        angle_max,
        beam_count,
        min_range,
        max_range,
        stride=1,
    ):
        """Turn a metric depth image into a horizontal planar scan.

        1. Back-project every pixel (u, v) with optical depth z through the
           pinhole model into the camera body frame (x forward, y left, z up):
           x = z, y = -(u - cx) z / fx, h = -(v - cy) z / fy.
        2. Rotate by the camera's roll and pitch, p' = Ry(pitch) Rx(roll) p,
           into the levelled frame: same origin and heading as the camera,
           z aligned with gravity.
        3. Keep points whose elevation angle lies in
           [min_elevation, max_elevation] and whose horizontal distance lies
           in [min_range, max_range].
        4. Bin by horizontal bearing atan2(y', x'); each bin keeps its
           nearest horizontal distance. Empty bins are +inf (REP 117: no
           return within range).
        Non-finite or non-positive depths (no return / nearer than the near
        clip) carry no distance and are ignored.
        """
        depth = np.asarray(depth, dtype=np.float32)
        if depth.ndim != 2 or depth.shape[0] < 2 or depth.shape[1] < 2:
            return None
        if beam_count < 2 or not angle_min < angle_max:
            return None

        z = depth[::stride, ::stride].astype(np.float64)
        v, u = np.mgrid[0:depth.shape[0]:stride, 0:depth.shape[1]:stride]
        valid = np.isfinite(z) & (z > 0.0)
        z = np.where(valid, z, 0.0)

        x = z
        y = -(u - cx) * z / fx
        h = -(v - cy) * z / fy

        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        y_r = cr * y - sr * h          # Rx(roll)
        h_r = sr * y + cr * h
        x_l = cp * x + sp * h_r        # Ry(pitch)
        h_l = -sp * x + cp * h_r
        y_l = y_r

        horizontal = np.hypot(x_l, y_l)
        elevation = np.arctan2(h_l, horizontal)
        bearing = np.arctan2(y_l, x_l)
        keep = (
            valid
            & (elevation >= min_elevation)
            & (elevation <= max_elevation)
            & (horizontal >= min_range)
            & (horizontal <= max_range)
            & (bearing >= angle_min)
            & (bearing <= angle_max)
        )

        increment = (angle_max - angle_min) / (beam_count - 1)
        index = np.rint((bearing[keep] - angle_min) / increment).astype(np.int64)
        ranges = np.full(beam_count, np.inf, dtype=np.float64)
        np.minimum.at(ranges, np.clip(index, 0, beam_count - 1), horizontal[keep])
        return ranges.astype(np.float32)

    @staticmethod
    def roll_pitch_from_quaternion(qx, qy, qz, qw):
        """Roll and pitch of a ZYX (yaw-pitch-roll) rotation, in radians."""
        roll = math.atan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
        pitch = math.asin(max(-1.0, min(1.0, 2.0 * (qw * qy - qz * qx))))
        return roll, pitch

    def camera_info_callback(self, msg):
        k = msg.k
        if k[0] <= 0.0 or k[4] <= 0.0:
            return
        intrinsics = (float(k[0]), float(k[4]), float(k[2]), float(k[5]), int(msg.width))
        if intrinsics != self.intrinsics:
            self.intrinsics = intrinsics
            self.get_logger().info(
                "camera intrinsics fx=%.2f fy=%.2f cx=%.1f cy=%.1f width=%d" % intrinsics
            )

    def publish_metric_scan(self, msg, depth):
        if self.intrinsics is None:
            self.get_logger().warning(
                "no CameraInfo yet; skipping depth image", throttle_duration_sec=5.0
            )
            return
        fx, fy, cx, cy, width = self.intrinsics

        roll = pitch = 0.0
        if self.level_reference_frame:
            try:
                # Camera attitude at the image's own acquisition time.
                tf = self.tf_buffer.lookup_transform(
                    self.level_reference_frame,
                    self.camera_frame,
                    Time.from_msg(msg.header.stamp),
                    timeout=self.tf_timeout,
                )
            except TransformException as exc:
                self.get_logger().warning(
                    f"no {self.level_reference_frame}->{self.camera_frame} TF at image time: {exc}",
                    throttle_duration_sec=5.0,
                )
                return
            q = tf.transform.rotation
            roll, pitch = self.roll_pitch_from_quaternion(q.x, q.y, q.z, q.w)

        # Bearing limits of the image's left/right edge columns.
        angle_max = math.atan2(cx, fx)
        angle_min = -math.atan2(width - 1 - cx, fx)
        ranges = self.levelled_scan_from_depth(
            depth, fx, fy, cx, cy, roll, pitch,
            self.min_elevation, self.max_elevation,
            angle_min, angle_max, self.target_beams,
            self.min_range, self.clearing_max_range, self.pixel_stride,
        )
        if ranges is None:
            self.get_logger().warning("Ignoring malformed metric depth image")
            return

        # Levelled frame = camera frame with roll and pitch undone:
        # R(camera -> levelled) = (Ry(pitch) Rx(roll))^T = Rx(-roll) Ry(-pitch).
        cr, sr = math.cos(-roll / 2.0), math.sin(-roll / 2.0)
        cp, sp = math.cos(-pitch / 2.0), math.sin(-pitch / 2.0)
        level_tf = TransformStamped()
        level_tf.header.stamp = msg.header.stamp
        level_tf.header.frame_id = self.camera_frame
        level_tf.child_frame_id = self.scan_frame_id
        level_tf.transform.rotation.w = cr * cp
        level_tf.transform.rotation.x = sr * cp
        level_tf.transform.rotation.y = cr * sp
        level_tf.transform.rotation.z = sr * sp
        self.tf_broadcaster.sendTransform(level_tf)

        scan = LaserScan()
        scan.header.stamp = msg.header.stamp
        scan.header.frame_id = self.scan_frame_id
        scan.angle_min = angle_min
        scan.angle_max = angle_max
        scan.angle_increment = (angle_max - angle_min) / (len(ranges) - 1)
        scan.time_increment = 0.0
        scan.scan_time = 0.0
        scan.range_min = self.min_range
        scan.range_max = self.clearing_max_range
        scan.ranges = ranges.tolist()
        self.pub.publish(scan)

    def depth_callback(self, msg):
        try:
            depth = self.bridge.imgmsg_to_cv2(
                msg,
                desired_encoding="passthrough",
            )
            if self.depth_mode == "metric":
                self.publish_metric_scan(msg, depth)
                return
            ranges = self.ranges_from_relative_depth(
                depth,
                self.vertical_roi_top,
                self.vertical_roi_bottom,
                self.target_beams,
                self.min_range,
                self.clearing_max_range,
                self.inverse_depth,
                self.near_range_anchor,
            )
            if ranges is None:
                self.get_logger().warning("Ignoring malformed MiDaS depth image")
                return

            scan = LaserScan()
            if msg.header.stamp.sec or msg.header.stamp.nanosec:
                scan.header.stamp = msg.header.stamp
            else:
                scan.header.stamp = self.get_clock().now().to_msg()
            scan.header.frame_id = self.scan_frame_id
            scan.angle_min = (
                self.scan_yaw_offset_rad - self.horizontal_fov_rad / 2.0
            )
            scan.angle_max = (
                self.scan_yaw_offset_rad + self.horizontal_fov_rad / 2.0
            )
            scan.angle_increment = (
                scan.angle_max - scan.angle_min
            ) / (len(ranges) - 1)
            scan.time_increment = 0.0
            scan.scan_time = 0.0
            scan.range_min = self.min_range
            scan.range_max = self.clearing_max_range
            # ranges_from_relative_depth returns one value per image column,
            # ordered left -> right of the image. A LaserScan is ordered from
            # angle_min to angle_max, i.e. counter-clockwise in REP 103 (x
            # forward, y left), so index 0 is the *rightmost* bearing and the
            # last index is the leftmost. The image's left column therefore
            # belongs at the end of the array, not the start: publishing the
            # column order directly mirrors the scan left/right. The metric
            # path bins by bearing and is unaffected (see
            # levelled_scan_from_depth).
            scan.ranges = ranges[::-1].tolist()
            self.pub.publish(scan)

        except (ValueError, TypeError) as exc:
            self.get_logger().warning(f"DepthToScan conversion error: {exc}")


def main(args=None):

    rclpy.init(args=args)

    node = DepthToScan()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
