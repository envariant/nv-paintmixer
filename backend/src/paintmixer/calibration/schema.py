"""JSON Schema for one row of the calibration CSV (values as strings, as a CSV reader yields).

The committed copy lives at ``docs/calibration_row.schema.json``; regenerate with
``uv run paintmixer schema --out ../docs/calibration_row.schema.json``. The schema captures the
per-cell syntax; cross-field rules (fractions sum to 1, known paint ids, -W/-B pairing) are
enforced by :func:`paintmixer.calibration.format.parse_calibration_csv`.
"""

from __future__ import annotations

import json
from typing import Any

from paintmixer.calibration.format import (
    OPTIONAL_COLUMNS,
    REQUIRED_SPECTRUM_COLUMNS,
    SPECTRUM_COLUMNS,
    SPREAD_COLUMNS,
    SampleType,
    Substrate,
)

NUMBER = r"^\s*(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*$"
_PAIR = r"\s*[a-z0-9][a-z0-9_.-]*\s*:\s*[0-9.eE+-]+\s*"
PAIRS = rf"^\s*$|^{_PAIR}(;{_PAIR})*;?\s*$"


def calibration_row_schema() -> dict[str, Any]:
    props: dict[str, Any] = {
        "sample_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Unique id; tint/mixture rows end in -W or -B; substrates are SUB-W / SUB-B"
            ),
        },
        "type": {"type": "string", "enum": [t.value for t in SampleType]},
        "substrate": {"type": "string", "enum": [s.value for s in Substrate]},
        "components": {
            "type": "string",
            "pattern": PAIRS,
            "description": (
                "paint_id:volume_fraction;... summing to 1 (tolerance 0.002); empty for substrates"
            ),
        },
        "components_mass_g": {
            "type": "string",
            "pattern": PAIRS,
            "description": "Optional weighed masses paint_id:grams;... (overrides components)",
        },
        "notes": {
            "type": "string",
            "description": "Semicolon-separated tokens: gap_um=<number>, holdout, free text",
        },
        "measured_at": {"type": "string"},
        "n_readings": {"type": "string", "pattern": r"^\s*\d*\s*$"},
    }
    for c in SPECTRUM_COLUMNS:
        props[c] = {"type": "string", "pattern": NUMBER, "description": "reflectance 0-1.2"}
    for c in SPREAD_COLUMNS:
        props[c] = {"type": "string", "pattern": r"^\s*$|" + NUMBER, "description": "std 0-1"}
    assert set(OPTIONAL_COLUMNS) <= set(props)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://paintmixer.local/schemas/calibration_row.schema.json",
        "title": "PaintMixer calibration CSV row",
        "type": "object",
        # r400..r700 are the minimum; r380, r390 and r710..r730 are optional (canonical grid)
        "required": [
            "sample_id",
            "type",
            "substrate",
            "components",
            "notes",
            *REQUIRED_SPECTRUM_COLUMNS,
        ],
        "properties": props,
        "additionalProperties": False,
    }


def schema_json() -> str:
    return json.dumps(calibration_row_schema(), indent=2) + "\n"
