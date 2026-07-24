import sys

import vision_test


def test_parse_args_accepts_manual_rc(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["vision_test.py", "--manual-rc", "--model", "model/best.pt"],
    )

    args = vision_test.parse_args()

    assert args.manual_rc is True


def test_manual_rc_does_not_construct_pixhawk(monkeypatch) -> None:
    class PixhawkMustNotStart:
        def __init__(self, endpoint: str) -> None:
            raise AssertionError(f"Pixhawk opened unexpectedly: {endpoint}")

    monkeypatch.setattr(vision_test, "PixhawkLink", PixhawkMustNotStart)

    assert (
        vision_test.create_pixhawk_link(
            manual_rc=True,
            endpoint="/dev/ttyACM0",
        )
        is None
    )


def test_control_mode_still_constructs_pixhawk(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(vision_test, "PixhawkLink", lambda endpoint: sentinel)

    assert (
        vision_test.create_pixhawk_link(
            manual_rc=False,
            endpoint="/dev/ttyACM0",
        )
        is sentinel
    )
