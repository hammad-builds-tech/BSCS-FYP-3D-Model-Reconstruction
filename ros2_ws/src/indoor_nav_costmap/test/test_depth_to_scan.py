import numpy as np

from indoor_nav_costmap.depth_to_scan import DepthToScan


def test_inverse_midas_depth_maps_larger_values_closer():
    depth = np.tile(np.linspace(0.0, 255.0, 120), (40, 1))

    ranges = DepthToScan.ranges_from_relative_depth(
        depth,
        vertical_roi_top=0.20,
        vertical_roi_bottom=0.85,
        target_beams=12,
        min_range=0.15,
        clearing_max_range=3.5,
        inverse_depth=True,
    )

    assert len(ranges) == 12
    assert ranges[0] > ranges[-1]
    assert np.isclose(ranges[-1], 0.15)


def test_flat_relative_depth_clears_without_marking_an_obstacle():
    depth = np.full((40, 120), 127.0, dtype=np.float32)

    ranges = DepthToScan.ranges_from_relative_depth(
        depth,
        vertical_roi_top=0.20,
        vertical_roi_bottom=0.85,
        target_beams=12,
        min_range=0.15,
        clearing_max_range=3.5,
        inverse_depth=True,
    )

    assert np.allclose(ranges, 3.5)


def test_malformed_depth_has_no_scan_output():
    assert DepthToScan.ranges_from_relative_depth(
        np.zeros((4, 4, 3), dtype=np.float32),
        vertical_roi_top=0.20,
        vertical_roi_bottom=0.85,
        target_beams=12,
        min_range=0.15,
        clearing_max_range=3.5,
        inverse_depth=True,
    ) is None



# Intrinsics published by the Gazebo rgbd camera (CameraInfo K matrix).
FX = FY = 467.7427
CX, CY, W, H = 320.0, 240.0, 640, 480
ANGLE_MAX = np.arctan2(CX, FX)
ANGLE_MIN = -np.arctan2(W - 1 - CX, FX)
CAM_HEIGHT = 0.28  # camera height above the floor in the Gazebo spawn pose


def _render(scene_t, roll=0.0, pitch=0.0):
    """Ray-cast a synthetic metric depth image (optical depth along x).

    scene_t(origin, direction) returns the ray parameter of the first hit
    in the levelled frame (camera at origin), or inf.
    """
    v, u = np.mgrid[0:H, 0:W].astype(np.float64)
    d_cam = np.stack([np.ones_like(u), -(u - CX) / FX, -(v - CY) / FY], axis=-1)
    cr, sr, cp, sp = np.cos(roll), np.sin(roll), np.cos(pitch), np.sin(pitch)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    d_level = d_cam @ (ry @ rx).T
    t = scene_t(d_level)          # hit at t * d_level, and optical depth = t
    return np.where(np.isfinite(t) & (t > 0), t, np.inf).astype(np.float32)


def _floor_and_wall(wall_x):
    def scene(d):
        with np.errstate(divide="ignore", invalid="ignore"):
            t_floor = np.where(d[..., 2] < 0, -CAM_HEIGHT / d[..., 2], np.inf)
            t_wall = np.where(d[..., 0] > 0, wall_x / d[..., 0], np.inf)
        return np.minimum(t_floor, t_wall)
    return scene


def _scan(depth, roll=0.0, pitch=0.0, beams=121, min_e=0.02, max_e=0.15):
    return DepthToScan.levelled_scan_from_depth(
        depth, FX, FY, CX, CY, roll, pitch, min_e, max_e,
        ANGLE_MIN, ANGLE_MAX, beams, 0.15, 8.0,
    )


def test_level_camera_wall_is_at_true_horizontal_distance():
    ranges = _scan(_render(_floor_and_wall(3.0)))
    bearings = np.linspace(ANGLE_MIN, ANGLE_MAX, 121)
    # Every beam sees the wall plane x = 3 m: range = 3 / cos(bearing).
    assert np.allclose(ranges, 3.0 / np.cos(bearings), rtol=0.01)


def test_pitched_camera_does_not_report_the_floor_as_a_wall():
    # The Gazebo robot rests 4.35 deg nose-down: its centre rows see the floor
    # about 3.3 m ahead. With the tilt corrected, no floor return survives.
    pitch = np.deg2rad(4.35)
    floor_only = _render(_floor_and_wall(np.inf), pitch=pitch)
    assert np.isfinite(floor_only[240, 320])        # the image does see floor
    assert np.all(np.isinf(_scan(floor_only, pitch=pitch)))


def test_pitched_camera_still_sees_the_wall_at_the_right_distance():
    pitch = np.deg2rad(4.35)
    ranges = _scan(_render(_floor_and_wall(5.55), pitch=pitch), pitch=pitch)
    centre = len(ranges) // 2
    assert np.isclose(ranges[centre], 5.55, rtol=0.01)


def test_tilt_must_be_corrected_otherwise_floor_or_wrong_range_appears():
    # Same pitched image, but processed as if the camera were level:
    # floor points look horizontal and get reported as obstacles.
    pitch = np.deg2rad(4.35)
    floor_only = _render(_floor_and_wall(np.inf), pitch=pitch)
    wrong = _scan(floor_only, pitch=0.0, min_e=-0.02, max_e=0.02)
    assert np.any(np.isfinite(wrong))


def test_rolled_camera_keeps_left_obstacle_on_the_left():
    # Box face at x = 1.5 m only for y > 0.3 (robot's left), wall at 4 m.
    def scene(d):
        with np.errstate(divide="ignore", invalid="ignore"):
            t_box = np.where(d[..., 0] > 0, 1.5 / d[..., 0], np.inf)
            y_hit = t_box * d[..., 1]
            t_box = np.where(y_hit > 0.3, t_box, np.inf)
            t_wall = np.where(d[..., 0] > 0, 4.0 / d[..., 0], np.inf)
        return np.minimum(t_box, t_wall)
    roll = np.deg2rad(3.0)
    ranges = _scan(_render(scene, roll=roll), roll=roll)
    assert ranges[-1] < 2.0          # positive bearing (left): the box
    assert ranges[0] > 3.9           # negative bearing (right): the wall


def test_no_return_pixels_give_no_obstacle():
    depth = np.full((H, W), np.inf, dtype=np.float32)
    depth[200:280, 300:340] = -np.inf   # nearer than the near clip
    assert np.all(np.isinf(_scan(depth)))


def test_quaternion_roll_pitch():
    half = np.deg2rad(4.35) / 2.0
    roll, pitch = DepthToScan.roll_pitch_from_quaternion(0.0, np.sin(half), 0.0, np.cos(half))
    assert np.isclose(pitch, np.deg2rad(4.35)) and np.isclose(roll, 0.0)


def test_relative_scan_is_not_mirrored_left_right():
    """A near obstacle in the image's LEFT half must land at positive bearing.

    ranges_from_relative_depth returns image-column order (left -> right).
    A LaserScan runs angle_min -> angle_max, which is counter-clockwise in
    REP 103, so the last index is the robot's left. depth_callback therefore
    reverses the array before publishing. This test pins that orientation so
    it matches levelled_scan_from_depth (see
    test_rolled_camera_keeps_left_obstacle_on_the_left).
    """
    # Inverse MiDaS depth: larger value = closer. Put the close surface in
    # the left half of the image only.
    depth = np.full((40, 120), 10.0, dtype=np.float32)
    depth[:, :60] = 250.0

    column_order = DepthToScan.ranges_from_relative_depth(
        depth,
        vertical_roi_top=0.20,
        vertical_roi_bottom=0.85,
        target_beams=12,
        min_range=0.15,
        clearing_max_range=3.5,
        inverse_depth=True,
    )

    # In image-column order the near surface is in the first half.
    assert column_order[0] < column_order[-1]

    # As published (reversed), the near surface must be at the END of the
    # array, i.e. towards angle_max = the robot's left.
    published = column_order[::-1]
    assert published[-1] < published[0], "left obstacle must be at angle_max"
    half = len(published) // 2
    assert published[half:].min() < published[:half].min()
