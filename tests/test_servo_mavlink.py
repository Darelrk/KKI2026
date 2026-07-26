from servo_mavlink import MAV_IGNORE, build_rc_override


def test_build_rc_override_sets_steering_and_neutral_throttle() -> None:
    channels = build_rc_override(
        steering_channel=1,
        steering_pwm=1100,
        throttle_channel=3,
        throttle_pwm=1500,
    )

    assert channels == (1100, MAV_IGNORE, 1500, MAV_IGNORE, MAV_IGNORE, MAV_IGNORE, MAV_IGNORE, MAV_IGNORE)


def test_build_rc_override_rejects_duplicate_channels() -> None:
    try:
        build_rc_override(
            steering_channel=3,
            steering_pwm=1100,
            throttle_channel=3,
            throttle_pwm=1500,
        )
    except ValueError as exc:
        assert "berbeda" in str(exc)
    else:
        raise AssertionError("duplicate RC channels must be rejected")
