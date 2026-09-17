#!/usr/bin/env python3
"""Export flattened hull panels to deterministic DXF, PDF, CSV, and layout JSON.

The manifest is intentionally the only geometry input.  This module does not
connect to FreeCAD and does not invent panels when the manifest is missing or
invalid.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


SHEET_WIDTH_MM = 1000.0
SHEET_HEIGHT_MM = 600.0
SAFE_LEFT_MM = 20.0
SAFE_RIGHT_MM = 20.0
SAFE_BOTTOM_MM = 45.0
SAFE_TOP_MM = 50.0
PACK_GAP_MM = 4.0
MAX_SHEETS = 6
KERF_OUTSIDE_MM = 0.1
PLYWOOD_THICKNESS_MM = 20.0
EPS = 1e-7
VERIFY_TOLERANCE_MM = 1e-5


class ExportError(RuntimeError):
    """Raised when the manifest or deterministic export cannot be completed."""


@dataclass(frozen=True)
class Panel:
    design: str
    panel_id: str
    quantity: int
    thickness_mm: float
    outline: tuple[tuple[float, float], ...]
    holes: tuple[tuple[tuple[float, float], ...], ...]
    bevels: tuple[dict[str, Any], ...]
    area_mm2: float
    notes: tuple[str, ...]
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class Placement:
    panel: Panel
    x_mm: float
    y_mm: float
    rotation_deg: int
    width_mm: float
    height_mm: float
    outline: tuple[tuple[float, float], ...]
    holes: tuple[tuple[tuple[float, float], ...], ...]


@dataclass(frozen=True)
class Sheet:
    design: str
    number: int
    placements: tuple[Placement, ...]


@dataclass(frozen=True)
class DesignExport:
    name: str
    panels: tuple[Panel, ...]
    sheets: tuple[Sheet, ...]


# ---------------------------------------------------------------------------
# Manifest and polygon validation


def _fail(message: str) -> None:
    raise ExportError(message)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        _fail(f"{field} must be a finite number")
    return result


def _clean_polygon(value: Any, field: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list):
        _fail(f"{field} must be a list of [x, y] points")
    points: list[tuple[float, float]] = []
    for index, point in enumerate(value):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            _fail(f"{field}[{index}] must be [x, y]")
        x = _number(point[0], f"{field}[{index}][0]")
        y = _number(point[1], f"{field}[{index}][1]")
        if points and abs(points[-1][0] - x) <= EPS and abs(points[-1][1] - y) <= EPS:
            continue
        points.append((x, y))
    if len(points) > 1 and abs(points[0][0] - points[-1][0]) <= EPS and abs(points[0][1] - points[-1][1]) <= EPS:
        points.pop()
    if len(points) < 3:
        _fail(f"{field} must contain at least three distinct points; dummy profiles are not allowed")
    if abs(_signed_area(points)) <= EPS:
        _fail(f"{field} has zero area")
    _assert_simple_polygon(points, field)
    return tuple(points)


def _signed_area(points: Sequence[tuple[float, float]]) -> float:
    return 0.5 * sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> bool:
    return (
        min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS
        and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS
        and abs(_orientation(a, b, p)) <= EPS
    )


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    if ((ab_c > EPS and ab_d < -EPS) or (ab_c < -EPS and ab_d > EPS)) and (
        (cd_a > EPS and cd_b < -EPS) or (cd_a < -EPS and cd_b > EPS)
    ):
        return True
    return (
        abs(ab_c) <= EPS and _on_segment(a, b, c)
        or abs(ab_d) <= EPS and _on_segment(a, b, d)
        or abs(cd_a) <= EPS and _on_segment(c, d, a)
        or abs(cd_b) <= EPS and _on_segment(c, d, b)
    )


def _assert_simple_polygon(points: Sequence[tuple[float, float]], field: str) -> None:
    count = len(points)
    for first in range(count):
        first_next = (first + 1) % count
        for second in range(first + 1, count):
            second_next = (second + 1) % count
            if first == second or first_next == second or second_next == first:
                continue
            if first == 0 and second_next == 0:
                continue
            if _segments_intersect(points[first], points[first_next], points[second], points[second_next]):
                _fail(f"{field} self-intersects near edges {first} and {second}")


def _point_in_polygon(point: tuple[float, float], polygon: Sequence[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _on_segment(start, end, point):
            return True
        if (start[1] > y) != (end[1] > y):
            crossing_x = (end[0] - start[0]) * (y - start[1]) / (end[1] - start[1]) + start[0]
            if x < crossing_x:
                inside = not inside
    return inside


def _bbox(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _validate_hole(hole: Sequence[tuple[float, float]], outer: Sequence[tuple[float, float]], field: str) -> None:
    if not _point_in_polygon(hole[0], outer):
        _fail(f"{field} is outside its panel outline")
    for index, start in enumerate(hole):
        end = hole[(index + 1) % len(hole)]
        for outer_index, outer_start in enumerate(outer):
            outer_end = outer[(outer_index + 1) % len(outer)]
            if _segments_intersect(start, end, outer_start, outer_end):
                _fail(f"{field} intersects its panel outline")


def _parse_panel(raw: Any, design: str, index: int, seen_ids: set[str]) -> Panel:
    if not isinstance(raw, dict):
        _fail(f"{design}.panels[{index}] must be an object")
    panel_id = raw.get("id")
    if not isinstance(panel_id, str) or not panel_id.strip():
        _fail(f"{design}.panels[{index}].id must be a non-empty string")
    panel_id = panel_id.strip()
    if panel_id in seen_ids:
        _fail(f"duplicate panel id {panel_id!r}; mirrored instances must have unique IDs")
    seen_ids.add(panel_id)
    quantity = raw.get("quantity")
    if quantity != 1:
        _fail(f"{design}.{panel_id}: quantity must be exactly 1")
    thickness = _number(raw.get("thickness_mm"), f"{design}.{panel_id}.thickness_mm")
    if abs(thickness - PLYWOOD_THICKNESS_MM) > EPS:
        _fail(f"{design}.{panel_id}: plywood thickness must remain 20 mm, got {thickness:g}")
    outline = _clean_polygon(raw.get("outline"), f"{design}.{panel_id}.outline")
    raw_holes = raw.get("holes", [])
    if not isinstance(raw_holes, list):
        _fail(f"{design}.{panel_id}.holes must be a list")
    holes: list[tuple[tuple[float, float], ...]] = []
    for hole_index, raw_hole in enumerate(raw_holes):
        hole = _clean_polygon(raw_hole, f"{design}.{panel_id}.holes[{hole_index}]")
        _validate_hole(hole, outline, f"{design}.{panel_id}.holes[{hole_index}]")
        holes.append(hole)
    raw_bevels = raw.get("bevels", [])
    if not isinstance(raw_bevels, list):
        _fail(f"{design}.{panel_id}.bevels must be a list")
    bevels: list[dict[str, Any]] = []
    for bevel_index, bevel in enumerate(raw_bevels):
        if not isinstance(bevel, dict):
            _fail(f"{design}.{panel_id}.bevels[{bevel_index}] must be an object")
        edge = bevel.get("edge")
        if isinstance(edge, bool) or not isinstance(edge, int) or edge < 0 or edge >= len(outline):
            _fail(f"{design}.{panel_id}.bevels[{bevel_index}].edge is outside outline edge range")
        description = bevel.get("description", "")
        if not isinstance(description, str):
            _fail(f"{design}.{panel_id}.bevels[{bevel_index}].description must be text")
        bevels.append({"edge": edge, "description": description})
    area = _number(raw.get("area_mm2"), f"{design}.{panel_id}.area_mm2")
    if area <= 0:
        _fail(f"{design}.{panel_id}.area_mm2 must be positive")
    raw_notes = raw.get("notes", [])
    if not isinstance(raw_notes, list) or not all(isinstance(note, str) for note in raw_notes):
        _fail(f"{design}.{panel_id}.notes must be a list of strings")
    return Panel(
        design=design,
        panel_id=panel_id,
        quantity=1,
        thickness_mm=thickness,
        outline=outline,
        holes=tuple(holes),
        bevels=tuple(bevels),
        area_mm2=area,
        notes=tuple(raw_notes),
        bbox=_bbox(outline),
    )


def load_manifest(path: str | Path) -> tuple[Panel, ...]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found: {manifest_path}. Expected export/panels.json; no dummy profiles are generated."
        )
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExportError(f"Invalid JSON manifest {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != 1 or raw.get("units") != "mm":
        _fail("Manifest must have schema=1 and units='mm'")
    designs = raw.get("designs")
    if not isinstance(designs, list) or not designs:
        _fail("Manifest designs must be a non-empty list")
    result: list[Panel] = []
    seen_ids: set[str] = set()
    seen_designs: set[str] = set()
    for design_index, design_raw in enumerate(designs):
        if not isinstance(design_raw, dict):
            _fail(f"designs[{design_index}] must be an object")
        name = design_raw.get("name")
        if not isinstance(name, str) or not name.strip():
            _fail(f"designs[{design_index}].name must be a non-empty string")
        name = name.strip()
        if name in seen_designs:
            _fail(f"duplicate design name {name!r}")
        seen_designs.add(name)
        seen_ids.clear()
        panel_raw = design_raw.get("panels")
        if not isinstance(panel_raw, list) or not panel_raw:
            _fail(f"{name}.panels must be a non-empty list")
        for panel_index, raw_panel in enumerate(panel_raw):
            result.append(_parse_panel(raw_panel, name, panel_index, seen_ids))
    return tuple(result)


# ---------------------------------------------------------------------------
# Deterministic rectangular shelf/bottom-left packing


def _safe_area() -> tuple[float, float, float, float]:
    return (
        SAFE_LEFT_MM,
        SAFE_BOTTOM_MM,
        SHEET_WIDTH_MM - SAFE_LEFT_MM - SAFE_RIGHT_MM,
        SHEET_HEIGHT_MM - SAFE_BOTTOM_MM - SAFE_TOP_MM,
    )


def _transform_point(
    point: tuple[float, float], source_bbox: tuple[float, float, float, float], rotation_deg: int
) -> tuple[float, float]:
    min_x, min_y, width, _height = source_bbox
    u = point[0] - min_x
    v = point[1] - min_y
    if rotation_deg == 0:
        return u, v
    if rotation_deg == 90:
        return v, width - u
    raise ValueError(f"unsupported rotation {rotation_deg}")


def _placed_polygon(
    polygon: Sequence[tuple[float, float]],
    source_bbox: tuple[float, float, float, float],
    rotation_deg: int,
    x_mm: float,
    y_mm: float,
) -> tuple[tuple[float, float], ...]:
    return tuple(
        (
            round(local[0] + x_mm, 9),
            round(local[1] + y_mm, 9),
        )
        for point in polygon
        for local in (_transform_point(point, source_bbox, rotation_deg),)
    )


def _rect_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + PACK_GAP_MM <= bx + EPS
        or bx + bw + PACK_GAP_MM <= ax + EPS
        or ay + ah + PACK_GAP_MM <= by + EPS
        or by + bh + PACK_GAP_MM <= ay + EPS
    )


def _candidate_points(placed: Sequence[Placement]) -> tuple[tuple[float, float], ...]:
    left, bottom, _width, _height = _safe_area()
    x_edges = {left}
    y_edges = {bottom}
    for item in placed:
        x_edges.add(round(item.x_mm + item.width_mm + PACK_GAP_MM, 9))
        x_edges.add(round(item.x_mm, 9))
        y_edges.add(round(item.y_mm + item.height_mm + PACK_GAP_MM, 9))
        y_edges.add(round(item.y_mm, 9))
    points = {(round(x, 9), round(y, 9)) for x in x_edges for y in y_edges}
    return tuple(sorted(points, key=lambda point: (point[1], point[0])))


def _try_place(panel: Panel, placed: Sequence[Placement]) -> Placement | None:
    left, bottom, safe_width, safe_height = _safe_area()
    _min_x, _min_y, source_width, source_height = panel.bbox
    orientations = ((0, source_width, source_height), (90, source_height, source_width))
    candidates: list[Placement] = []
    for x_mm, y_mm in _candidate_points(placed):
        for rotation_deg, width_mm, height_mm in orientations:
            if x_mm < left - EPS or y_mm < bottom - EPS:
                continue
            if x_mm + width_mm > left + safe_width + EPS or y_mm + height_mm > bottom + safe_height + EPS:
                continue
            rectangle = (x_mm, y_mm, width_mm, height_mm)
            if any(_rect_overlap(rectangle, (other.x_mm, other.y_mm, other.width_mm, other.height_mm)) for other in placed):
                continue
            candidates.append(
                Placement(
                    panel=panel,
                    x_mm=round(x_mm, 9),
                    y_mm=round(y_mm, 9),
                    rotation_deg=rotation_deg,
                    width_mm=round(width_mm, 9),
                    height_mm=round(height_mm, 9),
                    outline=_placed_polygon(panel.outline, panel.bbox, rotation_deg, x_mm, y_mm),
                    holes=tuple(
                        _placed_polygon(hole, panel.bbox, rotation_deg, x_mm, y_mm) for hole in panel.holes
                    ),
                )
            )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            item.y_mm,
            item.x_mm,
            item.rotation_deg,
            item.width_mm * item.height_mm,
        ),
    )


def pack_design(design: str, panels: Sequence[Panel]) -> tuple[Sheet, ...]:
    ordered = sorted(
        panels,
        key=lambda panel: (
            -(panel.bbox[2] * panel.bbox[3]),
            -max(panel.bbox[2], panel.bbox[3]),
            panel.panel_id,
        ),
    )
    pages: list[list[Placement]] = []
    for panel in ordered:
        safe_width, safe_height = _safe_area()[2:4]
        panel_width, panel_height = panel.bbox[2:4]
        if not ((panel_width <= safe_width + EPS and panel_height <= safe_height + EPS) or (panel_height <= safe_width + EPS and panel_width <= safe_height + EPS)):
            _fail(
                f"{design}: panel {panel.panel_id} is larger than the 1000x600 safe nesting area in both orientations"
            )
        placed = None
        for page in pages:
            placed = _try_place(panel, page)
            if placed is not None:
                page.append(placed)
                break
        if placed is None:
            page: list[Placement] = []
            placed = _try_place(panel, page)
            if placed is None:
                _fail(f"{design}: panel {panel.panel_id} cannot fit on a 1000x600 sheet")
            page.append(placed)
            pages.append(page)
        if len(pages) > MAX_SHEETS:
            _fail(
                f"{design}: deterministic nesting requires {len(pages)} sheets, exceeding the limit of {MAX_SHEETS}; "
                "export stopped without truncating or arbitrarily splitting panels"
            )
    return tuple(
        Sheet(design=design, number=index + 1, placements=tuple(page)) for index, page in enumerate(pages)
    )


def _design_order(panels: Sequence[Panel]) -> list[str]:
    names = sorted({panel.design for panel in panels})
    preferred = [name for name in ("Catamaran", "Trimaran") if name in names]
    return preferred + [name for name in names if name not in preferred]


def build_exports(panels: Sequence[Panel]) -> tuple[DesignExport, ...]:
    exports: list[DesignExport] = []
    for name in _design_order(panels):
        design_panels = tuple(panel for panel in panels if panel.design == name)
        exports.append(DesignExport(name=name, panels=design_panels, sheets=pack_design(name, design_panels)))
    return tuple(exports)


# ---------------------------------------------------------------------------
# Shared layout metadata


def _round_polygon(polygon: Iterable[tuple[float, float]]) -> list[list[float]]:
    return [[round(x, 9), round(y, 9)] for x, y in polygon]


def _bevel_notes(panel: Panel) -> str:
    if not panel.bevels:
        return "none specified"
    return " | ".join(
        f"edge {bevel['edge']}: {bevel['description']}" if bevel["description"] else f"edge {bevel['edge']}"
        for bevel in panel.bevels
    )


def _layout_panel(placement: Placement) -> dict[str, Any]:
    panel = placement.panel
    return {
        "id": panel.panel_id,
        "quantity": panel.quantity,
        "thickness_mm": panel.thickness_mm,
        "source_bbox_mm": [round(value, 9) for value in panel.bbox],
        "source_outline_mm": _round_polygon(panel.outline),
        "source_holes_mm": [_round_polygon(hole) for hole in panel.holes],
        "x_mm": placement.x_mm,
        "y_mm": placement.y_mm,
        "rotation_deg": placement.rotation_deg,
        "bbox_mm": [placement.x_mm, placement.y_mm, placement.width_mm, placement.height_mm],
        "outline_mm": _round_polygon(placement.outline),
        "holes_mm": [_round_polygon(hole) for hole in placement.holes],
        "bevels": list(panel.bevels),
        "bevel_notes": _bevel_notes(panel),
        "area_mm2": panel.area_mm2,
        "notes": list(panel.notes),
        "label": f"{panel.panel_id} R{placement.rotation_deg}",
    }


def build_layout(exports: Sequence[DesignExport]) -> dict[str, Any]:
    left, bottom, width, height = _safe_area()
    return {
        "schema": 1,
        "units": "mm",
        "sheet_width_mm": SHEET_WIDTH_MM,
        "sheet_height_mm": SHEET_HEIGHT_MM,
        "safe_area_mm": {
            "x_mm": left,
            "y_mm": bottom,
            "width_mm": width,
            "height_mm": height,
        },
        "packing": {
            "algorithm": "deterministic bottom-left shelf candidates",
            "sort": "largest bounding-box area first, then longest side, then panel id",
            "rotations_deg": [0, 90],
            "gap_mm": PACK_GAP_MM,
        },
        "cut": {
            "finished_profile": "CUT layer is nominal plywood profile; no geometric offset is emitted",
            "toolpath_outside_offset_mm": KERF_OUTSIDE_MM,
            "toolpath_note": "Apply CAM outside offset +0.10 mm; do not cut both nominal and toolpath geometry",
            "hole_offset": "No automatic hole compensation emitted; CAM must apply inner compensation if required",
        },
        "designs": [
            {
                "name": export.name,
                "panel_count": len(export.panels),
                "sheet_count": len(export.sheets),
                "sheets": [
                    {
                        "sheet_id": f"{_safe_stem(export.name)}_sheet{sheet.number}",
                        "number": sheet.number,
                        "width_mm": SHEET_WIDTH_MM,
                        "height_mm": SHEET_HEIGHT_MM,
                        "panels": [_layout_panel(placement) for placement in sheet.placements],
                    }
                    for sheet in export.sheets
                ],
            }
            for export in exports
        ],
    }


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return stem or "design"


# ---------------------------------------------------------------------------
# DXF (ASCII R14 LWPOLYLINE; coordinates are millimetres)


def _dxf_number(value: float) -> str:
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def _dxf_text(layer: str, text: str, x_mm: float, y_mm: float, height_mm: float = 5.0) -> list[str]:
    clean = text.replace("\r", " ").replace("\n", " ")
    clean = clean.encode("ascii", "replace").decode("ascii")
    return [
        "0",
        "TEXT",
        "8",
        layer,
        "10",
        _dxf_number(x_mm),
        "20",
        _dxf_number(y_mm),
        "40",
        _dxf_number(height_mm),
        "1",
        clean,
        "50",
        "0",
    ]


def _dxf_polyline(layer: str, polygon: Sequence[tuple[float, float]]) -> list[str]:
    lines = ["0", "LWPOLYLINE", "8", layer, "90", str(len(polygon)), "70", "1", "43", "0.0"]
    for x_mm, y_mm in polygon:
        lines.extend(["10", _dxf_number(x_mm), "20", _dxf_number(y_mm)])
    return lines


def _write_dxf_sheet(path: Path, sheet: Sheet) -> None:
    entities: list[str] = []
    entities.extend(_dxf_text("INFO", f"{sheet.design} | SHEET {sheet.number} | 1000 x 600 mm | SCALE 1:1", 20, 590, 6))
    entities.extend(_dxf_text("TOOLPATH", "TOOLPATH: CAM OUTSIDE OFFSET +0.10 mm | DO NOT CUT BOTH", 20, 583, 4))
    entities.extend(_dxf_text("TOOLPATH", "CUT layer is nominal finished plywood profile; no toolpath geometry emitted", 20, 577, 3.5))
    entities.extend(_dxf_text("INFO", "HOLES: nominal CUT; apply inner compensation in CAM if required", 20, 571, 3.5))
    for placement in sheet.placements:
        panel = placement.panel
        for polygon in (placement.outline, *placement.holes):
            entities.extend(_dxf_polyline("CUT", polygon))
        label_y = min(placement.y_mm + placement.height_mm - 3, placement.y_mm + max(placement.height_mm / 2, 3))
        entities.extend(
            _dxf_text(
                "INFO",
                f"{panel.panel_id} | {placement.width_mm:.1f}x{placement.height_mm:.1f} mm | R{placement.rotation_deg}",
                placement.x_mm + 2,
                label_y,
                4,
            )
        )
        if panel.bevels:
            entities.extend(_dxf_text("INFO", f"BEVEL {panel.panel_id}: {_bevel_notes(panel)}", placement.x_mm + 2, placement.y_mm + 2, 2.5))
    entities.extend(_dxf_text("INFO", "20 mm plywood, profiles before fiberglass/resin/putty; bevel sanding required", 20, 8, 3.5))
    entities.extend(_dxf_text("INFO", "Geometry study only; flotation and performance are not validated", 20, 14, 3.5))
    header = [
        "0",
        "SECTION",
        "2",
        "HEADER",
        "9",
        "$ACADVER",
        "1",
        "AC1015",
        "9",
        "$INSUNITS",
        "70",
        "4",
        "9",
        "$MEASUREMENT",
        "70",
        "1",
        "0",
        "ENDSEC",
        "0",
        "SECTION",
        "2",
        "ENTITIES",
    ]
    footer = ["0", "ENDSEC", "0", "EOF", ""]
    path.write_text("\n".join(header + entities + footer), encoding="ascii", newline="\n")


# ---------------------------------------------------------------------------
# Minimal deterministic PDF writer (1 PDF page = 1000 x 600 mm at 1:1)


def _pdf_number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def _pdf_text(value: str) -> str:
    clean = value.replace("\r", " ").replace("\n", " ")
    clean = clean.encode("ascii", "replace").decode("ascii")
    return "(" + clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def _pdf_xy(x_mm: float, y_mm: float) -> tuple[float, float]:
    scale = 72.0 / 25.4
    return x_mm * scale, (SHEET_HEIGHT_MM - y_mm) * scale


def _pdf_path(polygon: Sequence[tuple[float, float]]) -> str:
    first_x, first_y = _pdf_xy(*polygon[0])
    commands = [f"{_pdf_number(first_x)} {_pdf_number(first_y)} m"]
    for point in polygon[1:]:
        x, y = _pdf_xy(*point)
        commands.append(f"{_pdf_number(x)} {_pdf_number(y)} l")
    commands.append("h S")
    return " ".join(commands)


def _pdf_line(x1: float, y1: float, x2: float, y2: float) -> str:
    ax, ay = _pdf_xy(x1, y1)
    bx, by = _pdf_xy(x2, y2)
    return f"{_pdf_number(ax)} {_pdf_number(ay)} m {_pdf_number(bx)} {_pdf_number(by)} l S"


def _pdf_text_at(text: str, x_mm: float, y_mm: float, font_pt: float = 8.0, gray: float = 0.0) -> str:
    x, y = _pdf_xy(x_mm, y_mm)
    return f"{gray:.3f} g BT /F1 {_pdf_number(font_pt)} Tf 1 0 0 1 {_pdf_number(x)} {_pdf_number(y)} Tm {_pdf_text(text)} Tj ET 0 g"


def _pdf_page_content(sheet: Sheet) -> bytes:
    commands = ["q", "0.35 w", "0 g"]
    commands.append(_pdf_line(0, 0, SHEET_WIDTH_MM, 0))
    commands.append(_pdf_line(SHEET_WIDTH_MM, 0, SHEET_WIDTH_MM, SHEET_HEIGHT_MM))
    commands.append(_pdf_line(SHEET_WIDTH_MM, SHEET_HEIGHT_MM, 0, SHEET_HEIGHT_MM))
    commands.append(_pdf_line(0, SHEET_HEIGHT_MM, 0, 0))
    commands.append(_pdf_text_at(f"{sheet.design} | SHEET {sheet.number} | 1000 x 600 mm | SCALE 1:1", 20, 592, 10))
    commands.append(_pdf_text_at("CUT = nominal finished plywood profile. CAM: outside offset +0.10 mm. DO NOT CUT BOTH.", 20, 584, 7))
    commands.append(_pdf_text_at("HOLES remain nominal; apply inner compensation in CAM if required (none emitted here).", 20, 577, 7))
    commands.append(_pdf_text_at("Profiles are before fiberglass/resin/putty; bevel sanding required; flotation/performance not validated.", 20, 570, 7))
    # Safe nesting rectangle is a guide only, never a CUT entity.
    commands.extend(["0.70 g", "0.25 w"])
    commands.append(_pdf_line(SAFE_LEFT_MM, SAFE_BOTTOM_MM, SAFE_LEFT_MM + (SHEET_WIDTH_MM - SAFE_LEFT_MM - SAFE_RIGHT_MM), SAFE_BOTTOM_MM))
    commands.append(_pdf_line(SAFE_LEFT_MM + (SHEET_WIDTH_MM - SAFE_LEFT_MM - SAFE_RIGHT_MM), SAFE_BOTTOM_MM, SAFE_LEFT_MM + (SHEET_WIDTH_MM - SAFE_LEFT_MM - SAFE_RIGHT_MM), SAFE_BOTTOM_MM + (SHEET_HEIGHT_MM - SAFE_BOTTOM_MM - SAFE_TOP_MM)))
    commands.append(_pdf_line(SAFE_LEFT_MM + (SHEET_WIDTH_MM - SAFE_LEFT_MM - SAFE_RIGHT_MM), SAFE_BOTTOM_MM + (SHEET_HEIGHT_MM - SAFE_BOTTOM_MM - SAFE_TOP_MM), SAFE_LEFT_MM, SAFE_BOTTOM_MM + (SHEET_HEIGHT_MM - SAFE_BOTTOM_MM - SAFE_TOP_MM)))
    commands.append(_pdf_line(SAFE_LEFT_MM, SAFE_BOTTOM_MM + (SHEET_HEIGHT_MM - SAFE_BOTTOM_MM - SAFE_TOP_MM), SAFE_LEFT_MM, SAFE_BOTTOM_MM))
    commands.extend(["0 g", "0.35 w"])
    for placement in sheet.placements:
        commands.append(_pdf_path(placement.outline))
        for hole in placement.holes:
            commands.append(_pdf_path(hole))
        label = f"{placement.panel.panel_id} | {placement.width_mm:.1f} x {placement.height_mm:.1f} mm | R{placement.rotation_deg}"
        commands.append(_pdf_text_at(label, placement.x_mm + 2, placement.y_mm + max(placement.height_mm - 4, 4), 7))
        if placement.panel.bevels:
            commands.append(_pdf_text_at(f"BEVEL: {_bevel_notes(placement.panel)}", placement.x_mm + 2, placement.y_mm + 3, 5, 0.25))
    # A physical 100 mm ruler remains in the title margin.
    commands.append(_pdf_line(20, 15, 120, 15))
    for tick in range(0, 101, 10):
        tick_height = 5 if tick % 50 == 0 else 3
        commands.append(_pdf_line(20 + tick, 15, 20 + tick, 15 + tick_height))
    commands.append(_pdf_text_at("0", 19, 10, 6))
    commands.append(_pdf_text_at("50", 68, 10, 6))
    commands.append(_pdf_text_at("100 mm", 113, 10, 6))
    commands.append(_pdf_text_at("20 mm plywood | nominal profiles | bevel notes in CSV/DXF/PDF", 150, 15, 6, 0.25))
    commands.append("Q")
    return ("\n".join(commands) + "\n").encode("ascii")


class _PdfDocument:
    def __init__(self, page_contents: Sequence[bytes]) -> None:
        self.objects: list[bytes | None] = [None]
        self.pages_id = self._reserve()
        self.font_id = self._add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        content_ids = [self._add(content) for content in page_contents]
        page_ids: list[int] = []
        width_pt = SHEET_WIDTH_MM * 72.0 / 25.4
        height_pt = SHEET_HEIGHT_MM * 72.0 / 25.4
        for content_id in content_ids:
            page_ids.append(
                self._add(
                    (
                        f"<< /Type /Page /Parent {self.pages_id} 0 R /MediaBox [0 0 {_pdf_number(width_pt)} {_pdf_number(height_pt)}] "
                        f"/Resources << /Font << /F1 {self.font_id} 0 R >> >> /Contents {content_id} 0 R >>"
                    ).encode("ascii")
                )
            )
        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        self.objects[self.pages_id] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
        self.catalog_id = self._add(f"<< /Type /Catalog /Pages {self.pages_id} 0 R >>".encode("ascii"))

    def _reserve(self) -> int:
        self.objects.append(None)
        return len(self.objects) - 1

    def _add(self, value: bytes) -> int:
        if value.startswith(b"q\n") or b"\n" in value[:4]:
            value = b"<< /Length " + str(len(value)).encode("ascii") + b" >>\nstream\n" + value + b"endstream"
        self.objects.append(value)
        return len(self.objects) - 1

    def bytes(self) -> bytes:
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for object_id, value in enumerate(self.objects[1:], start=1):
            if value is None:
                raise ExportError(f"PDF object {object_id} was not initialized")
            offsets.append(len(output))
            output.extend(f"{object_id} 0 obj\n".encode("ascii"))
            output.extend(value)
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {len(self.objects)}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                f"trailer\n<< /Size {len(self.objects)} /Root {self.catalog_id} 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(output)


def _write_pdf(path: Path, design: DesignExport) -> None:
    contents = [_pdf_page_content(sheet) for sheet in design.sheets]
    path.write_bytes(_PdfDocument(contents).bytes())


# ---------------------------------------------------------------------------
# CSV and JSON output


def _write_layout(path: Path, layout: dict[str, Any]) -> None:
    path.write_text(json.dumps(layout, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, exports: Sequence[DesignExport]) -> None:
    fields = [
        "design",
        "sheet_id",
        "sheet_number",
        "panel_id",
        "quantity",
        "thickness_mm",
        "rotation_deg",
        "x_mm",
        "y_mm",
        "bbox_width_mm",
        "bbox_height_mm",
        "area_mm2",
        "hole_count",
        "bevel_notes",
        "notes",
        "cut_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for design in exports:
            for sheet in design.sheets:
                sheet_id = f"{_safe_stem(design.name)}_sheet{sheet.number}"
                for placement in sheet.placements:
                    panel = placement.panel
                    writer.writerow(
                        {
                            "design": design.name,
                            "sheet_id": sheet_id,
                            "sheet_number": sheet.number,
                            "panel_id": panel.panel_id,
                            "quantity": panel.quantity,
                            "thickness_mm": f"{panel.thickness_mm:.9g}",
                            "rotation_deg": placement.rotation_deg,
                            "x_mm": f"{placement.x_mm:.9g}",
                            "y_mm": f"{placement.y_mm:.9g}",
                            "bbox_width_mm": f"{placement.width_mm:.9g}",
                            "bbox_height_mm": f"{placement.height_mm:.9g}",
                            "area_mm2": f"{panel.area_mm2:.9g}",
                            "hole_count": len(panel.holes),
                            "bevel_notes": _bevel_notes(panel),
                            "notes": " | ".join(panel.notes),
                            "cut_note": "CUT nominal; CAM outside offset +0.10 mm; do not cut both; holes require inner CAM compensation if needed",
                        }
                    )


def export_all(manifest_path: str | Path, project_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parent
    panels = load_manifest(manifest_path)
    exports = build_exports(panels)
    layout = build_layout(exports)
    laser_dir = root / "laser_dxf"
    export_dir = root / "export"
    laser_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    for design in exports:
        for sheet in design.sheets:
            _write_dxf_sheet(laser_dir / f"{_safe_stem(design.name)}_sheet{sheet.number}.dxf", sheet)
        _write_pdf(export_dir / f"{_safe_stem(design.name)}_panels.pdf", design)
    _write_csv(export_dir / "panel_cut_list.csv", exports)
    _write_layout(export_dir / "panel_layout.json", layout)
    return {
        "manifest": str(Path(manifest_path)),
        "project_root": str(root),
        "designs": {
            design.name: {"panel_count": len(design.panels), "sheet_count": len(design.sheets)} for design in exports
        },
        "dxf_dir": str(laser_dir),
        "pdf_dir": str(export_dir),
        "layout": str(export_dir / "panel_layout.json"),
        "cut_list": str(export_dir / "panel_cut_list.csv"),
    }


# ---------------------------------------------------------------------------
# Reopening/parser verification for the FreeCAD owner


def _parse_dxf_entities(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except FileNotFoundError as exc:
        raise ExportError(f"DXF missing: {path}") from exc
    if len(lines) % 2:
        raise ExportError(f"DXF has an odd number of group-code lines: {path}")
    pairs = [(lines[index].strip(), lines[index + 1].strip()) for index in range(0, len(lines), 2)]
    polylines: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    index = 0
    while index < len(pairs):
        code, value = pairs[index]
        if code != "0":
            index += 1
            continue
        if value == "LWPOLYLINE":
            entity: dict[str, Any] = {"layer": "", "closed": False, "points": []}
            index += 1
            current_x: float | None = None
            while index < len(pairs) and pairs[index][0] != "0":
                group, item = pairs[index]
                if group == "8":
                    entity["layer"] = item
                elif group == "70":
                    try:
                        entity["closed"] = bool(int(item) & 1)
                    except ValueError:
                        pass
                elif group == "10":
                    try:
                        current_x = float(item)
                    except ValueError as exc:
                        raise ExportError(f"DXF invalid x coordinate in {path}") from exc
                elif group == "20" and current_x is not None:
                    try:
                        entity["points"].append((current_x, float(item)))
                    except ValueError as exc:
                        raise ExportError(f"DXF invalid y coordinate in {path}") from exc
                    current_x = None
                index += 1
            polylines.append(entity)
            continue
        if value == "TEXT":
            entity = {"layer": "", "text": "", "x": 0.0, "y": 0.0}
            index += 1
            while index < len(pairs) and pairs[index][0] != "0":
                group, item = pairs[index]
                if group == "8":
                    entity["layer"] = item
                elif group == "1":
                    entity["text"] = item
                elif group == "10":
                    entity["x"] = float(item)
                elif group == "20":
                    entity["y"] = float(item)
                index += 1
            texts.append(entity)
            continue
        index += 1
    return polylines, texts


def _close_enough(a: Sequence[float], b: Sequence[float], tolerance: float = VERIFY_TOLERANCE_MM) -> bool:
    return len(a) == len(b) and all(abs(float(left) - float(right)) <= tolerance for left, right in zip(a, b))


def _assert_polygon_matches(actual: Sequence[Sequence[float]], expected: Sequence[Sequence[float]], context: str) -> None:
    if len(actual) != len(expected):
        _fail(f"{context}: vertex count mismatch ({len(actual)} != {len(expected)})")
    for index, (actual_point, expected_point) in enumerate(zip(actual, expected)):
        if not _close_enough(actual_point, expected_point):
            _fail(f"{context}: vertex {index} differs after reopen")


def _inverse_point(
    point: tuple[float, float], placement: dict[str, Any], source_bbox: Sequence[float]
) -> tuple[float, float]:
    x_mm = float(placement["x_mm"])
    y_mm = float(placement["y_mm"])
    rotation = int(placement["rotation_deg"])
    min_x, min_y, width, _height = (float(item) for item in source_bbox)
    u = point[0] - x_mm
    v = point[1] - y_mm
    if rotation == 0:
        return u + min_x, v + min_y
    if rotation == 90:
        return width - v + min_x, u + min_y
    _fail(f"{placement['id']}: unsupported layout rotation {rotation}")


def _verify_sheet(sheet_meta: dict[str, Any], dxf_path: Path, source_panels: dict[str, Panel]) -> dict[str, Any]:
    polylines, texts = _parse_dxf_entities(dxf_path)
    panels = sheet_meta.get("panels")
    if not isinstance(panels, list):
        _fail(f"{dxf_path}: layout panels missing")
    expected_polyline_count = sum(1 + len(panel.get("holes_mm", [])) for panel in panels)
    if len(polylines) != expected_polyline_count:
        _fail(f"{dxf_path}: expected {expected_polyline_count} profiles, got {len(polylines)}")
    cut_polylines = [polyline for polyline in polylines if polyline.get("layer") == "CUT"]
    if len(cut_polylines) != expected_polyline_count:
        _fail(f"{dxf_path}: all profiles must be on CUT layer")
    text_values = [str(text.get("text", "")) for text in texts]
    labels = "\n".join(text_values)
    if "TOOLPATH" not in labels or "DO NOT CUT BOTH" not in labels:
        _fail(f"{dxf_path}: toolpath warning label missing")
    actual_polyline_index = 0
    rectangles: list[tuple[float, float, float, float, str]] = []
    safe = _safe_area()
    for panel in panels:
        panel_id = panel.get("id")
        if not isinstance(panel_id, str) or not any(value.startswith(f"{panel_id} |") for value in text_values):
            _fail(f"{dxf_path}: panel label {panel_id!r} missing")
        source_panel = source_panels.get(panel_id)
        if source_panel is None:
            _fail(f"{dxf_path}: panel {panel_id!r} is not present in the manifest")
        source_bbox = panel.get("source_bbox_mm")
        if not isinstance(source_bbox, list) or len(source_bbox) != 4 or not _close_enough(source_bbox, source_panel.bbox):
            _fail(f"{dxf_path}: panel {panel_id} source bbox differs from manifest")
        bbox = panel.get("bbox_mm")
        if not isinstance(bbox, list) or len(bbox) != 4:
            _fail(f"{dxf_path}: panel {panel_id} bbox missing")
        x_mm, y_mm, width_mm, height_mm = (float(value) for value in bbox)
        if x_mm < -VERIFY_TOLERANCE_MM or y_mm < -VERIFY_TOLERANCE_MM or x_mm + width_mm > SHEET_WIDTH_MM + VERIFY_TOLERANCE_MM or y_mm + height_mm > SHEET_HEIGHT_MM + VERIFY_TOLERANCE_MM:
            _fail(f"{dxf_path}: panel {panel_id} is outside the 1000x600 sheet")
        if x_mm < safe[0] - VERIFY_TOLERANCE_MM or y_mm < safe[1] - VERIFY_TOLERANCE_MM or x_mm + width_mm > safe[0] + safe[2] + VERIFY_TOLERANCE_MM or y_mm + height_mm > safe[1] + safe[3] + VERIFY_TOLERANCE_MM:
            _fail(f"{dxf_path}: panel {panel_id} is outside the safe nesting area")
        rectangle = (x_mm, y_mm, width_mm, height_mm, panel_id)
        if any(_rect_overlap(rectangle[:4], other[:4]) for other in rectangles):
            _fail(f"{dxf_path}: panel {panel_id} overlaps another panel bbox")
        rectangles.append(rectangle)
        expected_profiles = [panel.get("outline_mm", [])] + list(panel.get("holes_mm", []))
        source_profiles = [source_panel.outline] + list(source_panel.holes)
        layout_source_profiles = [panel.get("source_outline_mm", [])] + list(panel.get("source_holes_mm", []))
        if len(layout_source_profiles) != len(source_profiles) or any(not isinstance(profile, list) for profile in layout_source_profiles):
            _fail(f"{dxf_path}: panel {panel_id} source profile list differs from manifest")
        for source_index, layout_source_profile in enumerate(layout_source_profiles):
            _assert_polygon_matches(layout_source_profile, source_profiles[source_index], f"{dxf_path}:{panel_id}:manifest-profile{source_index}")
        for profile_index, expected_profile in enumerate(expected_profiles):
            polyline = cut_polylines[actual_polyline_index]
            actual_polyline_index += 1
            if not polyline.get("closed") or len(polyline.get("points", [])) < 3:
                _fail(f"{dxf_path}: {panel_id} profile {profile_index} is not closed")
            _assert_polygon_matches(polyline["points"], expected_profile, f"{dxf_path}:{panel_id}:profile{profile_index}")
            inverse = [_inverse_point(tuple(point), panel, panel["source_bbox_mm"]) for point in polyline["points"]]
            _assert_polygon_matches(inverse, source_profiles[profile_index], f"{dxf_path}:{panel_id}:inverse-profile{profile_index}")
    return {"path": str(dxf_path), "panel_count": len(panels), "profile_count": len(polylines), "closed": True}


def _read_layout(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Layout metadata missing: {path}")
    try:
        layout = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExportError(f"Invalid layout metadata {path}: {exc}") from exc
    if not isinstance(layout, dict) or layout.get("schema") != 1 or layout.get("units") != "mm":
        _fail(f"Invalid layout metadata schema in {path}")
    return layout


def verify_exports(
    manifest_path: str | Path,
    project_root: str | Path | None = None,
    layout_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parent
    panels = load_manifest(manifest_path)
    expected = build_exports(panels)
    layout = _read_layout(Path(layout_path) if layout_path is not None else root / "export" / "panel_layout.json")
    by_name = {str(design.get("name")): design for design in layout.get("designs", []) if isinstance(design, dict)}
    reports: list[dict[str, Any]] = []
    for design in expected:
        meta = by_name.get(design.name)
        if meta is None:
            _fail(f"Layout has no design {design.name}")
        if meta.get("panel_count") != len(design.panels) or meta.get("sheet_count") != len(design.sheets):
            _fail(f"Layout count mismatch for {design.name}")
        sheets = meta.get("sheets")
        if not isinstance(sheets, list) or len(sheets) != len(design.sheets):
            _fail(f"Layout sheet list mismatch for {design.name}")
        design_reports: list[dict[str, Any]] = []
        for sheet, sheet_meta in zip(design.sheets, sheets):
            expected_id = f"{_safe_stem(design.name)}_sheet{sheet.number}"
            if sheet_meta.get("sheet_id") != expected_id:
                _fail(f"Layout sheet id mismatch for {design.name} sheet {sheet.number}")
            dxf_path = root / "laser_dxf" / f"{_safe_stem(design.name)}_sheet{sheet.number}.dxf"
            source_panels = {panel.panel_id: panel for panel in design.panels}
            design_reports.append(_verify_sheet(sheet_meta, dxf_path, source_panels))
        pdf_path = root / "export" / f"{_safe_stem(design.name)}_panels.pdf"
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            _fail(f"PDF missing or empty: {pdf_path}")
        reports.append({"name": design.name, "sheets": design_reports, "pdf": str(pdf_path)})
    csv_path = root / "export" / "panel_cut_list.csv"
    csv_rows: list[dict[str, str]]
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        _fail(f"Cut-list CSV missing or empty: {csv_path}")
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            csv_rows = list(reader)
    except (OSError, csv.Error) as exc:
        _fail(f"Cut-list CSV cannot be reopened: {csv_path}: {exc}")
    expected_rows = {
        (design.name, f"{_safe_stem(design.name)}_sheet{sheet.number}", placement.panel.panel_id)
        for design in expected
        for sheet in design.sheets
        for placement in sheet.placements
    }
    actual_rows = {(row.get("design", ""), row.get("sheet_id", ""), row.get("panel_id", "")) for row in csv_rows}
    if actual_rows != expected_rows:
        _fail(f"Cut-list CSV rows do not match layout ({len(actual_rows)} actual keys, {len(expected_rows)} expected)")
    if any("bevel_notes" not in row for row in csv_rows):
        _fail(f"Cut-list CSV lacks bevel_notes column: {csv_path}")
    return {
        "ok": True,
        "manifest": str(Path(manifest_path)),
        "layout": str(Path(layout_path) if layout_path is not None else root / "export" / "panel_layout.json"),
        "designs": reports,
        "cut_list": str(csv_path),
    }


# ---------------------------------------------------------------------------
# CLI


def _default_manifest(root: Path) -> Path:
    return root / "export" / "panels.json"


def main(argv: Sequence[str] | None = None) -> int:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, help="manifest path; defaults to export/panels.json")
    parser.add_argument("--manifest", dest="manifest_option", type=Path, help="manifest path (optional named form)")
    parser.add_argument("--project-root", type=Path, default=root, help=argparse.SUPPRESS)
    parser.add_argument("--layout", type=Path, default=None, help="layout JSON path for --verify")
    parser.add_argument("--verify", action="store_true", help="reopen DXF and verify profiles, placement, and counts")
    args = parser.parse_args(argv)
    manifest = args.manifest_option or args.manifest
    if manifest is None:
        manifest = _default_manifest(args.project_root)
    elif not manifest.is_absolute():
        manifest = args.project_root / manifest
    try:
        result = verify_exports(manifest, args.project_root, args.layout) if args.verify else export_all(manifest, args.project_root)
    except (ExportError, FileNotFoundError, OSError) as exc:
        print(f"export_panels.py: ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
