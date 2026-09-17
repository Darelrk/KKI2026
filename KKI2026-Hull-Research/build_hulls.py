"""FreeCAD entrypoints for the KKI2026 hull study.

Run inside FreeCAD's Python console or through the FreeCAD MCP Python
execution tool.  The root argument is intentionally explicit so the same
bundled sources work after a FCStd reopen.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

DEFAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))
DESIGNS = ("Catamaran", "Trimaran")


def load_hull_module(root: str = DEFAULT_ROOT):
    root = os.path.abspath(os.fspath(root))
    if root not in sys.path:
        sys.path.insert(0, root)
    import hull_model

    hull_model.install_module_path(root)
    return hull_model


def build_design(name: str, root: str = DEFAULT_ROOT) -> Dict[str, Any]:
    """Build one named design and return its result structure."""
    model = load_hull_module(root)
    return model.build_design(name, root)


def export_manifest(doc: Any, root: str = DEFAULT_ROOT) -> Dict[str, Any]:
    """Export the shared panels.json contract for an already-built document."""
    model = load_hull_module(root)
    return model.export_manifest(doc, root)


def build_all(root: str = DEFAULT_ROOT) -> Dict[str, Any]:
    """Build Catamaran then Trimaran in deterministic order."""
    root = os.path.abspath(os.fspath(root))
    results = [build_design(name, root) for name in DESIGNS]
    return {"root": root, "designs": results}


def main(root: str = DEFAULT_ROOT) -> Dict[str, Any]:
    return build_all(root)


if __name__ == "__main__":  # pragma: no cover - intended for FreeCAD console
    print(json.dumps(main(), indent=2, sort_keys=False))
