import pytest
from types import SimpleNamespace

from vision_route import (
    Detection,
    GateFeature,
    GateTracker,
    PatternMatcher,
    PatternSignature,
    RouteConfig,
    RouteController,
    RouteState,
    ThrottleConfig,
    VisualTargetTracker,
    VisualThrottleController,
    compute_visual_throttle_pwm,
    signed_heading_error,
)
from vision_test import vfr_hud_heading


def test_signed_heading_error_wraps_at_north():
    assert signed_heading_error(1.0, 359.0) == 2.0
    assert signed_heading_error(359.0, 1.0) == -2.0


def test_controller_starts_in_visual_track():
    controller = RouteController(RouteConfig())
    decision = controller.step([], frame_width=640, heading_deg=0.0, now=0.0)
    assert decision.state is RouteState.VISUAL_TRACK
    assert decision.steering_pwm == 1500
    assert decision.throttle_pwm == 1500


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

    # Single red buoy -> steer right (+offset)
    red_only = [det("red_buoy", 200, 300)] # width=20, default offset = 20 * 1.5 = 30
    assert select_target_x(red_only) == 230.0

    # Single green buoy -> steer left (-offset)
    green_only = [det("green_buoy", 400, 300)] # width=20, default offset = 20 * 1.5 = 30
    assert select_target_x(green_only) == 370.0


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
        == 1585
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
    assert tracker.update([pair[0]], now=0.9) == 260.0


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
