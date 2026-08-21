from simulation.evaluate_batch import is_docked_status, is_initial_status


def test_initial_status_accepts_clean_webots_start() -> None:
    status = {
        "x": 11.1,
        "y": -11.5,
        "gate_tracking": {
            "passed_valid": 0,
            "missed": 0,
            "wall_touches": 0,
            "buoy_touches": 0,
        },
    }
    assert is_initial_status(status) is True


def test_initial_status_rejects_stale_mid_course_state() -> None:
    status = {
        "x": 9.0,
        "y": 6.0,
        "gate_tracking": {
            "passed_valid": 3,
            "missed": 0,
            "wall_touches": 0,
            "buoy_touches": 0,
        },
    }
    assert is_initial_status(status) is False


def test_initial_status_accepts_mirrored_arena_b_start() -> None:
    status = {
        "arena": "B",
        "x": 18.9,
        "y": -11.5,
        "gate_tracking": {
            "passed_valid": 0,
            "missed": 0,
            "wall_touches": 0,
            "buoy_touches": 0,
        },
    }
    assert is_initial_status(status) is True


def test_docked_status_requires_gate_completion_and_dock_position() -> None:
    status = {
        "x": 11.5,
        "y": -13.0,
        "gate_tracking": {
            "passed_valid": 10,
            "total_gates": 10,
            "markers_passed_valid": 2,
            "total_markers": 2,
            "dock_target": [11.5, -13.0],
        },
    }
    assert is_docked_status(status) is True


def test_docked_status_requires_both_bottom_markers() -> None:
    status = {
        "x": 11.5,
        "y": -13.0,
        "gate_tracking": {
            "passed_valid": 10,
            "total_gates": 10,
            "markers_passed_valid": 1,
            "total_markers": 2,
            "dock_target": [11.5, -13.0],
        },
    }
    assert is_docked_status(status) is False


def test_docked_status_rejects_gate_ten_position() -> None:
    status = {
        "x": -11.0,
        "y": -6.0,
        "gate_tracking": {"passed_valid": 10, "total_gates": 10},
    }
    assert is_docked_status(status) is False


def test_reset_simulation_accepts_success_status(monkeypatch) -> None:
    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    from simulation import evaluate_batch

    monkeypatch.setattr(
        evaluate_batch.urllib.request,
        "urlopen",
        lambda _request, timeout: Response(),
    )
    evaluate_batch.reset_simulation()


def test_reset_simulation_rejects_http_error(monkeypatch) -> None:
    class Response:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    from simulation import evaluate_batch

    monkeypatch.setattr(
        evaluate_batch.urllib.request,
        "urlopen",
        lambda _request, timeout: Response(),
    )
    try:
        evaluate_batch.reset_simulation()
    except RuntimeError as exc:
        assert "Tidak bisa reset Webots" in str(exc)
    else:
        raise AssertionError("reset_simulation accepted HTTP 500")
