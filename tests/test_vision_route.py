import pytest
from types import SimpleNamespace

from vision_route import (
    NEUTRAL_PWM,
    CoursePhase,
    CourseRouteConfig,
    CourseRouteController,
    Detection,
    GateFeature,
    GateTracker,
    PatternMatcher,
    PatternSignature,
    RouteConfig,
    RouteController,
    RouteState,
    SearchConfig,
    ThrottleConfig,
    VisualSearchController,
    VisualGateCentering,
    VisualGateCorrectionConfig,
    VisualTargetTracker,
    VisualThrottleController,
    compute_visual_throttle_pwm,
    select_visual_gate_pair,
    signed_heading_error,
)
from vision_test import CourseAutopilot, detect_marker_boxes, vfr_hud_heading


def test_signed_heading_error_wraps_at_north():
    assert signed_heading_error(1.0, 359.0) == 2.0
    assert signed_heading_error(359.0, 1.0) == -2.0


def test_controller_starts_in_visual_track():
    controller = RouteController(RouteConfig())
    decision = controller.step([], frame_width=640, heading_deg=0.0, now=0.0)
    assert decision.state is RouteState.VISUAL_TRACK
    assert decision.steering_pwm == 1500
    assert decision.throttle_pwm == 1500


def test_visual_search_sweeps_while_advancing_slowly() -> None:
    search = VisualSearchController(SearchConfig(center_pwm=1500, max_delta=100, period_s=8.0, throttle_pwm=1535))
    assert search.config.throttle_pwm == 1535

    assert search.update(now=0.0) == (1500, 1535)
    assert search.update(now=2.0) == (1400, 1535)
    assert search.update(now=4.0) == (1500, 1535)
    assert search.update(now=6.0) == (1600, 1535)
    assert search.active is True

    search.reset()
    assert search.active is False
    assert search.update(now=20.0) == (1500, 1535)

def det(label, x, y, confidence=0.9):
    return Detection(label, confidence, x, y, 20.0, 20.0)


def feature(name, x, y):
    return GateFeature(name=name, center_x_norm=x, center_y_norm=y)


def test_gate_requires_red_and_green():
    tracker = GateTracker(crossing_y=0.70, cooldown_s=1.0)
    assert tracker.update(
        [det("red_buoy", 300, 300)],
        frame_width=640,
        frame_height=640,
        now=0.0,
    ) is None


def test_gate_event_is_emitted_once_after_crossing():
    tracker = GateTracker(crossing_y=0.70, cooldown_s=1.0)
    pair = [det("red_buoy", 280, 200), det("green_buoy", 360, 200)]
    crossed = [det("red_buoy", 280, 500), det("green_buoy", 360, 500)]
    assert tracker.update(
        pair,
        frame_width=640,
        frame_height=640,
        now=0.0,
    ) is None
    event = tracker.update(
        crossed,
        frame_width=640,
        frame_height=640,
        now=0.2,
    )
    assert event is not None
    assert tracker.update(
        crossed,
        frame_width=640,
        frame_height=640,
        now=0.3,
    ) is None


def test_first_3x3_signature_matches_ordered_route_features():
    signature = PatternSignature(
        name="first_3x3",
        required_features=(
            feature("entry", 0.25, 0.30),
            feature("middle", 0.50, 0.50),
            feature("exit", 0.75, 0.70),
        ),
        tolerance=0.20,
    )
    matcher = PatternMatcher(signature)
    assert matcher.observe(feature("entry", 0.24, 0.31)) is None
    assert matcher.observe(feature("middle", 0.49, 0.51)) is None
    assert matcher.observe(feature("exit", 0.76, 0.69)) == "first_3x3"


def test_vfr_hud_heading_returns_normalized_heading():
    assert vfr_hud_heading(SimpleNamespace(heading=271)) == 271.0
    assert vfr_hud_heading(SimpleNamespace(heading=-1)) == 359.0


def test_vfr_hud_heading_returns_none_without_field():
    assert vfr_hud_heading(SimpleNamespace()) is None


def make_controller(**config_overrides):
    return RouteController(RouteConfig(**config_overrides))


def enter_survey(**config_overrides):
    controller = make_controller(**config_overrides)
    controller.step(
        [],
        frame_width=640,
        heading_deg=0.0,
        now=0.0,
        checkpoint_name="first_3x3",
    )
    controller.step([], frame_width=640, heading_deg=90.0, now=1.0)
    assert controller.state is RouteState.SURVEY_SEARCH
    return controller


def test_checkpoint_enters_blind_turn_once():
    controller = make_controller()
    decision = controller.step(
        [],
        frame_width=640,
        heading_deg=0.0,
        now=0.0,
        checkpoint_name="first_3x3",
    )
    assert decision.state is RouteState.BLIND_TURN
    assert decision.event == "checkpoint_first_3x3"


def test_blind_turn_enters_survey_at_target_heading():
    controller = make_controller()
    controller.step(
        [],
        frame_width=640,
        heading_deg=0.0,
        now=0.0,
        checkpoint_name="first_3x3",
    )
    decision = controller.step([], frame_width=640, heading_deg=85.0, now=2.0)
    assert decision.state is RouteState.SURVEY_SEARCH
    assert decision.throttle_pwm == controller.config.survey_throttle_pwm


def test_survey_requires_both_colors_for_reacquisition():
    controller = enter_survey(reacquire_frames=2)
    one_color = [det("red_buoy", 320, 300)]
    decision = controller.step(one_color, frame_width=640, heading_deg=90.0, now=1.1)
    assert decision.state is RouteState.SURVEY_SEARCH


def test_survey_resumes_visual_track_after_stable_pair():
    controller = enter_survey(reacquire_frames=2)
    pair = [det("red_buoy", 280, 300), det("green_buoy", 360, 300)]
    controller.step(pair, frame_width=640, heading_deg=90.0, now=1.1)
    decision = controller.step(pair, frame_width=640, heading_deg=90.0, now=1.2)
    assert decision.state is RouteState.VISUAL_TRACK


def test_survey_timeout_fails_safe():
    controller = enter_survey(survey_timeout_s=2.0)
    decision = controller.step([], frame_width=640, heading_deg=90.0, now=3.1)
    assert decision.state is RouteState.FAILSAFE
    assert decision.throttle_pwm == 1500
    assert decision.steering_pwm == 1500


def test_select_target_x_pair_and_single_buoy_offset():
    from vision_route import select_target_x
    # Red & Green pair -> midpoint
    pair = [det("red_buoy", 280, 300), det("green_buoy", 360, 300)]
    assert select_target_x(pair) == 320.0

    # KKI convention: Red buoy is on the left -> search right for corridor
    red_only = [det("red_buoy", 200, 300)]
    assert select_target_x(red_only) == 310.0

    # Green buoy is on the right -> search left for corridor
    green_only = [det("green_buoy", 400, 300)]
    assert select_target_x(green_only) == 290.0

def throttle_det(width: float, height: float, label: str = "red_buoy") -> Detection:
    return Detection(label, 0.9, 320.0, 240.0, width, height)


def test_visual_throttle_maps_area_and_steering_boost() -> None:
    assert (
        compute_visual_throttle_pwm(
            [throttle_det(40.0, 40.0)],
            640,
            480,
            1500,
        )
        == 1600
    )
    assert (
        compute_visual_throttle_pwm(
            [throttle_det(160.0, 120.0)],
            640,
            480,
            1500,
        )
        == 1560
    )
    assert (
        compute_visual_throttle_pwm(
            [throttle_det(400.0, 160.0)],
            640,
            480,
            1500,
        )
        == 1540
    )
    assert (
        compute_visual_throttle_pwm(
            [throttle_det(160.0, 120.0)],
            640,
            480,
            1750,
        )
        == 1580
    )
    assert (
        compute_visual_throttle_pwm(
            [throttle_det(160.0, 120.0, label="boat")],
            640,
            480,
            1500,
        )
        == 1500
    )


@pytest.mark.parametrize(
    ("frame_width", "frame_height"),
    [(0, 480), (640, 0), (-1, 480)],
)
def test_visual_throttle_rejects_non_positive_frame(
    frame_width: int,
    frame_height: int,
) -> None:
    with pytest.raises(ValueError, match="frame"):
        compute_visual_throttle_pwm([], frame_width, frame_height, 1500)


def test_visual_throttle_rejects_out_of_range_steering() -> None:
    with pytest.raises(ValueError, match="steering_pwm"):
        compute_visual_throttle_pwm([], 640, 480, 999)


def test_throttle_config_rejects_invalid_pwm_order() -> None:
    with pytest.raises(ValueError, match="near_pwm"):
        ThrottleConfig(near_pwm=1600, cruise_pwm=1550)


def test_visual_throttle_controller_ramps_holds_and_decays() -> None:
    controller = VisualThrottleController(
        ThrottleConfig(hold_s=0.8, ramp_pwm_per_s=200.0)
    )
    far = [throttle_det(40.0, 40.0)]

    assert (
        controller.update(
            far,
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=0.0,
        )
        == 1500
    )
    assert (
        controller.update(
            far,
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=0.25,
        )
        == 1550
    )
    assert (
        controller.update(
            far,
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=0.50,
        )
        == 1600
    )
    assert (
        controller.update(
            [],
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=1.00,
        )
        == 1600
    )
    assert (
        controller.update(
            [],
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=1.40,
        )
        == 1520
    )
    assert (
        controller.update(
            [],
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=1.50,
        )
        == 1500
    )
    assert controller.reset(now=2.0) == 1500
    assert (
        controller.update(
            [],
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=2.1,
        )
        == 1500
    )


def test_route_config_visual_throttle_is_above_neutral() -> None:
    assert RouteConfig().visual_throttle_pwm == 1560


def test_visual_throttle_keeps_ramping_last_target_during_hold() -> None:
    controller = VisualThrottleController(
        ThrottleConfig(hold_s=0.8, ramp_pwm_per_s=200.0)
    )
    far = [throttle_det(40.0, 40.0)]

    assert (
        controller.update(
            far,
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=0.0,
        )
        == 1500
    )
    assert (
        controller.update(
            [],
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=0.25,
        )
        == 1550
    )
    assert (
        controller.update(
            [],
            frame_width=640,
            frame_height=480,
            steering_pwm=1500,
            now=0.50,
        )
        == 1600
    )


def test_visual_target_tracker_holds_pair_midpoint_when_buoy_is_missing() -> None:
    tracker = VisualTargetTracker(hold_s=0.8, smoothing_alpha=1.0)
    pair = [
        Detection("red_buoy", 0.9, 200.0, 240.0, 40.0, 40.0),
        Detection("green_buoy", 0.9, 440.0, 240.0, 40.0, 40.0),
    ]

    assert tracker.update(pair, now=0.0) == 320.0
    assert tracker.update([pair[0]], now=0.2) == 320.0
    assert tracker.update([pair[1]], now=0.4) == 320.0
    assert tracker.update([pair[0]], now=0.9) == 310.0


def test_visual_target_tracker_smooths_pair_midpoint_motion() -> None:
    tracker = VisualTargetTracker(hold_s=0.8, smoothing_alpha=0.5)
    first_pair = [
        Detection("red_buoy", 0.9, 200.0, 240.0, 40.0, 40.0),
        Detection("green_buoy", 0.9, 440.0, 240.0, 40.0, 40.0),
    ]
    second_pair = [
        Detection("red_buoy", 0.9, 240.0, 240.0, 40.0, 40.0),
        Detection("green_buoy", 0.9, 480.0, 240.0, 40.0, 40.0),
    ]

    assert tracker.update(first_pair, now=0.0) == 320.0
    assert tracker.update(second_pair, now=0.2) == 340.0


def test_visual_target_tracker_uses_mirrored_pair_order_for_arena_b() -> None:
    tracker = VisualTargetTracker(
        hold_s=0.8,
        smoothing_alpha=1.0,
        red_on_left=False,
    )
    pair = [
        Detection("green_buoy", 0.9, 180.0, 280.0, 40.0, 50.0),
        Detection("red_buoy", 0.9, 460.0, 282.0, 42.0, 52.0),
    ]
    assert (
        tracker.update(
            pair,
            now=0.0,
            frame_width=640,
            frame_height=480,
        )
        == 320.0
    )


def test_course_route_targets_each_gate_center_in_order() -> None:
    controller = CourseRouteController()
    expected = [
        (11.0, -6.0),
        (9.0, 0.0),
        (11.0, 6.0),
        (6.0, 10.0),
        (2.0, 10.0),
        (-2.0, 10.0),
        (-6.0, 10.0),
        (-11.0, 6.0),
        (-9.0, 0.0),
        (-11.3, -6.0),
    ]
    for gate_count, waypoint in enumerate(expected):
        decision = controller.step(
            gate_count=gate_count,
            x=0.0,
            y=0.0,
            heading_deg=0.0,
        )
        assert decision.target_waypoint == waypoint
        assert decision.gate_count == gate_count
        assert decision.finished is False


def test_course_route_uses_fixed_blind_left_turn_headings_for_arena_a() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=6.0, heading_deg=0.0)
    top_turn = controller.step(gate_count=3, x=11.0, y=6.0, heading_deg=0.0)
    assert top_turn.phase is CoursePhase.TURN
    for _ in range(8):
        top_turn = controller.step(gate_count=3, x=11.0, y=6.0, heading_deg=0.0)
    assert top_turn.target_heading_deg == pytest.approx(309.0)

    controller.step(gate_count=6, x=-2.0, y=10.0, heading_deg=270.0)
    left_turn = controller.step(gate_count=7, x=-6.0, y=10.0, heading_deg=270.0)
    assert left_turn.phase is CoursePhase.TURN
    for _ in range(16):
        left_turn = controller.step(gate_count=7, x=-6.0, y=10.0, heading_deg=270.0)
    assert left_turn.target_heading_deg == pytest.approx(231.0)


def test_course_route_mirrors_blind_turn_headings_for_arena_b() -> None:
    controller = CourseRouteController(CourseRouteConfig(arena="B"))
    decision = controller.step(gate_count=3, x=19.0, y=6.0, heading_deg=0.0)
    for _ in range(8):
        decision = controller.step(gate_count=3, x=19.0, y=6.0, heading_deg=0.0)
    assert decision.target_heading_deg == pytest.approx(51.0)


def test_blind_turn_commits_and_starts_forward_capture_at_gate_three_entry() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=5.9, heading_deg=12.0)
    decision = controller.step(
        gate_count=3,
        x=11.2,
        y=6.0,
        heading_deg=12.0,
        speed_mps=0.12,
    )
    assert decision.phase is CoursePhase.TURN
    assert decision.target_heading_deg == pytest.approx(309.0)
    # Gate 3 starts with a bounded pivot brake.  Reverse thrust mirrors the
    # azimuth so the resulting yaw is still left, while forward momentum is
    # removed before the hard-left pulse begins.
    assert decision.throttle_pwm == CourseRouteConfig().course_turn_brake_pwm
    assert decision.steering_pwm == 1900


def test_blind_turn_stays_straight_before_gate_three_line() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=1, x=9.0, y=0.0, heading_deg=0.0)
    decision = controller.step(
        gate_count=2,
        x=11.1,
        y=5.20,
        heading_deg=12.0,
        speed_mps=0.12,
    )
    assert decision.phase is CoursePhase.APPROACH
    assert decision.target_waypoint == (11.0, 6.0)
    # The blind manoeuvre is not armed until Gate 3 is actually crossed.
    # Before that line the hull keeps the direct bearing to the visible gate;
    # a stale camera frame must not start the hard-left pivot early.
    assert decision.steering_pwm != 1100
    assert decision.throttle_pwm >= CourseRouteConfig().approach_pwm


def test_blind_turn_releases_pivot_brake_into_forward_kick() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=5.9, heading_deg=20.0)
    decision = controller.step(
        gate_count=3,
        x=10.9,
        y=7.0,
        heading_deg=25.0,
        speed_mps=0.22,
        now_s=2.0,
    )
    assert decision.phase is CoursePhase.TURN
    # The brake is still active immediately after Gate 3.
    assert decision.throttle_pwm == CourseRouteConfig().course_turn_brake_pwm
    assert decision.steering_pwm == 1900
    captured = controller.step(
        gate_count=3,
        x=10.8,
        y=7.5,
        heading_deg=309.0,
        speed_mps=0.20,
        now_s=3.0,
    )
    # Once the heading is already captured, the high-thrust pivot is released
    # and the bounded heading/lane correction takes over.
    assert captured.steering_pwm != 1100
    assert captured.throttle_pwm < CourseRouteConfig().blind_pivot_pwm


def test_gate_three_uses_short_high_thrust_pivot_burst() -> None:
    config = CourseRouteConfig()
    controller = CourseRouteController(config)
    controller.step(
        gate_count=2,
        x=11.0,
        y=5.9,
        heading_deg=20.0,
        speed_mps=0.20,
        now_s=0.0,
    )
    brake = controller.step(
        gate_count=3,
        x=11.0,
        y=6.0,
        heading_deg=20.0,
        speed_mps=0.20,
        now_s=0.0,
    )
    assert config.course_turn_brake_duration_s == pytest.approx(0.25)
    assert brake.throttle_pwm == config.course_turn_brake_pwm

    pivot = controller.step(
        gate_count=3,
        x=10.9,
        y=6.2,
        heading_deg=20.0,
        speed_mps=0.05,
        yaw_rate_dps=0.0,
        now_s=0.30,
    )
    assert pivot.steering_pwm == 1100
    assert pivot.throttle_pwm == config.blind_pivot_pwm == 1780
    assert pivot.avoidance_reason == "BLIND_LEFT_PIVOT"


def test_gate_three_pivot_reduces_thrust_near_outside_green_buoy() -> None:
    config = CourseRouteConfig()
    controller = CourseRouteController(config)
    controller.step(
        gate_count=2,
        x=11.0,
        y=5.9,
        heading_deg=20.0,
        now_s=0.0,
    )
    controller.step(
        gate_count=3,
        x=11.0,
        y=6.0,
        heading_deg=20.0,
        now_s=0.0,
    )
    near_green = controller.step(
        gate_count=3,
        x=11.5,
        y=6.2,
        heading_deg=20.0,
        speed_mps=0.05,
        yaw_rate_dps=0.0,
        now_s=0.30,
    )
    assert near_green.steering_pwm == 1100
    assert near_green.throttle_pwm == config.blind_turn_kick_pwm
    assert near_green.throttle_pwm < config.blind_pivot_pwm


def test_gate_three_pivot_extends_only_below_yaw_rate_target_and_is_bounded() -> None:
    config = CourseRouteConfig()
    controller = CourseRouteController(config)
    controller.step(
        gate_count=2,
        x=11.0,
        y=5.9,
        heading_deg=20.0,
        now_s=0.0,
    )
    controller.step(
        gate_count=3,
        x=11.0,
        y=6.0,
        heading_deg=20.0,
        now_s=0.0,
    )
    extended = controller.step(
        gate_count=3,
        x=10.5,
        y=6.6,
        heading_deg=20.0,
        yaw_rate_dps=0.0,
        now_s=0.72,
    )
    assert extended.steering_pwm == 1100
    assert extended.throttle_pwm == config.blind_pivot_pwm

    ended = controller.step(
        gate_count=3,
        x=10.3,
        y=6.8,
        heading_deg=20.0,
        yaw_rate_dps=0.0,
        now_s=1.02,
    )
    assert ended.throttle_pwm < config.blind_pivot_pwm


def test_blind_turn_recentres_bounded_line_error_to_gate_four() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=5.9, heading_deg=20.0, now_s=0.0)
    controller.step(
        gate_count=3,
        x=10.9,
        y=6.0,
        heading_deg=25.0,
        speed_mps=0.20,
        now_s=1.0,
    )
    decision = controller.step(
        gate_count=3,
        x=6.80,
        y=8.80,
        heading_deg=330.0,
        speed_mps=0.20,
        now_s=3.0,
    )
    # The point is south of the nominal line here, so a small northward
    # correction is expected; it must remain bounded rather than becoming a
    # second hard-left command.
    assert 309.0 < decision.target_heading_deg < 337.0
    assert decision.avoidance_reason == ""
    assert decision.steering_pwm != 1100


def test_blind_turn_crosses_gate_four_only_inside_vertical_aperture() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=5.9, heading_deg=20.0, now_s=0.0)
    controller.step(
        gate_count=3,
        x=10.9,
        y=6.0,
        heading_deg=25.0,
        speed_mps=0.20,
        now_s=1.0,
    )
    decision = controller.step(
        gate_count=3,
        x=6.50,
        y=9.50,
        heading_deg=309.0,
        speed_mps=0.20,
        now_s=3.0,
    )
    assert decision.avoidance_reason == "GATE4_STRAIGHT"
    assert 1500 <= decision.steering_pwm < 1600
    assert decision.throttle_pwm >= CourseRouteConfig().blind_turn_pwm


def test_blind_turn_switches_to_gate_four_entry_lane_after_peek() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=5.9, heading_deg=20.0, now_s=0.0)
    controller.step(
        gate_count=3,
        x=11.2,
        y=6.0,
        heading_deg=25.0,
        speed_mps=0.25,
        now_s=1.0,
    )
    # This is the failure geometry recorded in the latest run: the hull is
    # north of the Gate-3 -> Gate-4 line and must move south before it reaches
    # the green buoy at (6, 11).
    lane = controller.step(
        gate_count=3,
        x=8.0,
        y=10.9,
        heading_deg=278.0,
        speed_mps=0.67,
        now_s=3.0,
    )
    final_entry = controller.step(
        gate_count=3,
        x=6.75,
        y=10.9,
        heading_deg=270.0,
        speed_mps=0.25,
        now_s=3.1,
    )
    # The position guard aims just south of the Gate-4 midpoint before the
    # hull reaches the green buoy's x-line, then preserves the already-safe
    # body heading for the final clearance pulse.
    assert lane.target_heading_deg == pytest.approx(225.0, abs=0.5)
    assert lane.steering_pwm < 1500
    # The boat is still far north of the blind-leg centreline, so it must
    # correct at bounded thrust rather than opening full cruise.
    assert lane.throttle_pwm < CourseRouteConfig().max_forward_pwm
    assert final_entry.target_heading_deg == pytest.approx(177.6, abs=0.5)
    assert final_entry.steering_pwm == 1500
    assert final_entry.throttle_pwm == CourseRouteConfig().blind_green_clearance_pwm
    assert final_entry.avoidance_reason == "BLIND_GREEN_CLEARANCE"


def test_blind_turn_clears_green_buoy_with_heading_preserving_pulse() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=5.9, heading_deg=20.0, now_s=0.0)
    controller.step(
        gate_count=3,
        x=11.2,
        y=6.0,
        heading_deg=25.0,
        speed_mps=0.25,
        now_s=1.0,
    )
    decision = controller.step(
        gate_count=3,
        x=6.55,
        y=10.80,
        heading_deg=225.0,
        speed_mps=0.30,
        ultrasonic={"right": 0.12, "front": 4.0},
        now_s=3.1,
    )
    assert decision.steering_pwm == 1500
    assert decision.throttle_pwm == CourseRouteConfig().blind_green_clearance_pwm
    assert decision.avoidance_reason == "BLIND_GREEN_CLEARANCE"


def test_blind_entry_recovery_mirrors_for_arena_b() -> None:
    controller = CourseRouteController(CourseRouteConfig(arena="B"))
    controller.step(gate_count=2, x=19.0, y=5.9, heading_deg=340.0, now_s=0.0)
    controller.step(
        gate_count=3,
        x=18.8,
        y=6.0,
        heading_deg=335.0,
        speed_mps=0.25,
        now_s=1.0,
    )
    decision = controller.step(
        gate_count=3,
        x=22.0,
        y=10.9,
        heading_deg=82.0,
        speed_mps=0.67,
        now_s=3.0,
    )
    assert decision.target_heading_deg == pytest.approx(135.0, abs=0.5)
    assert decision.throttle_pwm < CourseRouteConfig().max_forward_pwm


def test_blind_turn_enables_full_cruise_only_after_lane_capture() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=5.9, heading_deg=20.0, now_s=0.0)
    controller.step(
        gate_count=3,
        x=11.0,
        y=6.0,
        heading_deg=20.0,
        speed_mps=0.20,
        now_s=1.0,
    )
    # This point lies on the Gate-3 -> Gate-4 centreline and faces its 309°
    # bearing. Only here is the post-turn full-forward command allowed.
    captured = controller.step(
        gate_count=3,
        x=10.5,
        y=6.4,
        heading_deg=309.0,
        speed_mps=0.20,
        now_s=3.0,
    )
    assert captured.throttle_pwm == CourseRouteConfig().max_forward_pwm

    # A later northward drift revokes cruise and returns to the capture pulse.
    drifted = controller.step(
        gate_count=3,
        x=8.0,
        y=10.9,
        heading_deg=278.0,
        speed_mps=0.67,
        now_s=3.1,
    )
    assert drifted.throttle_pwm < CourseRouteConfig().max_forward_pwm


def test_gate_four_uses_centerline_corridor_control_after_crossing() -> None:
    decision = CourseRouteController().step(
        gate_count=4,
        x=5.80,
        y=10.40,
        heading_deg=330.0,
        speed_mps=0.20,
    )
    assert decision.phase is CoursePhase.CORRIDOR
    assert decision.avoidance_reason == ""
    assert decision.target_heading_deg is not None
    # The lane controller points southwest while north of y=10.0, then
    # continuously settles to west; it must not jump to the opposite side of
    # the corridor.
    assert 230.0 <= decision.target_heading_deg <= 290.0
    assert decision.steering_pwm != 1900


def test_blind_turn_brakes_and_pivots_at_gate_three_entry() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=11.0, y=5.9, heading_deg=12.0)
    decision = controller.step(
        gate_count=3,
        x=11.2,
        y=6.0,
        heading_deg=12.0,
        speed_mps=0.45,
    )
    assert decision.phase is CoursePhase.TURN
    assert decision.throttle_pwm == CourseRouteConfig().course_turn_brake_pwm
    assert decision.steering_pwm == 1900


def test_course_route_uses_smallest_heading_error_across_north() -> None:
    decision = CourseRouteController().step(
        gate_count=0,
        x=11.0,
        y=-12.0,
        heading_deg=359.0,
    )
    assert decision.target_heading_deg == pytest.approx(0.0)
    assert decision.steering_pwm > 1500


def test_course_route_slows_before_large_turn() -> None:
    controller = CourseRouteController()
    cruise = controller.step(
        gate_count=0,
        x=11.0,
        y=-12.0,
        heading_deg=0.0,
        speed_mps=0.30,
    )
    turn = controller.step(
        gate_count=3,
        x=10.0,
        y=6.0,
        heading_deg=20.0,
        speed_mps=0.30,
    )
    assert turn.throttle_pwm < cruise.throttle_pwm
    assert turn.target_speed_mps < cruise.target_speed_mps
    assert turn.phase is CoursePhase.TURN


def test_course_route_uses_new_leg_heading_immediately_after_gate_crossing() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=8, x=-11.0, y=6.0, heading_deg=180.0)

    decision = controller.step(
        gate_count=9,
        x=-9.25,
        y=0.0,
        heading_deg=131.0,
    )

    assert decision.target_heading_deg == pytest.approx(198.86, abs=0.02)
    assert decision.steering_pwm > 1600


def test_course_route_targets_blue_marker_after_gate_ten() -> None:
    decision = CourseRouteController().step(
        gate_count=10,
        x=-11.0,
        y=-6.0,
        heading_deg=180.0,
    )
    assert decision.phase is CoursePhase.MARKER_BLUE
    assert decision.finished is False
    assert decision.target_waypoint == pytest.approx((-11.2, -9.2))
    assert decision.throttle_pwm > 1500


def test_course_route_uses_reverse_brake_when_marker_approach_is_overspeed() -> None:
    decision = CourseRouteController().step(
        gate_count=10,
        x=-11.0,
        y=-6.0,
        heading_deg=150.0,
        speed_mps=0.55,
    )
    assert decision.phase is CoursePhase.MARKER_BLUE
    assert decision.throttle_pwm == CourseRouteConfig().reverse_brake_pwm


def test_course_route_reverses_and_mirrors_azimuth_for_large_green_exit_turn() -> None:
    decision = CourseRouteController().step(
        gate_count=10,
        marker_count=2,
        x=-6.9,
        y=-12.1,
        heading_deg=170.0,
        speed_mps=0.15,
    )
    config = CourseRouteConfig()
    assert decision.phase is CoursePhase.DOCK_RETURN
    assert decision.throttle_pwm == config.reverse_turn_pwm
    # The forward heading correction would use a low PWM. A reversible
    # stern thruster has to mirror it to retain the same yaw moment.
    assert decision.steering_pwm > 1500


def test_course_route_does_not_brake_early_before_green_pass() -> None:
    controller = CourseRouteController()
    controller.step(
        gate_count=10,
        x=-11.3,
        y=-6.0,
        heading_deg=180.0,
    )
    decision = controller.step(
        gate_count=10,
        marker_count=1,
        x=-10.9,
        y=-9.25,
        heading_deg=170.0,
        speed_mps=0.16,
    )
    config = CourseRouteConfig()
    assert decision.phase is CoursePhase.MARKER_GREEN
    # The green box is still several metres away.  A reverse pulse is reserved
    # for a genuinely close, overspeed approach rather than this early turn.
    assert decision.throttle_pwm > config.reverse_brake_pwm
    assert decision.steering_pwm != 1500


def test_course_route_uses_gps_south_boundary_recovery_when_ultrasonic_misses_corner() -> None:
    decision = CourseRouteController().step(
        gate_count=10,
        marker_count=1,
        x=-9.5,
        y=-12.6,
        heading_deg=120.0,
        speed_mps=0.16,
        ultrasonic={
            "front": 5.0,
            "front_left": 5.0,
            "front_right": 5.0,
            "left": 5.0,
            "right": 5.0,
        },
    )
    assert decision.throttle_pwm == CourseRouteConfig().reverse_turn_pwm
    assert decision.avoidance_reason == "BOUNDARY_SOUTH_RECOVERY"


def test_course_route_uses_lateral_boundary_recovery_before_west_wall() -> None:
    decision = CourseRouteController().step(
        gate_count=10,
        marker_count=1,
        x=-12.7,
        y=-10.5,
        heading_deg=135.0,
        speed_mps=0.20,
        ultrasonic={
            "front_left": 5.0,
            "front": 5.0,
            "front_right": 5.0,
            "left": 5.0,
            "right": 5.0,
        },
    )
    assert decision.avoidance_reason == "BOUNDARY_LATERAL_RECOVERY"
    assert decision.throttle_pwm < 1500
    assert decision.steering_pwm < 1500


def test_course_route_advances_markers_only_after_centre_corridor_crossing() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=10, x=-11.0, y=-6.0, heading_deg=180.0)
    valid = controller.step(
        gate_count=10,
        x=-11.10,
        y=-9.20,
        heading_deg=155.0,
    )
    assert valid.marker_count == 1
    assert valid.phase is CoursePhase.MARKER_GREEN
    assert valid.target_waypoint == pytest.approx((-5.55, -11.25))

    off_centre = CourseRouteController()
    off_centre.step(gate_count=10, x=-11.0, y=-6.0, heading_deg=180.0)
    missed = off_centre.step(
        gate_count=10,
        x=-10.00,
        y=-9.20,
        heading_deg=155.0,
    )
    assert missed.marker_count == 0
    assert missed.phase is CoursePhase.MARKER_BLUE


def test_course_route_requires_dock_entry_before_final_dock() -> None:
    controller = CourseRouteController()
    direct = controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-13.0,
        heading_deg=180.0,
    )
    first_return = controller.step(
        gate_count=10,
        marker_count=2,
        x=-4.8,
        y=-10.8,
        heading_deg=90.0,
    )
    second_return = controller.step(
        gate_count=10,
        marker_count=2,
        x=1.0,
        y=-8.5,
        heading_deg=90.0,
    )
    third_return = controller.step(
        gate_count=10,
        marker_count=2,
        x=7.0,
        y=-8.3,
        heading_deg=90.0,
    )
    entry = controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-10.45,
        heading_deg=180.0,
    )
    assert direct.phase is CoursePhase.DOCK_RETURN
    assert direct.target_waypoint == (-4.8, -10.8)
    assert first_return.target_waypoint == (1.0, -8.5)
    assert second_return.target_waypoint == (7.0, -8.3)
    assert third_return.phase is CoursePhase.DOCK_APPROACH
    assert third_return.target_waypoint == (11.5, -10.45)
    assert entry.phase is CoursePhase.DOCK
    assert entry.target_waypoint == (11.5, -13.0)


def test_course_route_aligns_at_dock_entry_before_releasing_final_berth() -> None:
    controller = CourseRouteController()
    controller.step(
        gate_count=10,
        marker_count=2,
        x=-4.8,
        y=-10.8,
        heading_deg=90.0,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=1.0,
        y=-8.5,
        heading_deg=90.0,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=7.0,
        y=-8.3,
        heading_deg=90.0,
    )
    sideways = controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-10.45,
        heading_deg=135.0,
        speed_mps=0.14,
    )
    aligned = controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-10.45,
        heading_deg=180.0,
        speed_mps=0.05,
    )
    assert sideways.phase is CoursePhase.DOCK_APPROACH
    assert sideways.target_heading_deg == pytest.approx(180.0)
    assert sideways.throttle_pwm == CourseRouteConfig().reverse_turn_pwm
    assert aligned.phase is CoursePhase.DOCK


def test_course_route_uses_bounded_turn_boost_during_dock_approach() -> None:
    controller = CourseRouteController()
    controller.step(
        gate_count=10,
        marker_count=2,
        x=-4.8,
        y=-10.8,
        heading_deg=90.0,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=1.0,
        y=-8.5,
        heading_deg=90.0,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=7.0,
        y=-8.3,
        heading_deg=90.0,
    )
    decision = controller.step(
        gate_count=10,
        marker_count=2,
        x=8.5,
        y=-9.2,
        heading_deg=128.0,
        speed_mps=0.14,
    )
    assert decision.phase is CoursePhase.DOCK_APPROACH
    assert decision.throttle_pwm >= CourseRouteConfig().dock_turn_pwm


def test_course_route_finishes_only_after_stable_dock_hold() -> None:
    controller = CourseRouteController()
    # Both pass-through markers must be reported before the final dock phase.
    controller.step(
        gate_count=10,
        marker_count=2,
        x=-4.8,
        y=-10.8,
        heading_deg=90.0,
        speed_mps=0.0,
        now_s=7.5,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=1.0,
        y=-8.5,
        heading_deg=90.0,
        speed_mps=0.0,
        now_s=8.0,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=7.0,
        y=-8.3,
        heading_deg=90.0,
        speed_mps=0.0,
        now_s=8.5,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-10.45,
        heading_deg=180.0,
        speed_mps=0.0,
        now_s=9.0,
    )
    approaching = controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-13.0,
        heading_deg=controller.dock_heading_deg,
        speed_mps=0.0,
        now_s=10.0,
    )
    almost_stable = controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-13.0,
        heading_deg=controller.dock_heading_deg,
        speed_mps=0.0,
        now_s=12.9,
    )
    decision = controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-13.0,
        heading_deg=controller.dock_heading_deg,
        speed_mps=0.0,
        now_s=13.1,
    )
    assert approaching.phase is CoursePhase.DOCK
    assert approaching.throttle_pwm == 1500
    assert almost_stable.finished is False
    assert decision.phase is CoursePhase.FINISH
    assert decision.finished is True
    assert decision.target_waypoint is None
    assert decision.throttle_pwm == 1500


def test_colour_marker_detector_finds_boxes_but_not_green_buoy() -> None:
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Pale Webots water/background.
    frame[:, :] = (190, 150, 85)
    cv2.rectangle(frame, (180, 180), (290, 230), (242, 133, 64), -1)
    cv2.rectangle(frame, (360, 250), (470, 295), (85, 231, 60), -1)
    cv2.circle(frame, (100, 100), 12, (85, 231, 60), -1)

    detections = detect_marker_boxes(frame)
    labels = {detection.label for detection in detections}
    assert labels == {"blue_marker", "green_marker"}
    assert all(detection.confidence >= 0.45 for detection in detections)


def test_marker_visual_layer_turns_away_from_active_box() -> None:
    class DummyLink:
        def send_override(self, steering: int, throttle: int) -> None:
            pass

        def telemetry(self) -> dict[str, object]:
            return {}

    autopilot = CourseAutopilot(DummyLink(), arena="A")
    autopilot.update_visual(
        [Detection("blue_marker", 0.8, 500.0, 300.0, 120.0, 80.0)],
        frame_width=640,
        frame_height=480,
        now_s=10.0,
    )
    decision = autopilot.controller.step(
        gate_count=10,
        marker_count=0,
        x=-11.0,
        y=-9.0,
        heading_deg=90.0,
        speed_mps=0.05,
        now_s=10.0,
    )
    corrected = autopilot._apply_marker_obstacle_correction(decision, now_s=10.0)
    assert corrected.avoidance_reason == "VISION_MARKER_BOX"
    assert corrected.obstacle_avoidance is True
    assert corrected.steering_pwm < decision.steering_pwm


def test_gate_visual_correction_is_bounded_trim() -> None:
    class DummyLink:
        def send_override(self, steering: int, throttle: int) -> None:
            pass

        def telemetry(self) -> dict[str, object]:
            return {}

    autopilot = CourseAutopilot(DummyLink(), arena="A")
    autopilot.update_visual(
        [
            Detection("red_buoy", 0.9, 80.0, 300.0, 120.0, 100.0),
            Detection("green_buoy", 0.9, 600.0, 300.0, 120.0, 100.0),
        ],
        frame_width=640,
        frame_height=480,
        now_s=10.0,
    )
    decision = autopilot.controller.step(
        gate_count=2,
        marker_count=0,
        x=9.0,
        y=1.0,
        heading_deg=18.0,
        speed_mps=0.35,
        now_s=10.0,
    )
    corrected = autopilot._apply_visual_correction(decision, now_s=10.0)
    assert corrected.visual_correction_active is True
    assert abs(corrected.visual_correction_pwm) <= 30


def test_blind_turn_ignores_buoy_pair_trim_during_pivot() -> None:
    class DummyLink:
        def send_override(self, steering: int, throttle: int) -> None:
            pass

        def telemetry(self) -> dict[str, object]:
            return {}

    autopilot = CourseAutopilot(DummyLink(), arena="A")
    autopilot.update_visual(
        [
            Detection("red_buoy", 0.9, 90.0, 280.0, 120.0, 100.0),
            Detection("green_buoy", 0.9, 560.0, 280.0, 120.0, 100.0),
        ],
        frame_width=640,
        frame_height=480,
        now_s=10.0,
    )
    decision = autopilot.controller.step(
        gate_count=3,
        x=11.0,
        y=6.0,
        heading_deg=350.0,
        speed_mps=0.1,
        now_s=10.0,
    )
    corrected = autopilot._apply_visual_correction(decision, now_s=10.0)
    assert corrected.visual_correction_active is False
    assert corrected.avoidance_reason == "BLIND_LEFT_BRAKE"


def test_course_route_resets_after_simulator_returns_to_start() -> None:
    controller = CourseRouteController()
    controller.step(
        gate_count=10,
        marker_count=2,
        x=-2.0,
        y=-11.4,
        heading_deg=90.0,
        speed_mps=0.0,
        now_s=-1.0,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=5.0,
        y=-11.1,
        heading_deg=90.0,
        speed_mps=0.0,
        now_s=-0.5,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-10.45,
        heading_deg=180.0,
        speed_mps=0.0,
        now_s=-0.1,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-13.0,
        heading_deg=controller.dock_heading_deg,
        speed_mps=0.0,
        now_s=0.0,
    )
    controller.step(
        gate_count=10,
        marker_count=2,
        x=11.5,
        y=-13.0,
        heading_deg=controller.dock_heading_deg,
        speed_mps=0.0,
        now_s=3.1,
    )
    restarted = controller.step(
        gate_count=0,
        x=11.1,
        y=-11.5,
        heading_deg=0.0,
    )
    assert restarted.phase is CoursePhase.APPROACH
    assert restarted.gate_count == 0
    assert restarted.target_waypoint == (11.0, -6.0)
    assert restarted.finished is False


def test_course_route_infers_progress_without_simulator_gate_counter() -> None:
    controller = CourseRouteController()
    start = controller.step(
        gate_count=None,
        x=11.1,
        y=-11.5,
        heading_deg=0.0,
    )
    assert start.gate_count == 0
    captured = controller.step(
        gate_count=None,
        x=11.0,
        y=-6.0,
        heading_deg=0.0,
    )
    assert captured.gate_count == 1
    assert captured.target_waypoint == (9.0, 0.0)


def test_sensor_only_does_not_advance_on_midpoint_approach_outside_gate() -> None:
    controller = CourseRouteController()
    controller.step(
        gate_count=None,
        x=13.0,
        y=-11.5,
        heading_deg=0.0,
    )
    missed = controller.step(
        gate_count=None,
        x=13.0,
        y=-6.0,
        heading_deg=0.0,
    )
    assert missed.gate_count == 0


def test_sensor_only_mirrors_gate_plane_for_arena_b() -> None:
    controller = CourseRouteController(CourseRouteConfig(arena="B"))
    controller.step(
        gate_count=None,
        x=18.9,
        y=-11.5,
        heading_deg=0.0,
    )
    captured = controller.step(
        gate_count=None,
        x=19.0,
        y=-6.0,
        heading_deg=0.0,
    )
    assert captured.gate_count == 1


def test_course_route_corridor_correction_is_bounded_and_centering() -> None:
    high = CourseRouteController().step(
        gate_count=4,
        x=5.0,
        y=11.0,
        heading_deg=270.0,
    )
    low = CourseRouteController().step(
        gate_count=4,
        x=5.0,
        y=9.0,
        heading_deg=270.0,
    )
    assert high.phase is CoursePhase.CORRIDOR
    # The controller aims at the next midpoint (2, 10), so one metre of
    # north/south error produces only the geometric bearing correction.
    assert high.target_heading_deg == pytest.approx(251.565, abs=1e-3)
    assert high.steering_pwm < 1500
    assert low.target_heading_deg == pytest.approx(288.435, abs=1e-3)
    assert low.steering_pwm > 1500


def test_course_route_blends_gate_center_with_outgoing_leg_before_crossing() -> None:
    decision = CourseRouteController().step(
        gate_count=0,
        x=10.0,
        y=-6.8,
        heading_deg=0.0,
    )
    assert decision.target_waypoint == (11.0, -6.0)
    assert 330.0 <= decision.target_heading_deg < 360.0


def test_course_route_enters_top_corridor_from_gate_midpoint_before_turning_west() -> None:
    # Gate 4 is the first vertical pair.  The controller may begin the turn,
    # but must still point toward its midpoint rather than driving west into a
    # buoy before crossing x=6.
    decision = CourseRouteController().step(
        gate_count=3,
        x=6.75,
        y=8.97,
        heading_deg=277.0,
        speed_mps=0.35,
    )
    assert decision.target_waypoint == (6.0, 10.0)
    assert 285.0 <= decision.target_heading_deg <= 345.0


def test_course_route_marker_guidance_uses_left_then_right_pass_sides() -> None:
    controller = CourseRouteController()
    blue, green = controller.marker_guidance_waypoints
    blue_centre, green_centre = controller.marker_waypoints
    assert blue[0] < blue_centre[0]
    assert green[0] > green_centre[0]
    assert green[1] > green_centre[1]


def test_course_route_slows_gate_ten_approach_before_buoy_line() -> None:
    decision = CourseRouteController().step(
        gate_count=9,
        x=-9.3,
        y=-4.0,
        heading_deg=220.0,
        speed_mps=0.30,
    )
    # A modest 17-degree error should keep moving; the turn ceiling is for
    # larger heading errors only.
    assert decision.target_speed_mps > CourseRouteConfig().turn_speed_mps
    assert decision.throttle_pwm > CourseRouteConfig().approach_pwm


def test_course_route_keeps_gate_center_without_pre_turning() -> None:
    decision = CourseRouteController().step(
        gate_count=2,
        x=10.0,
        y=5.0,
        heading_deg=20.0,
        speed_mps=0.30,
    )
    assert decision.target_waypoint == (11.0, 6.0)
    # The hull is still approaching the visible Gate 3 pair.  It should not
    # enter the blind-turn low-speed envelope before the gate plane.
    assert decision.target_speed_mps <= CourseRouteConfig().slalom_speed_mps
    assert decision.target_speed_mps > CourseRouteConfig().heading_slow_speed_mps
    assert decision.steering_pwm != 1100
    assert decision.throttle_pwm > CourseRouteConfig().approach_pwm


def test_course_route_commits_heading_at_blind_gate_transition() -> None:
    controller = CourseRouteController()
    controller.step(gate_count=2, x=10.0, y=5.0, heading_deg=20.0)
    decision = controller.step(gate_count=3, x=10.0, y=6.0, heading_deg=20.0)
    # Gate 3 is the known blind corner.  Waiting for the normal heading slew
    # would send the hull north of Gate 4 before the next pair is visible.
    assert decision.target_heading_deg == pytest.approx(309.0)


def test_course_route_mirrors_waypoints_and_dock_for_arena_b() -> None:
    controller = CourseRouteController(CourseRouteConfig(arena="B"))
    first = controller.step(
        gate_count=0,
        x=20.0,
        y=-11.5,
        heading_deg=0.0,
    )
    staging_return = controller.step(
        gate_count=10,
        marker_count=2,
        x=34.8,
        y=-10.8,
        heading_deg=270.0,
    )
    first_return = controller.step(
        gate_count=10,
        marker_count=2,
        x=29.0,
        y=-8.5,
        heading_deg=270.0,
    )
    second_return = controller.step(
        gate_count=10,
        marker_count=2,
        x=23.0,
        y=-8.3,
        heading_deg=270.0,
    )
    dock = controller.step(
        gate_count=10,
        marker_count=2,
        x=18.5,
        y=-10.45,
        heading_deg=180.0,
    )
    assert first.target_waypoint == (19.0, -6.0)
    assert staging_return.target_waypoint == (29.0, -8.5)
    assert first_return.target_waypoint == (23.0, -8.3)
    assert second_return.target_waypoint == (18.5, -10.45)
    assert dock.target_waypoint == (18.5, -13.0)
    assert controller.arena == "B"


def test_course_route_front_ultrasonic_uses_low_escape_pulse() -> None:
    decision = CourseRouteController().step(
        gate_count=0,
        x=10.0,
        y=-10.0,
        heading_deg=0.0,
        ultrasonic={"front": 0.40},
    )
    assert 1500 < decision.throttle_pwm <= CourseRouteConfig().ultrasonic_escape_pwm
    assert decision.obstacle_avoidance is True
    assert decision.avoidance_reason == "ULTRASONIC_FRONT_STOP"


def test_course_route_reverses_once_when_front_block_remains_stuck() -> None:
    controller = CourseRouteController()
    first = controller.step(
        gate_count=0,
        x=10.0,
        y=-10.0,
        heading_deg=0.0,
        speed_mps=0.0,
        ultrasonic={"front": 0.20},
        now_s=0.0,
    )
    second = controller.step(
        gate_count=0,
        x=10.0,
        y=-10.0,
        heading_deg=0.0,
        speed_mps=0.0,
        ultrasonic={"front": 0.20},
        now_s=0.9,
    )
    assert first.avoidance_reason == "ULTRASONIC_FRONT_STOP"
    assert second.avoidance_reason == "ULTRASONIC_REVERSE_ESCAPE"
    assert second.throttle_pwm == CourseRouteConfig().reverse_brake_pwm
    assert second.steering_pwm == 1500


def test_course_route_steers_away_from_left_ultrasonic_obstacle() -> None:
    clear = CourseRouteController().step(
        gate_count=0,
        x=11.0,
        y=-7.0,
        heading_deg=0.0,
    )
    avoided = CourseRouteController().step(
        gate_count=0,
        x=11.0,
        y=-7.0,
        heading_deg=0.0,
        ultrasonic={"front_left": 0.30, "left": 0.40},
    )
    assert avoided.steering_pwm > clear.steering_pwm
    assert avoided.avoidance_reason == "ULTRASONIC_SIDE_CLEARANCE"


def test_course_route_coasts_when_above_target_speed_and_never_reverses() -> None:
    decision = CourseRouteController().step(
        gate_count=0,
        x=10.0,
        y=-10.0,
        heading_deg=0.0,
        speed_mps=1.2,
    )
    assert decision.throttle_pwm == 1500


def test_visual_gate_pair_rejects_buoys_from_different_depths() -> None:
    detections = [
        Detection("red_buoy", 0.91, 120.0, 300.0, 38.0, 62.0),
        Detection("green_buoy", 0.88, 520.0, 302.0, 40.0, 60.0),
        # This green buoy is horizontally nearer, but belongs to a distant gate.
        Detection("green_buoy", 0.97, 250.0, 70.0, 12.0, 18.0),
    ]
    pair = select_visual_gate_pair(detections, 640, 480)
    assert pair is not None
    assert pair.target_x == pytest.approx(320.0)
    assert pair.confidence == pytest.approx(0.88)


def test_visual_gate_pair_requires_red_left_green_right() -> None:
    detections = [
        Detection("red_buoy", 0.90, 500.0, 300.0, 40.0, 60.0),
        Detection("green_buoy", 0.90, 140.0, 300.0, 40.0, 60.0),
    ]
    assert select_visual_gate_pair(detections, 640, 480) is None


def test_visual_gate_centering_accepts_mirrored_colour_order_for_arena_b() -> None:
    centering = VisualGateCentering(
        VisualGateCorrectionConfig(red_on_left=False)
    )
    correction = centering.update(
        [
            Detection("green_buoy", 0.90, 140.0, 300.0, 40.0, 60.0),
            Detection("red_buoy", 0.90, 500.0, 300.0, 40.0, 60.0),
        ],
        frame_width=640,
        frame_height=480,
        now_s=0.0,
    )
    assert correction is not None
    assert correction.target_x == pytest.approx(320.0)


def test_visual_gate_centering_is_bounded_and_expires() -> None:
    centering = VisualGateCentering()
    detections = [
        Detection("red_buoy", 0.90, 360.0, 300.0, 40.0, 60.0),
        Detection("green_buoy", 0.90, 560.0, 301.0, 42.0, 61.0),
    ]
    correction = centering.update(
        detections,
        frame_width=640,
        frame_height=480,
        now_s=10.0,
    )
    assert correction is not None
    assert 0 < correction.steering_delta_pwm <= 160
    assert centering.update([], frame_width=640, frame_height=480, now_s=10.3) == correction
    assert centering.update([], frame_width=640, frame_height=480, now_s=10.6) is None
