"""Parametric planar-plywood hulls for the KKI2026 hull study.

The module is deliberately self-contained so a saved FreeCAD document can be
reopened with this file on ``sys.path``.  Geometry is made from individual
20 mm planar stock solids; there is no filled-hull fallback.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

try:  # FreeCAD imports are available when this module is run by FreeCAD.
    import FreeCAD as App  # type: ignore
    import Part  # type: ignore
except ImportError:  # Keep importable for the bundled loader outside FreeCAD.
    App = None  # type: ignore
    Part = None  # type: ignore

SCHEMA = 1
PROJECT_SUFFIX = "KKI2026-hull-research"
SHEET_WIDTH = 1000.0
SHEET_HEIGHT = 600.0
SHEET_MARGIN = 10.0
SHEET_GAP = 8.0
EPS = 1.0e-7

# Property definitions are shared by the spreadsheet, controller, and rebuild
# code.  All dimensional values are millimetres unless marked as an angle.
PARAMETER_DEFS: Sequence[Tuple[str, str, str, Any]] = (
    ("HullLength", "App::PropertyLength", "HullLength", "900 mm"),
    ("HullWidthTotal", "App::PropertyLength", "HullWidthTotal", "550 mm"),
    ("HullWidthSingle", "App::PropertyLength", "HullWidthSingle", "260 mm"),
    ("MainHullWidth", "App::PropertyLength", "MainHullWidth", "260 mm"),
    ("AmaWidth", "App::PropertyLength", "AmaWidth", "100 mm"),
    ("AmaLength", "App::PropertyLength", "AmaLength", "600 mm"),
    ("HullGap", "App::PropertyLength", "HullGap", "30 mm"),
    ("TriGap", "App::PropertyLength", "TriGap", "25 mm"),
    ("CatCenterOffset", "App::PropertyLength", "CatCenterOffset", "145 mm"),
    ("AmaCenterOffset", "App::PropertyLength", "AmaCenterOffset", "225 mm"),
    ("PlywoodT", "App::PropertyLength", "PlywoodT", "20 mm"),
    ("HullHeight", "App::PropertyLength", "HullHeight", "140 mm"),
    ("AmaHeight", "App::PropertyLength", "AmaHeight", "110 mm"),
    ("AmaBaseZ", "App::PropertyLength", "AmaBaseZ", "30 mm"),
    ("DeckHeight", "App::PropertyLength", "DeckHeight", "120 mm"),
    ("DeckThickness", "App::PropertyLength", "DeckThickness", "20 mm"),
    ("BottomFlatSingle", "App::PropertyLength", "BottomFlatSingle", "150 mm"),
    ("MainBottomFlat", "App::PropertyLength", "MainBottomFlat", "190 mm"),
    ("AmaBottomFlat", "App::PropertyLength", "AmaBottomFlat", "50 mm"),
    ("DeadriseAngle", "App::PropertyAngle", "DeadriseAngle", "15 deg"),
    ("DeadriseRun", "App::PropertyLength", "DeadriseRun", "55 mm"),
    ("DeadriseRise", "App::PropertyLength", "DeadriseRise", "0 mm"),
    ("StationFirst", "App::PropertyLength", "StationFirst", "50 mm"),
    ("StationSpacing", "App::PropertyLength", "StationSpacing", "170 mm"),
    ("StationCount", "App::PropertyInteger", "StationCount", 5),
    ("ConnectorWidth", "App::PropertyLength", "ConnectorWidth", "20 mm"),
    ("ConnectorX1", "App::PropertyLength", "ConnectorX1", "120 mm"),
    ("ConnectorX2", "App::PropertyLength", "ConnectorX2", "290 mm"),
    ("ConnectorX3", "App::PropertyLength", "ConnectorX3", "460 mm"),
    ("ConnectorX4", "App::PropertyLength", "ConnectorX4", "630 mm"),
    ("BowEntranceCat", "App::PropertyLength", "BowEntranceCat", "220 mm"),
    ("BowEntranceMain", "App::PropertyLength", "BowEntranceMain", "270 mm"),
    ("BowEntranceAma", "App::PropertyLength", "BowEntranceAma", "180 mm"),
    ("KerfWidth", "App::PropertyLength", "KerfWidth", "0.2 mm"),
    ("KerfOffset", "App::PropertyLength", "KerfOffset", "0.1 mm"),
    ("MinInnerRadius", "App::PropertyLength", "MinInnerRadius", "6 mm"),
    ("FinishAllowance", "App::PropertyLength", "FinishAllowance", "0 mm"),
)


def _require_freecad() -> None:
    if App is None or Part is None:
        raise RuntimeError("FreeCAD/Part API is required; run this module inside FreeCAD 1.1.1")


def install_module_path(root: str) -> str:
    """Make the bundled module discoverable after a FCStd reopen."""
    path = os.path.abspath(os.fspath(root))
    if path not in sys.path:
        sys.path.insert(0, path)
    return path


def _quantity_value(value: Any) -> float:
    """Read a FreeCAD Quantity or a plain numeric value in millimetres/degrees."""
    if hasattr(value, "Value"):
        return float(value.Value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    # This fallback is only for values already expressed in the spreadsheet's
    # document units.  FreeCAD properties normally take the first branch.
    match = re.match(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)", text)
    if not match:
        raise ValueError(f"Cannot read FreeCAD quantity: {value!r}")
    return float(match.group(1))


def _number(value: Any) -> float:
    return _quantity_value(value)


def _vec(value: Sequence[float] | Any) -> Any:
    _require_freecad()
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return App.Vector(value.x, value.y, value.z)
    return App.Vector(float(value[0]), float(value[1]), float(value[2]))


def _point_list(points: Iterable[Any]) -> List[Any]:
    _require_freecad()
    result: List[Any] = []
    for point in points:
        v = _vec(point)
        if not result or (v - result[-1]).Length > EPS:
            result.append(v)
    if len(result) > 1 and (result[0] - result[-1]).Length <= EPS:
        result.pop()
    if len(result) < 3:
        raise ValueError("A panel face needs at least three distinct points")
    return result


def _face(points: Iterable[Any]) -> Tuple[Any, List[Any]]:
    pts = _point_list(points)
    wire = Part.makePolygon(pts + [pts[0]])
    face = Part.Face(wire)
    if face.isNull() or face.Area <= EPS:
        raise ValueError("Panel face is null or has zero area")
    return face, pts


def _plane_normal(points: Sequence[Any]) -> Any:
    for index in range(1, len(points) - 1):
        normal = (points[index] - points[0]).cross(points[index + 1] - points[0])
        if normal.Length > EPS:
            normal.normalize()
            return normal
    raise ValueError("Panel face points are collinear")


def _solid(points: Iterable[Any], inward: Sequence[float], thickness: float) -> Tuple[Any, List[Any]]:
    """Make one stock-thickness solid from a planar face.

    The face is the outside nominal mating profile.  Extrusion is toward the
    hull interior, leaving the envelope at the specified design dimensions.
    """
    if thickness <= EPS:
        raise ValueError(f"Plywood thickness must be positive, got {thickness}")
    face, pts = _face(points)
    normal = _plane_normal(pts)
    expected = _vec((float(inward[0]), float(inward[1]), float(inward[2])))
    if expected.Length <= EPS:
        raise ValueError("Panel extrusion direction cannot be zero")
    if normal.dot(expected) < 0.0:
        normal = normal.multiply(-1.0)
    shape = face.extrude(normal.multiply(float(thickness)))
    if shape.isNull() or not shape.isValid() or shape.Volume <= EPS:
        raise RuntimeError(
            f"Invalid panel solid (volume={getattr(shape, 'Volume', 0)!r}); "
            "check planar panel points and plywood thickness"
        )
    return shape, pts


def _flatten_points(points: Sequence[Any]) -> List[List[float]]:
    """Rigidly flatten a planar polygon into a deterministic 2-D outline."""
    pts = _point_list(points)
    origin = pts[0]
    e1 = None
    for point in pts[1:]:
        candidate = point - origin
        if candidate.Length > EPS:
            candidate.normalize()
            e1 = candidate
            break
    if e1 is None:
        raise ValueError("Cannot flatten a degenerate panel")
    e2 = None
    for point in pts[2:] + pts[1:2]:
        candidate = point - origin
        # FreeCAD's Vector.multiply() is SCALAR multiplication that mutates
        # the vector in place; the dot product must be applied on a COPY so
        # the basis vector e1 is not scaled by the projection length.
        dot = candidate.dot(e1)
        e1_scaled = App.Vector(e1.x, e1.y, e1.z).multiply(dot)
        candidate = candidate - e1_scaled
        if candidate.Length > EPS:
            candidate.normalize()
            e2 = candidate
            break
    if e2 is None:
        raise ValueError("Cannot flatten a collinear panel")
    result = [[(point - origin).dot(e1), (point - origin).dot(e2)] for point in pts]
    min_x = min(point[0] for point in result)
    min_y = min(point[1] for point in result)
    return [[round(point[0] - min_x, 6), round(point[1] - min_y, 6)] for point in result]


def _polygon_area(outline: Sequence[Sequence[float]]) -> float:
    return abs(
        0.5
        * sum(
            outline[index][0] * outline[(index + 1) % len(outline)][1]
            - outline[(index + 1) % len(outline)][0] * outline[index][1]
            for index in range(len(outline))
        )
    )


def _json_points(points: Sequence[Any]) -> str:
    return json.dumps(
        [[round(float(point.x), 6), round(float(point.y), 6), round(float(point.z), 6)] for point in points],
        separators=(",", ":"),
    )


def _bevels(role: str, angle: float) -> List[Dict[str, Any]]:
    angle_text = f"{angle:.3f}".rstrip("0").rstrip(".")
    if role == "BottomFlat":
        description = f"Longitudinal chine mating edges; bevel-machine to {angle_text} deg after laser cut"
        return [{"edge": 0, "description": description}, {"edge": 2, "description": description}]
    if role.startswith("Chine"):
        description = f"Mates flat bottom and vertical side; post-laser bevel to {angle_text} deg"
        return [{"edge": 0, "description": description}, {"edge": 2, "description": description}]
    if role.startswith("Side"):
        return [{"edge": 0, "description": "Bottom chine mating edge; bevel-machine after nominal cut"}]
    if role == "Deck":
        return [{"edge": 0, "description": "Removable deck support edge; keep CUT outline nominal"}]
    if role == "Transom":
        return [{"edge": 1, "description": "Transom-to-bottom and side butt joint; post-laser bevel"}]
    if role == "Bulkhead":
        return [{"edge": 0, "description": "Section bulkhead mating perimeter; bevel as required for shell angle"}]
    if role == "Connector":
        return [{"edge": 0, "description": "Deck connector end; post-laser fit/bevel, no shell overlap"}]
    return []


def _make_spec(
    panel_id: str,
    hull_id: str,
    role: str,
    points: Sequence[Any],
    inward: Sequence[float],
    thickness: float,
    angle: float,
    **metadata: Any,
) -> Dict[str, Any]:
    pts = _point_list(points)
    outline = _flatten_points(pts)
    return {
        "id": panel_id,
        "hull_id": hull_id,
        "role": role,
        "quantity": 1,
        "thickness": float(thickness),
        "source_face": pts,
        "inward": [float(inward[0]), float(inward[1]), float(inward[2])],
        "outline": outline,
        "holes": [],
        "bevels": _bevels(role, angle),
        "metadata": metadata,
    }


def _positive(params: Mapping[str, float], key: str) -> float:
    value = float(params[key])
    if value <= EPS:
        raise ValueError(f"Hull parameter {key} must be positive, got {value}")
    return value


def _stations(length: float, first: float, spacing: float, count: int) -> List[float]:
    if count < 1:
        raise ValueError("StationCount must be at least one")
    if first <= 0 or spacing <= 0:
        raise ValueError("StationFirst and StationSpacing must be positive")
    regular = [first + index * spacing for index in range(count)]
    if regular[-1] < length - EPS:
        return regular
    # A short ama cannot fit five 170 mm intervals.  Keep five named stations,
    # clipping the final station to the ama bow so the station count remains
    # explicit without inventing a hull extension.
    result = [value for value in regular if value < length - EPS]
    if len(result) < count:
        result.append(length)
    return result[:count]


def _profile_width(x: float, length: float, full_width: float, entrance: float) -> float:
    if entrance <= EPS or x <= length - entrance:
        return full_width
    if x >= length:
        return 0.0
    return max(0.0, full_width * (length - x) / entrance)


def _bottom_width(top_width: float, full_width: float, flat_width: float) -> float:
    if top_width <= EPS:
        return 0.0
    # Preserve the specified 55 mm horizontal chamfer run for cat/main/ama.
    run = max(0.0, (full_width - flat_width) * 0.5)
    return max(0.0, top_width - 2.0 * run)


def _section_values(
    x: float,
    hull: Mapping[str, float],
    angle: float,
) -> Dict[str, float]:
    top = _profile_width(x, hull["length"], hull["width"], hull["entrance"])
    bottom = _bottom_width(top, hull["width"], hull["bottom_flat"])
    run = max(0.0, (top - bottom) * 0.5)
    rise = run * math.tan(math.radians(angle))
    return {"top": top, "bottom": bottom, "run": run, "rise": rise}


def _hull_specs(params: Mapping[str, float], hull: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], List[float]]:
    angle = float(params["DeadriseAngle"])
    thickness = _positive(params, "PlywoodT")
    station_positions = _stations(
        float(hull["length"]),
        float(params["StationFirst"]),
        float(params["StationSpacing"]),
        int(params["StationCount"]),
    )
    boundaries: List[float] = [0.0]
    boundaries.extend(station for station in station_positions if station > EPS and station < hull["length"] - EPS)
    boundaries.append(float(hull["length"]))
    boundaries = sorted(set(round(value, 6) for value in boundaries))
    specs: List[Dict[str, Any]] = []
    prefix = str(hull["prefix"])
    center = float(hull["center"])
    base_z = float(hull["base_z"])
    top_z = base_z + float(hull["height"])

    for segment in range(len(boundaries) - 1):
        x0, x1 = boundaries[segment], boundaries[segment + 1]
        s0 = _section_values(x0, hull, angle)
        s1 = _section_values(x1, hull, angle)
        # Short hulls (ama) taper to zero width inside the last station span;
        # skip segments whose section is fully collapsed so no degenerate
        # zero-area panel faces are emitted.
        if s0["bottom"] <= EPS and s1["bottom"] <= EPS:
            # Bottom panel collapses before the bow on short hulls.
            continue
        # Outer nominal face profiles.  Extrusion is toward the local center
        # and upward, preserving the specified outside envelope.
        bottom_points = [
            (x0, center - s0["bottom"] * 0.5, base_z),
            (x1, center - s1["bottom"] * 0.5, base_z),
            (x1, center + s1["bottom"] * 0.5, base_z),
            (x0, center + s0["bottom"] * 0.5, base_z),
        ]
        specs.append(
            _make_spec(
                f"{prefix}-BOTTOM-{segment + 1:02d}",
                prefix,
                "BottomFlat",
                bottom_points,
                (0.0, 0.0, 1.0),
                thickness,
                angle,
                segment=segment + 1,
                x0=x0,
                x1=x1,
                outer_surface="flat bottom",
            )
        )
        # Port is negative local y, starboard is positive local y.
        port_chine = [
            (x0, center - s0["bottom"] * 0.5, base_z),
            (x1, center - s1["bottom"] * 0.5, base_z),
            (x1, center - s1["top"] * 0.5, base_z + s1["rise"]),
            (x0, center - s0["top"] * 0.5, base_z + s0["rise"]),
        ]
        starboard_chine = [
            (x0, center + s0["bottom"] * 0.5, base_z),
            (x0, center + s0["top"] * 0.5, base_z + s0["rise"]),
            (x1, center + s1["top"] * 0.5, base_z + s1["rise"]),
            (x1, center + s1["bottom"] * 0.5, base_z),
        ]
        specs.append(
            _make_spec(
                f"{prefix}-CHINE-PORT-{segment + 1:02d}",
                prefix,
                "ChinePort",
                port_chine,
                (0.0, 1.0, 1.0),
                thickness,
                angle,
                segment=segment + 1,
                x0=x0,
                x1=x1,
                outer_surface="port 15 deg chamfer",
            )
        )
        specs.append(
            _make_spec(
                f"{prefix}-CHINE-STARBOARD-{segment + 1:02d}",
                prefix,
                "ChineStarboard",
                starboard_chine,
                (0.0, -1.0, 1.0),
                thickness,
                angle,
                segment=segment + 1,
                x0=x0,
                x1=x1,
                outer_surface="starboard 15 deg chamfer",
            )
        )
        port_side = [
            (x0, center - s0["top"] * 0.5, base_z + s0["rise"]),
            (x1, center - s1["top"] * 0.5, base_z + s1["rise"]),
            (x1, center - s1["top"] * 0.5, top_z),
            (x0, center - s0["top"] * 0.5, top_z),
        ]
        starboard_side = [
            (x0, center + s0["top"] * 0.5, base_z + s0["rise"]),
            (x0, center + s0["top"] * 0.5, top_z),
            (x1, center + s1["top"] * 0.5, top_z),
            (x1, center + s1["top"] * 0.5, base_z + s1["rise"]),
        ]
        specs.append(
            _make_spec(
                f"{prefix}-SIDE-PORT-{segment + 1:02d}",
                prefix,
                "SidePort",
                port_side,
                (0.0, 1.0, 0.0),
                thickness,
                angle,
                segment=segment + 1,
                x0=x0,
                x1=x1,
                outer_surface="vertical port side",
            )
        )
        specs.append(
            _make_spec(
                f"{prefix}-SIDE-STARBOARD-{segment + 1:02d}",
                prefix,
                "SideStarboard",
                starboard_side,
                (0.0, -1.0, 0.0),
                thickness,
                angle,
                segment=segment + 1,
                x0=x0,
                x1=x1,
                outer_surface="vertical starboard side",
            )
        )

    # Closed transom at x=0.  The section face ends at the design top, while
    # station bulkheads stop at the deck support underside.
    section = _section_values(0.0, hull, angle)
    transom_points = [
        (0.0, center - section["bottom"] * 0.5, base_z),
        (0.0, center + section["bottom"] * 0.5, base_z),
        (0.0, center + section["top"] * 0.5, base_z + section["rise"]),
        (0.0, center + section["top"] * 0.5, top_z),
        (0.0, center - section["top"] * 0.5, top_z),
        (0.0, center - section["top"] * 0.5, base_z + section["rise"]),
    ]
    specs.append(
        _make_spec(
            f"{prefix}-TRANSOM-01",
            prefix,
            "Transom",
            transom_points,
            (1.0, 0.0, 0.0),
            thickness,
            angle,
            closed=True,
            station=0,
        )
    )

    # Five section bulkheads are solid planar frames.  Solid frames are chosen
    # intentionally: no unnecessary radius holes or mass optimisation is
    # introduced at this geometry-study stage.
    for station_index, x in enumerate(station_positions, start=1):
        section = _section_values(x, hull, angle)
        if section["top"] <= EPS:
            # Station lies beyond the collapsed bow of a short hull.
            continue
        support_top = float(params["DeckHeight"])
        if support_top <= base_z + section["rise"] + EPS:
            raise ValueError(
                f"DeckHeight {support_top} is below chine at {prefix} station {x}; "
                "raise DeckHeight or revise hull height"
            )
        bulkhead_points = [
            (x, center - section["bottom"] * 0.5, base_z),
            (x, center + section["bottom"] * 0.5, base_z),
            (x, center + section["top"] * 0.5, base_z + section["rise"]),
            (x, center + section["top"] * 0.5, support_top),
            (x, center - section["top"] * 0.5, support_top),
            (x, center - section["top"] * 0.5, base_z + section["rise"]),
        ]
        specs.append(
            _make_spec(
                f"{prefix}-BULKHEAD-{station_index:02d}",
                prefix,
                "Bulkhead",
                bulkhead_points,
                (1.0, 0.0, 0.0),
                thickness,
                angle,
                station=station_index,
                station_x=x,
                opening_radius=float(params["MinInnerRadius"]),
                opening="solid bulkhead; no opening required",
            )
        )

    # Removable deck modules: the shell top is 140 mm absolute; a 120 mm
    # support underside plus 20 mm stock reaches that top exactly.  Ama base
    # is raised 30 mm, so its 110 mm shell also ends at 140 mm.
    deck_z = float(params["DeckHeight"])
    deck_t = float(params["DeckThickness"])
    for segment in range(len(boundaries) - 1):
        x0, x1 = boundaries[segment], boundaries[segment + 1]
        w0 = _profile_width(x0, hull["length"], hull["width"], hull["entrance"])
        w1 = _profile_width(x1, hull["length"], hull["width"], hull["entrance"])
        deck_points = [
            (x0, center - w0 * 0.5, deck_z),
            (x1, center - w1 * 0.5, deck_z),
            (x1, center + w1 * 0.5, deck_z),
            (x0, center + w0 * 0.5, deck_z),
        ]
        specs.append(
            _make_spec(
                f"{prefix}-DECK-{segment + 1:02d}",
                prefix,
                "Deck",
                deck_points,
                (0.0, 0.0, 1.0),
                deck_t,
                angle,
                segment=segment + 1,
                removable=True,
                support_underside=deck_z,
                top_z=deck_z + deck_t,
            )
        )
    return specs, station_positions


def _default_params(design_name: str) -> Dict[str, float]:
    name = str(design_name).strip().lower()
    if name not in {"catamaran", "trimaran"}:
        raise ValueError("design_name must be Catamaran or Trimaran")
    values: Dict[str, float] = {}
    for key, _kind, _alias, default in PARAMETER_DEFS:
        values[key] = _quantity_value(default)
    if name == "catamaran":
        values.update(
            {
                "HullWidthSingle": 260.0,
                "MainHullWidth": 260.0,
                "BottomFlatSingle": 150.0,
                "MainBottomFlat": 150.0,
                "CatCenterOffset": 145.0,
                "BowEntranceCat": 220.0,
                "AmaLength": 600.0,
            }
        )
    else:
        values.update(
            {
                "HullWidthSingle": 300.0,
                "MainHullWidth": 300.0,
                "BottomFlatSingle": 190.0,
                "MainBottomFlat": 190.0,
                "CatCenterOffset": 145.0,
                "BowEntranceMain": 270.0,
                "AmaWidth": 100.0,
                "AmaLength": 600.0,
                "AmaCenterOffset": 225.0,
                "AmaHeight": 110.0,
                "AmaBaseZ": 30.0,
                "AmaBottomFlat": 50.0,
                "TriGap": 25.0,
            }
        )
    values["DeadriseRise"] = math.tan(math.radians(values["DeadriseAngle"])) * values["DeadriseRun"]
    return values


def _hulls_for_design(design_name: str, params: Mapping[str, float]) -> List[Dict[str, Any]]:
    name = str(design_name).strip().lower()
    length = _positive(params, "HullLength")
    if name == "catamaran":
        width = _positive(params, "HullWidthSingle")
        return [
            {
                "prefix": "CAT-PORT",
                "center": -float(params["CatCenterOffset"]),
                "width": width,
                "length": length,
                "height": _positive(params, "HullHeight"),
                "base_z": 0.0,
                "bottom_flat": _positive(params, "BottomFlatSingle"),
                "entrance": _positive(params, "BowEntranceCat"),
            },
            {
                "prefix": "CAT-STARBOARD",
                "center": float(params["CatCenterOffset"]),
                "width": width,
                "length": length,
                "height": _positive(params, "HullHeight"),
                "base_z": 0.0,
                "bottom_flat": _positive(params, "BottomFlatSingle"),
                "entrance": _positive(params, "BowEntranceCat"),
            },
        ]
    if name == "trimaran":
        main_width = _positive(params, "MainHullWidth")
        ama_width = _positive(params, "AmaWidth")
        return [
            {
                "prefix": "TRI-MAIN",
                "center": 0.0,
                "width": main_width,
                "length": length,
                "height": _positive(params, "HullHeight"),
                "base_z": 0.0,
                "bottom_flat": _positive(params, "MainBottomFlat"),
                "entrance": _positive(params, "BowEntranceMain"),
            },
            {
                "prefix": "TRI-AMA-PORT",
                "center": -float(params["AmaCenterOffset"]),
                "width": ama_width,
                "length": _positive(params, "AmaLength"),
                "height": _positive(params, "AmaHeight"),
                "base_z": _positive(params, "AmaBaseZ"),
                "bottom_flat": _positive(params, "AmaBottomFlat"),
                "entrance": _positive(params, "BowEntranceAma"),
            },
            {
                "prefix": "TRI-AMA-STARBOARD",
                "center": float(params["AmaCenterOffset"]),
                "width": ama_width,
                "length": _positive(params, "AmaLength"),
                "height": _positive(params, "AmaHeight"),
                "base_z": _positive(params, "AmaBaseZ"),
                "bottom_flat": _positive(params, "AmaBottomFlat"),
                "entrance": _positive(params, "BowEntranceAma"),
            },
        ]
    raise ValueError("design_name must be Catamaran or Trimaran")


def build_panel_specs(design_name: str, params: Mapping[str, float]) -> Tuple[List[Dict[str, Any]], Dict[str, List[float]]]:
    """Return all panel descriptors and station positions for a design."""
    specs: List[Dict[str, Any]] = []
    stations: Dict[str, List[float]] = {}
    for hull in _hulls_for_design(design_name, params):
        hull_specs, hull_stations = _hull_specs(params, hull)
        specs.extend(hull_specs)
        stations[hull["prefix"]] = hull_stations

    # Four requested connector positions.  Connectors occupy only the clear
    # gaps; they never intrude into shell stock.  At x=630 the ama has ended,
    # so the trimaran connector remains a main-deck gap brace rather than a
    # fabricated ama extension.
    connector_xs = [
        float(params["ConnectorX1"]),
        float(params["ConnectorX2"]),
        float(params["ConnectorX3"]),
        float(params["ConnectorX4"]),
    ]
    connector_width = _positive(params, "ConnectorWidth")
    deck_z = float(params["DeckHeight"])
    deck_t = float(params["DeckThickness"])
    angle = float(params["DeadriseAngle"])
    name = str(design_name).strip().lower()
    gaps: List[Tuple[str, float, float]] = []
    if name == "catamaran":
        half_gap = float(params["HullGap"]) * 0.5
        gaps.append(("CAT-GAP", -half_gap, half_gap))
    else:
        main_half = float(params["MainHullWidth"]) * 0.5
        ama_inner = float(params["AmaCenterOffset"]) - float(params["AmaWidth"]) * 0.5
        gaps.extend(
            [
                ("TRI-GAP-PORT", -ama_inner, -main_half),
                ("TRI-GAP-STARBOARD", main_half, ama_inner),
            ]
        )
    for connector_index, x in enumerate(connector_xs, start=1):
        x0 = x - connector_width * 0.5
        x1 = x + connector_width * 0.5
        for gap_id, y0, y1 in gaps:
            if y1 <= y0:
                raise ValueError(f"Connector gap {gap_id} is inverted: {y0}, {y1}")
            points = [(x0, y0, deck_z), (x1, y0, deck_z), (x1, y1, deck_z), (x0, y1, deck_z)]
            suffix = gap_id.replace("TRI-GAP-", "").replace("CAT-GAP", "CENTER")
            specs.append(
                _make_spec(
                    f"{name.upper()}-CONNECTOR-{suffix}-{connector_index:02d}",
                    "CONNECTORS",
                    "Connector",
                    points,
                    (0.0, 0.0, 1.0),
                    deck_t,
                    angle,
                    connector_x=x,
                    gap=gap_id,
                    gap_start=y0,
                    gap_end=y1,
                    no_shell_overlap=True,
                )
            )
    return specs, stations


def _layout_outline(outline: Sequence[Sequence[float]], rotation: int, x: float, y: float) -> List[List[float]]:
    min_x = min(point[0] for point in outline)
    min_y = min(point[1] for point in outline)
    local = [[point[0] - min_x, point[1] - min_y] for point in outline]
    if rotation:
        width = max(point[0] for point in local)
        local = [[point[1], width - point[0]] for point in local]
    return [[round(point[0] + x, 6), round(point[1] + y, 6)] for point in local]


def _layout_specs(specs: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """Deterministic shelf nesting on 1000 x 600 sheets, max six sheets."""
    items: List[Tuple[float, str, float, float]] = []
    for spec in specs:
        outline = spec["outline"]
        width = max(point[0] for point in outline) - min(point[0] for point in outline)
        height = max(point[1] for point in outline) - min(point[1] for point in outline)
        if width <= EPS or height <= EPS:
            raise ValueError(f"Panel {spec['id']} has a degenerate flattened outline")
        items.append((width * height, spec["id"], width, height))
    items.sort(key=lambda item: (-item[0], item[1]))
    sheets: List[Dict[str, float]] = []
    placements: Dict[str, Dict[str, Any]] = {}

    def try_place(state: Dict[str, float], width: float, height: float, rotation: int) -> Tuple[float, float] | None:
        x = state["x"]
        y = state["y"]
        row_h = state["row_h"]
        if x + width > SHEET_WIDTH - SHEET_MARGIN + EPS:
            x = SHEET_MARGIN
            y = y + row_h + SHEET_GAP
            row_h = 0.0
        if y + height > SHEET_HEIGHT - SHEET_MARGIN + EPS:
            return None
        state["x"] = x + width + SHEET_GAP
        state["row_h"] = max(row_h, height)
        return x, y

    for _area, panel_id, width, height in items:
        placed = False
        for sheet_index, state in enumerate(sheets, start=1):
            snapshot = dict(state)
            candidates = [(0, width, height), (90, height, width)]
            candidates.sort(key=lambda candidate: (candidate[2], candidate[1], candidate[0]))
            for rotation, candidate_w, candidate_h in candidates:
                state.clear()
                state.update(snapshot)
                result = try_place(state, candidate_w, candidate_h, rotation)
                if result is not None:
                    x, y = result
                    placements[panel_id] = {
                        "sheet": sheet_index,
                        "x": x,
                        "y": y,
                        "rotation": rotation,
                        "outline": _layout_outline(spec_by_id[panel_id]["outline"], rotation, x, y),
                    }
                    placed = True
                    break
            if placed:
                break
        if not placed:
            if len(sheets) >= 6:
                raise RuntimeError(
                    f"Nesting requires more than 6 sheets for {panel_id}; "
                    "do not split panels arbitrarily; revise panel layout"
                )
            state = {"x": SHEET_MARGIN, "y": SHEET_MARGIN, "row_h": 0.0}
            sheets.append(state)
            candidates = [(0, width, height), (90, height, width)]
            candidates.sort(key=lambda candidate: (candidate[2], candidate[1], candidate[0]))
            for rotation, candidate_w, candidate_h in candidates:
                result = try_place(state, candidate_w, candidate_h, rotation)
                if result is not None:
                    x, y = result
                    placements[panel_id] = {
                        "sheet": len(sheets),
                        "x": x,
                        "y": y,
                        "rotation": rotation,
                        "outline": _layout_outline(spec_by_id[panel_id]["outline"], rotation, x, y),
                    }
                    placed = True
                    break
        if not placed:
            raise RuntimeError(f"Panel {panel_id} does not fit a 1000 x 600 mm sheet")
    return placements, len(sheets)


# _layout_specs uses this short-lived index to keep the function deterministic
# without storing a second copy of every panel descriptor in each placement.
spec_by_id: Dict[str, Dict[str, Any]] = {}


def _pack_specs(specs: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], int]:
    global spec_by_id
    spec_by_id = {spec["id"]: spec for spec in specs}
    try:
        return _layout_specs(specs)
    finally:
        spec_by_id = {}


def _property_number(obj: Any, name: str) -> float:
    try:
        return _number(getattr(obj, name))
    except Exception as exc:  # pragma: no cover - FreeCAD reports exact field
        raise RuntimeError(f"Controller property {name!r} is unavailable") from exc


def _params_from_controller(controller: Any) -> Dict[str, float]:
    params: Dict[str, float] = {}
    for key, _kind, _alias, _default in PARAMETER_DEFS:
        params[key] = _property_number(controller, key)
    params["StationCount"] = int(round(params["StationCount"]))
    params["DeadriseRise"] = math.tan(math.radians(params["DeadriseAngle"])) * params["DeadriseRun"]
    if params["DeadriseRise"] <= EPS:
        raise ValueError("Derived DeadriseRise is zero; check DeadriseAngle and DeadriseRun")
    return params


def _shape_for_spec(spec: Mapping[str, Any]) -> Tuple[Any, List[Any]]:
    return _solid(spec["source_face"], spec["inward"], float(spec["thickness"]))


def _set_panel_properties(obj: Any, spec: Mapping[str, Any], controller: Any) -> None:
    obj.PanelId = str(spec["id"])
    obj.HullId = str(spec["hull_id"])
    obj.PanelRole = str(spec["role"])
    obj.Quantity = int(spec["quantity"])
    obj.SourceFacePointsJSON = _json_points(spec["source_face"])
    obj.FlattenedOutlineJSON = json.dumps(spec["outline"], separators=(",", ":"))
    obj.HolesJSON = json.dumps(spec["holes"], separators=(",", ":"))
    obj.BevelsJSON = json.dumps(spec["bevels"], separators=(",", ":"))
    obj.PanelNotes = (
        "CUT is the finished nominal outline. Apply kerf compensation outside the toolpath "
        "(+0.1 mm) rather than shrinking this stock profile. Any angle is post-laser bevel machining."
    )
    obj.Controller = controller
    obj.ViewObject.ShapeColor = (0.58, 0.60, 0.63)
    obj.ViewObject.LineColor = (0.12, 0.12, 0.14)
    obj.ViewObject.Transparency = 0
    obj.ViewObject.Visibility = True


def _add_panel_object(doc: Any, group: Any, spec: Mapping[str, Any], controller: Any) -> Any:
    safe_id = re.sub(r"[^A-Za-z0-9_]", "_", str(spec["id"]))
    obj = doc.addObject("Part::Feature", safe_id)
    obj.Label = f"{spec['id']} | {spec['role']} | nominal plywood 20 mm"
    obj.addProperty("App::PropertyString", "PanelId", "Panel")
    obj.addProperty("App::PropertyString", "HullId", "Panel")
    obj.addProperty("App::PropertyString", "PanelRole", "Panel")
    obj.addProperty("App::PropertyInteger", "Quantity", "Panel")
    obj.addProperty("App::PropertyLength", "Thickness", "Panel")
    obj.addProperty("App::PropertyLink", "Controller", "Relationships")
    obj.addProperty("App::PropertyString", "SourceFacePointsJSON", "Panel")
    obj.addProperty("App::PropertyString", "FlattenedOutlineJSON", "Panel")
    obj.addProperty("App::PropertyString", "HolesJSON", "Panel")
    obj.addProperty("App::PropertyString", "BevelsJSON", "Panel")
    obj.addProperty("App::PropertyString", "PanelNotes", "Panel")
    obj.addProperty("App::PropertyString", "MatingSurface", "Panel")
    obj.MatingSurface = str(spec["metadata"].get("outer_surface", spec["role"]))
    obj.setExpression("Thickness", f"{controller.Name}.PlywoodT")
    _set_panel_properties(obj, spec, controller)
    shape, _pts = _shape_for_spec(spec)
    obj.Shape = shape
    group.addObject(obj)
    return obj


def _add_pattern_objects(
    doc: Any,
    group: Any,
    specs: Sequence[Mapping[str, Any]],
    panel_objects: Mapping[str, Any],
    controller: Any,
) -> Tuple[Dict[str, Any], Dict[int, Any]]:
    pattern_objects: Dict[str, Any] = {}
    for spec in specs:
        safe_id = re.sub(r"[^A-Za-z0-9_]", "_", str(spec["id"]))
        obj = doc.addObject("Part::Feature", f"Pattern_{safe_id}")
        obj.Label = f"CUT {spec['id']} (nominal; kerf outside +0.1 mm)"
        obj.addProperty("App::PropertyString", "PatternForId", "Pattern")
        obj.addProperty("App::PropertyLink", "SourcePanel", "Relationships")
        obj.addProperty("App::PropertyLink", "Controller", "Relationships")
        obj.addProperty("App::PropertyInteger", "SheetIndex", "Pattern")
        obj.addProperty("App::PropertyLength", "PlacementX", "Pattern")
        obj.addProperty("App::PropertyLength", "PlacementY", "Pattern")
        obj.addProperty("App::PropertyAngle", "PatternRotation", "Pattern")
        obj.addProperty("App::PropertyString", "OutlineJSON", "Pattern")
        obj.PatternForId = str(spec["id"])
        obj.SourcePanel = panel_objects[spec["id"]]
        obj.Controller = controller
        obj.ViewObject.ShapeColor = (0.72, 0.58, 0.33)
        obj.ViewObject.LineColor = (0.16, 0.12, 0.08)
        obj.ViewObject.Transparency = 0
        obj.ViewObject.Visibility = True
        group.addObject(obj)
        pattern_objects[spec["id"]] = obj
    boundaries: Dict[int, Any] = {}
    for index in range(1, 7):
        boundary = doc.addObject("Part::Feature", f"SheetBoundary_{index:02d}")
        boundary.Label = f"Sheet {index:02d} | 1000 x 600 mm"
        boundary.addProperty("App::PropertyInteger", "SheetIndex", "Pattern")
        boundary.addProperty("App::PropertyLink", "Controller", "Relationships")
        boundary.SheetIndex = index
        boundary.Controller = controller
        boundary.Shape = Part.makePolygon(
            [
                App.Vector(0, 0, 0),
                App.Vector(SHEET_WIDTH, 0, 0),
                App.Vector(SHEET_WIDTH, SHEET_HEIGHT, 0),
                App.Vector(0, SHEET_HEIGHT, 0),
                App.Vector(0, 0, 0),
            ]
        )
        boundary.ViewObject.LineColor = (0.85, 0.55, 0.10)
        boundary.ViewObject.LineWidth = 2.0
        boundary.ViewObject.Visibility = index == 1
        group.addObject(boundary)
        boundaries[index] = boundary
    return pattern_objects, boundaries


def _update_pattern_objects(
    pattern_objects: Mapping[str, Any],
    boundaries: Mapping[int, Any],
    specs: Sequence[Mapping[str, Any]],
    placements: Mapping[str, Mapping[str, Any]],
) -> int:
    by_id = {spec["id"]: spec for spec in specs}
    sheet_count = max(int(item["sheet"]) for item in placements.values()) if placements else 0
    for panel_id, obj in pattern_objects.items():
        spec = by_id[panel_id]
        placement = placements[panel_id]
        outline = placement["outline"]
        points = [App.Vector(point[0], point[1], 0.0) for point in outline]
        obj.Shape = Part.Face(Part.makePolygon(points + [points[0]]))
        obj.SheetIndex = int(placement["sheet"])
        obj.PlacementX = float(placement["x"])
        obj.PlacementY = float(placement["y"])
        obj.PatternRotation = float(placement["rotation"])
        obj.OutlineJSON = json.dumps(outline, separators=(",", ":"))
        obj.ViewObject.Visibility = True
    for index, boundary in boundaries.items():
        boundary.ViewObject.Visibility = index <= sheet_count
    return sheet_count


def _update_reference_objects(
    reference_objects: Mapping[str, Any],
    design_name: str,
    params: Mapping[str, float],
    station_positions: Mapping[str, Sequence[float]],
) -> None:
    length = float(params["HullLength"])
    deck_z = float(params["DeckHeight"])
    axis = Part.makeLine(App.Vector(0, 0, 0), App.Vector(length, 0, 0))
    waterline = Part.makeLine(App.Vector(0, 0, deck_z), App.Vector(length, 0, deck_z))
    station_edges: List[Any] = []
    for positions in station_positions.values():
        for x in positions:
            station_edges.append(Part.makeLine(App.Vector(x, -300, 0), App.Vector(x, 300, 0)))
    reference_objects["Axis"].Shape = axis
    reference_objects["Waterline"].Shape = waterline
    reference_objects["Stations"].Shape = Part.makeCompound(station_edges)
    for obj in reference_objects.values():
        obj.ViewObject.LineColor = (0.18, 0.42, 0.80)
        obj.ViewObject.LineWidth = 2.0
        obj.ViewObject.Visibility = True


def _create_reference_objects(doc: Any, group: Any, controller: Any) -> Dict[str, Any]:
    objects: Dict[str, Any] = {}
    for suffix, label, role in (
        ("Axis", "Reference | longitudinal centerline", "axis"),
        ("Waterline", "Reference | deck support/waterline z=120", "waterline"),
        ("Stations", "Reference | section station markers", "stations"),
    ):
        obj = doc.addObject("Part::Feature", f"Reference_{suffix}")
        obj.Label = label
        obj.addProperty("App::PropertyString", "ReferenceRole", "Reference")
        obj.addProperty("App::PropertyLink", "Controller", "Relationships")
        obj.ReferenceRole = role
        obj.Controller = controller
        group.addObject(obj)
        objects[suffix] = obj
    return objects


def _hash_specs(specs: Sequence[Mapping[str, Any]], sheet_count: int) -> str:
    canonical = []
    for spec in specs:
        canonical.append(
            {
                "id": spec["id"],
                "role": spec["role"],
                "source_face": [[round(float(p.x), 6), round(float(p.y), 6), round(float(p.z), 6)] for p in spec["source_face"]],
                "thickness": round(float(spec["thickness"]), 6),
            }
        )
    canonical.append({"sheet_count": sheet_count})
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def _objects_by_panel_id(group: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for obj in group.Group:
        if hasattr(obj, "PanelId"):
            panel_id = str(obj.PanelId)
            if panel_id in result:
                raise RuntimeError(f"Duplicate panel ID in HullAssembled: {panel_id}")
            result[panel_id] = obj
    return result


_REBUILD_IN_PROGRESS: set[int] = set()


def _rebuild_document(controller: Any) -> Dict[str, Any]:
    token = id(controller)
    if token in _REBUILD_IN_PROGRESS:
        return {"panel_count": 0, "sheet_count": 0}
    _REBUILD_IN_PROGRESS.add(token)
    try:
        design_name = str(controller.DesignName)
        params = _params_from_controller(controller)
        specs, stations = build_panel_specs(design_name, params)
        placements, sheet_count = _pack_specs(specs)
        hull_group = controller.HullAssembled
        pattern_group = controller.PanelPattern
        reference_group = controller.Reference
        if hull_group is None or pattern_group is None or reference_group is None:
            raise RuntimeError("HullModelController links HullAssembled, PanelPattern, and Reference are required")
        panel_objects = _objects_by_panel_id(hull_group)
        expected_ids = {spec["id"] for spec in specs}
        if set(panel_objects) != expected_ids:
            missing = sorted(expected_ids - set(panel_objects))
            extra = sorted(set(panel_objects) - expected_ids)
            raise RuntimeError(f"Panel object mismatch; missing={missing}, extra={extra}")
        for spec in specs:
            obj = panel_objects[spec["id"]]
            shape, pts = _shape_for_spec(spec)
            obj.Shape = shape
            # Use the exact generated outside face points as exporter source.
            obj.SourceFacePointsJSON = _json_points(pts)
            obj.FlattenedOutlineJSON = json.dumps(_flatten_points(pts), separators=(",", ":"))
            obj.BevelsJSON = json.dumps(spec["bevels"], separators=(",", ":"))
            obj.HolesJSON = json.dumps(spec["holes"], separators=(",", ":"))
            obj.MatingSurface = str(spec["metadata"].get("outer_surface", spec["role"]))
            obj.ViewObject.Visibility = True
        pattern_objects = {
            str(obj.PatternForId): obj
            for obj in pattern_group.Group
            if hasattr(obj, "PatternForId")
        }
        boundaries = {
            int(obj.SheetIndex): obj
            for obj in pattern_group.Group
            if hasattr(obj, "SheetIndex") and str(obj.Name).startswith("SheetBoundary_")
        }
        if set(pattern_objects) != expected_ids:
            raise RuntimeError("PanelPattern is missing one or more source panel patterns")
        sheet_count = _update_pattern_objects(pattern_objects, boundaries, specs, placements)
        reference_objects = {
            "Axis": reference_group.Document.getObject("Reference_Axis"),
            "Waterline": reference_group.Document.getObject("Reference_Waterline"),
            "Stations": reference_group.Document.getObject("Reference_Stations"),
        }
        if any(value is None for value in reference_objects.values()):
            raise RuntimeError("Reference group is missing axis, waterline, or station markers")
        _update_reference_objects(reference_objects, design_name, params, stations)
        controller.PanelCount = len(specs)
        controller.SheetCount = int(sheet_count)
        controller.RebuildSignature = _hash_specs(specs, sheet_count)
        controller.ManifestPath = os.path.join(str(controller.ProjectRoot), "export", "panels.json")
        return {
            "panel_count": len(specs),
            "sheet_count": int(sheet_count),
            "stations": stations,
            "signature": controller.RebuildSignature,
        }
    finally:
        _REBUILD_IN_PROGRESS.discard(token)


class HullModelProxy:
    """Persistent FeaturePython proxy that rebuilds from HullParams expressions."""

    def __init__(self, obj: Any, design_name: str):
        self.design_name = str(design_name)
        self.Object = obj
        obj.Proxy = self

    def execute(self, obj: Any) -> None:
        if str(getattr(obj, "DesignName", self.design_name)) != self.design_name:
            self.design_name = str(obj.DesignName)
        _rebuild_document(obj)

    def onDocumentRestored(self, obj: Any) -> None:
        self.Object = obj
        if hasattr(obj, "DesignName"):
            self.design_name = str(obj.DesignName)

    def __getstate__(self) -> Dict[str, Any]:
        return {"design_name": self.design_name}

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        self.design_name = str(state.get("design_name", "Catamaran"))
        self.Object = None


def _create_spreadsheet(doc: Any, design_name: str, values: Mapping[str, float]) -> Any:
    sheet = doc.addObject("Spreadsheet::Sheet", "HullParams")
    sheet.Label = "HullParams | spreadsheet-driven dimensions"
    row = 1
    sheet.set(f"A{row}", "KKI2026 planar plywood hull parameters")
    sheet.set(f"B{row}", str(design_name))
    row += 1
    for key, _kind, alias, _default in PARAMETER_DEFS:
        sheet.set(f"A{row}", key)
        if key == "DeadriseRise":
            # Set after all aliases exist below.
            sheet.set(f"B{row}", "0 mm")
        elif _kind == "App::PropertyInteger":
            sheet.set(f"B{row}", str(int(round(values[key]))))
        elif _kind == "App::PropertyAngle":
            sheet.set(f"B{row}", f"{values[key]:.6f} deg")
        else:
            sheet.set(f"B{row}", f"{values[key]:.6f} mm")
        sheet.setAlias(f"B{row}", alias)
        row += 1
    # Derived, not independently constrained: 55*tan(15 deg)=14.737 mm.
    rise_row = 2 + [item[0] for item in PARAMETER_DEFS].index("DeadriseRise")
    sheet.set(f"B{rise_row}", "=tan(DeadriseAngle)*DeadriseRun")
    sheet.setStyle(f"A1:B{row - 1}", "bold", "add")
    return sheet


def _controller_property_defs() -> Sequence[Tuple[str, str, str]]:
    return tuple((key, kind, alias) for key, kind, alias, _default in PARAMETER_DEFS)


def _create_controller(
    doc: Any,
    design_name: str,
    root: str,
    sheet: Any,
    hull_group: Any,
    pattern_group: Any,
    reference_group: Any,
) -> Any:
    controller = doc.addObject("App::FeaturePython", "HullModelController")
    controller.Label = f"{design_name} | persistent parametric hull controller"
    controller.addProperty("App::PropertyString", "DesignName", "Model")
    controller.addProperty("App::PropertyString", "ProjectRoot", "Model")
    controller.addProperty("App::PropertyString", "ModuleFile", "Model")
    controller.addProperty("App::PropertyString", "ModelContract", "Model")
    controller.addProperty("App::PropertyLink", "ParamSheet", "Relationships")
    controller.addProperty("App::PropertyLink", "HullAssembled", "Relationships")
    controller.addProperty("App::PropertyLink", "PanelPattern", "Relationships")
    controller.addProperty("App::PropertyLink", "Reference", "Relationships")
    controller.addProperty("App::PropertyInteger", "PanelCount", "Build")
    controller.addProperty("App::PropertyInteger", "SheetCount", "Build")
    controller.addProperty("App::PropertyString", "RebuildSignature", "Build")
    controller.addProperty("App::PropertyString", "ManifestPath", "Build")
    controller.DesignName = str(design_name)
    controller.ProjectRoot = os.path.abspath(root)
    controller.ModuleFile = os.path.abspath(__file__)
    controller.ModelContract = (
        "Nominal 20 mm plywood planar panels; CUT outline is finished nominal; "
        "toolpath offset +0.1 mm outside for 0.2 mm kerf; no hydrostatics"
    )
    controller.ParamSheet = sheet
    controller.HullAssembled = hull_group
    controller.PanelPattern = pattern_group
    controller.Reference = reference_group
    for key, kind, alias in _controller_property_defs():
        controller.addProperty(kind, key, "Hull Parameters")
        controller.setExpression(key, f"{sheet.Name}.{alias}")
    controller.Proxy = HullModelProxy(controller, design_name)
    return controller


def _solid_panel_objects(group: Any) -> List[Any]:
    result = []
    for obj in group.Group:
        if hasattr(obj, "PanelId"):
            result.append(obj)
    return result


def _bbox_overlap(a: Any, b: Any) -> bool:
    ba, bb = a.Shape.BoundBox, b.Shape.BoundBox
    return (
        min(ba.XMax, bb.XMax) - max(ba.XMin, bb.XMin) > 1.0e-5
        and min(ba.YMax, bb.YMax) - max(ba.YMin, bb.YMin) > 1.0e-5
        and min(ba.ZMax, bb.ZMax) - max(ba.ZMin, bb.ZMin) > 1.0e-5
    )


def validate_document(doc: Any) -> Dict[str, Any]:
    """Run actionable geometry/model checks and return a proof structure."""
    controller = doc.getObject("HullModelController")
    if controller is None:
        raise RuntimeError("HullModelController is missing")
    for name in ("HullAssembled", "PanelPattern", "Reference"):
        if doc.getObject(name) is None:
            raise RuntimeError(f"Required primary object/group {name} is missing")
    panels = _solid_panel_objects(controller.HullAssembled)
    if not panels:
        raise RuntimeError("HullAssembled has no panel solids")
    ids = [str(panel.PanelId) for panel in panels]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Panel IDs are not unique")
    invalid = []
    invisible = []
    for panel in panels:
        if panel.Shape.isNull() or not panel.Shape.isValid() or panel.Shape.Volume <= EPS:
            invalid.append(str(panel.PanelId))
        if not panel.ViewObject.Visibility:
            invisible.append(str(panel.PanelId))
        if _quantity_value(panel.Thickness) <= EPS:
            raise RuntimeError(f"Panel {panel.PanelId} has non-positive thickness")
    if invalid:
        raise RuntimeError(f"Invalid or zero-volume panel solids: {invalid}")
    if invisible:
        raise RuntimeError(f"Individual panel visibility is disabled: {invisible}")
    params = _params_from_controller(controller)
    design_name = str(controller.DesignName)
    specs, station_positions = build_panel_specs(design_name, params)
    expected_ids = {spec["id"] for spec in specs}
    if set(ids) != expected_ids:
        raise RuntimeError("Saved panel set does not match parameter-driven descriptors")
    expected_width = _quantity_value(params["HullWidthTotal"])
    if abs(expected_width - 550.0) > 1.0e-5 or abs(_quantity_value(params["HullLength"]) - 900.0) > 1.0e-5:
        raise RuntimeError("Hull envelope parameters must remain 900 x 550 mm")
    # Surface envelope (rather than inward stock BB) is the design envelope.
    if design_name.lower() == "catamaran":
        outer_min = -params["CatCenterOffset"] - params["HullWidthSingle"] * 0.5
        outer_max = params["CatCenterOffset"] + params["HullWidthSingle"] * 0.5
    else:
        outer_min = -params["AmaCenterOffset"] - params["AmaWidth"] * 0.5
        outer_max = params["AmaCenterOffset"] + params["AmaWidth"] * 0.5
    if abs((outer_max - outer_min) - expected_width) > 1.0e-5:
        raise RuntimeError(f"Surface envelope is {outer_max - outer_min:g} mm, expected {expected_width:g} mm")
    station_counts = {key: len(value) for key, value in station_positions.items()}
    if any(count != int(params["StationCount"]) for count in station_counts.values()):
        raise RuntimeError(f"Every hull needs {int(params['StationCount'])} stations, got {station_counts}")
    placements, sheet_count = _pack_specs(specs)
    if sheet_count > 6:
        raise RuntimeError(f"Panel nesting uses {sheet_count} sheets; maximum is 6")
    # Different hulls must remain separated.  Same-hull seam intersections are
    # intentional mating stock and are therefore not treated as collisions.
    hull_by_id = {str(panel.PanelId): str(panel.HullId) for panel in panels}
    cross_hull_collisions: List[Tuple[str, str]] = []
    for index, first in enumerate(panels):
        for second in panels[index + 1 :]:
            first_hull = hull_by_id[str(first.PanelId)]
            second_hull = hull_by_id[str(second.PanelId)]
            if first_hull == second_hull or "CONNECTORS" in {first_hull, second_hull}:
                continue
            if _bbox_overlap(first, second):
                cross_hull_collisions.append((str(first.PanelId), str(second.PanelId)))
    if cross_hull_collisions:
        raise RuntimeError(f"Cross-hull stock collision(s): {cross_hull_collisions[:5]}")
    return {
        "valid_solids": len(panels),
        "panel_count": len(panels),
        "sheet_count": sheet_count,
        "station_counts": station_counts,
        "cross_hull_collisions": cross_hull_collisions,
        "envelope_mm": {"length": 900.0, "beam": 550.0},
        "derived_chine_rise_mm": round(math.tan(math.radians(params["DeadriseAngle"])) * params["DeadriseRun"], 6),
        "placements": placements,
    }


def _face_outline_from_solid(panel: Any) -> List[List[float]]:
    if panel.Shape.isNull() or not panel.Shape.isValid() or panel.Shape.Volume <= EPS:
        raise RuntimeError(f"Cannot export invalid panel solid {panel.PanelId}")
    faces = list(panel.Shape.Faces)
    if not faces:
        raise RuntimeError(f"Panel {panel.PanelId} has no faces")
    # The source stock face is the largest face of an extrusion.  Use its
    # ordered outer wire so manifest output is derived from actual Shape data.
    source_face = max(faces, key=lambda item: item.Area)
    try:
        vertices = list(source_face.OuterWire.OrderedVertexes)
    except Exception:
        vertices = list(source_face.Vertexes)
    points = [vertex.Point for vertex in vertices]
    if len(points) < 3:
        raise RuntimeError(f"Panel {panel.PanelId} source face is degenerate")
    return _flatten_points(points)


def _design_notes(design_name: str, params: Mapping[str, float]) -> List[str]:
    return [
        "All side, bottom, transom, bulkhead, deck, and connector stock is nominal 20 mm plywood.",
        "FinishAllowance is 0 mm: dimensions are nominal plywood geometry and are not certified finished dimensions after fiberglass, resin, or fairing.",
        "CUT outlines are finished nominal profiles; apply 0.1 mm outside toolpath compensation for the specified 0.2 mm kerf rather than shrinking the parts.",
        "Planar laser cuts do not create the indicated angled butt joints; bevel-machine mating edges after cutting.",
        "Bow is a sharp planar wedge with the configured entrance length; hydrostatics, maneuvering, and wave performance are not validated by this geometry study.",
        "Five section stations are represented; the 600 mm ama clips its fifth station to the ama bow while retaining the five-station model contract.",
        "Deck panels are separate removable modules: shell/deck support underside is z=120 mm and 20 mm deck stock reaches z=140 mm.",
        "Bulkheads are intentionally solid; no inner aperture is required. If an aperture is later introduced, keep inner radius at least 6 mm.",
    ]


def _read_existing_manifest(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {"schema": SCHEMA, "units": "mm", "designs": []}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read existing manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("units") != "mm":
        raise RuntimeError(f"Manifest {path} has incompatible schema")
    if not isinstance(value.get("designs"), list):
        raise RuntimeError(f"Manifest {path} has no designs list")
    return value


def export_manifest(doc: Any, root: str) -> Dict[str, Any]:
    """Export the shared deterministic panels.json contract from actual solids."""
    root = install_module_path(root)
    export_dir = os.path.join(root, "export")
    os.makedirs(export_dir, exist_ok=True)
    controller = doc.getObject("HullModelController")
    if controller is None:
        raise RuntimeError("HullModelController is missing; cannot export manifest")
    design_name = str(controller.DesignName)
    params = _params_from_controller(controller)
    panels: List[Dict[str, Any]] = []
    for panel in sorted(_solid_panel_objects(controller.HullAssembled), key=lambda obj: str(obj.PanelId)):
        outline = _face_outline_from_solid(panel)
        holes = json.loads(str(panel.HolesJSON)) if str(panel.HolesJSON) else []
        bevels = json.loads(str(panel.BevelsJSON)) if str(panel.BevelsJSON) else []
        area = round(_polygon_area(outline), 6)
        if area <= EPS:
            raise RuntimeError(f"Panel {panel.PanelId} has zero flattened area")
        panels.append(
            {
                "id": str(panel.PanelId),
                "quantity": int(panel.Quantity),
                "thickness_mm": round(_quantity_value(panel.Thickness), 6),
                "outline": outline,
                "holes": holes,
                "bevels": bevels,
                "area_mm2": area,
            }
        )
    manifest_path = os.path.join(export_dir, "panels.json")
    manifest = _read_existing_manifest(manifest_path)
    designs = [item for item in manifest["designs"] if item.get("name") != design_name]
    designs.append(
        {
            "name": design_name,
            "panels": panels,
            "notes": _design_notes(design_name, params),
        }
    )
    order = {"Catamaran": 0, "Trimaran": 1}
    designs.sort(key=lambda item: (order.get(str(item.get("name")), 99), str(item.get("name"))))
    output = {"schema": SCHEMA, "units": "mm", "designs": designs}
    temp_path = manifest_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(output, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(temp_path, manifest_path)
    return {
        "path": manifest_path,
        "schema": SCHEMA,
        "units": "mm",
        "design": design_name,
        "panel_count": len(panels),
        "design_count": len(designs),
    }


def build_design(design_name: str, root: str) -> Dict[str, Any]:
    """Create one FreeCAD document, rebuild it, validate it, and save it."""
    _require_freecad()
    root = install_module_path(root)
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, "laser_dxf"), exist_ok=True)
    os.makedirs(os.path.join(root, "export"), exist_ok=True)
    design = str(design_name).strip().title()
    if design not in {"Catamaran", "Trimaran"}:
        raise ValueError("design_name must be Catamaran or Trimaran")
    values = _default_params(design)
    doc_name = f"{design}_900x550"
    doc = App.newDocument(doc_name)
    doc.Label = f"{design} 900 x 550 | {PROJECT_SUFFIX}"
    hull_group = doc.addObject("App::DocumentObjectGroup", "HullAssembled")
    hull_group.Label = "HullAssembled | individual nominal plywood panels"
    pattern_group = doc.addObject("App::DocumentObjectGroup", "PanelPattern")
    pattern_group.Label = "PanelPattern | 1000 x 600 mm nesting sheets"
    reference_group = doc.addObject("App::DocumentObjectGroup", "Reference")
    reference_group.Label = "Reference | axes, waterline, and station markers"
    sheet = _create_spreadsheet(doc, design, values)
    controller = _create_controller(doc, design, root, sheet, hull_group, pattern_group, reference_group)
    specs, station_positions = build_panel_specs(design, values)
    panel_objects: Dict[str, Any] = {}
    for spec in specs:
        panel_objects[spec["id"]] = _add_panel_object(doc, hull_group, spec, controller)
    pattern_objects, boundaries = _add_pattern_objects(doc, pattern_group, specs, panel_objects, controller)
    reference_objects = _create_reference_objects(doc, reference_group, controller)
    doc.recompute()
    # Explicitly rebuild once after expression evaluation; this also makes the
    # initial result independent of FreeCAD's feature execution order.
    _rebuild_document(controller)
    checks = validate_document(doc)
    fcstd_path = os.path.join(root, f"{doc_name}.FCStd")
    doc.recompute()
    doc.saveAs(fcstd_path)
    manifest = export_manifest(doc, root)
    return {
        "design": design,
        "document_name": doc.Name,
        "fcstd_path": fcstd_path,
        "manifest": manifest,
        "panel_count": checks["panel_count"],
        "sheet_count": checks["sheet_count"],
        "valid_solids": checks["valid_solids"],
        "checks": {
            "groups": ["HullAssembled", "PanelPattern", "Reference"],
            "station_counts": checks["station_counts"],
            "cross_hull_collisions": checks["cross_hull_collisions"],
            "envelope_mm": checks["envelope_mm"],
            "derived_chine_rise_mm": checks["derived_chine_rise_mm"],
            "rebuild_signature": str(controller.RebuildSignature),
        },
    }


__all__ = [
    "SCHEMA",
    "HullModelProxy",
    "build_design",
    "build_panel_specs",
    "export_manifest",
    "install_module_path",
    "validate_document",
]
