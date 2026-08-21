"""Compatibility entrypoint for the canonical simulator vision controller.

The implementation lives in :mod:`simulation.vision_test`.  Keeping this thin
wrapper prevents root-level commands and older imports from running a stale
copy of the navigation algorithm.
"""

from simulation.vision_test import *  # noqa: F401,F403


def create_pixhawk_link(
    *,
    manual_rc: bool,
    endpoint: str,
    origin_lat: float = -6.200000,
    origin_lon: float = 106.816666,
):
    """Compatibility shim whose ``PixhawkLink`` remains monkeypatchable."""
    if manual_rc:
        return None
    if origin_lat == -6.200000 and origin_lon == 106.816666:
        return PixhawkLink(endpoint)
    return PixhawkLink(endpoint, origin_lat=origin_lat, origin_lon=origin_lon)


if __name__ == "__main__":
    from simulation.vision_test import main

    main()
