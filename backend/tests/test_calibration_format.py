from __future__ import annotations

import csv
import io
import json

import jsonschema
import numpy as np
import pytest

from paintmixer.calibration.format import (
    SPECTRUM_COLUMNS,
    SampleType,
    Substrate,
    ValidationReport,
    parse_calibration_csv,
)
from paintmixer.calibration.schema import calibration_row_schema, schema_json
from paintmixer.colorsci.spectral import N_BANDS
from paintmixer.domain import PaintInfo
from tests.helpers import ROOT, SAMPLE_DATA

HEADER = "sample_id,type,substrate,components,notes," + ",".join(SPECTRUM_COLUMNS)


def spec(v: float = 0.5, n: int = N_BANDS) -> str:
    return ",".join([f"{v}"] * n)


def csv_text(*rows: str, header: str = HEADER) -> str:
    return "\n".join([header, *rows]) + "\n"


def codes(
    rep: ValidationReport, severity: str = "error"
) -> list[tuple[int | None, str | None, str]]:
    return [(i.row, i.column, i.code) for i in rep.issues if i.severity == severity]


GOOD = [
    f"SUB-W,substrate_white,white,,,{spec(0.86)}",
    f"SUB-B,substrate_black,black,,,{spec(0.03)}",
    f"MT-phthalo-blue-W,masstone_over_white,white,phthalo-blue:1,gap_um=150,{spec(0.1)}",
    f"TN-phthalo-blue-15-W,tint,white,phthalo-blue:0.15;titanium-white:0.85,gap_um=150,{spec()}",
    f"TN-phthalo-blue-15-B,tint,black,phthalo-blue:0.15;titanium-white:0.85,gap_um=150,{spec()}",
    f"MX-1-W,mixture,white,phthalo-blue:0.5;arylide-yellow:0.5,gap_um=100;holdout,{spec()}",
    f"MX-1-B,mixture,black,phthalo-blue:0.5;arylide-yellow:0.5,gap_um=100;holdout,{spec()}",
]


@pytest.mark.parametrize("name", ["calibration_starter5.csv", "calibration_pool9.csv"])
def test_sample_files_are_valid(name: str, paints: dict[str, PaintInfo]) -> None:
    rep = parse_calibration_csv((SAMPLE_DATA / name).read_text(), paints)
    assert rep.ok, rep.errors[:5]
    assert not rep.warnings
    assert len(rep.samples) == rep.n_rows > 100
    types = {s.type for s in rep.samples}
    assert types == set(SampleType)
    assert any(s.holdout for s in rep.samples)
    assert all(s.masses_g for s in rep.samples if s.type == SampleType.MIXTURE)


def test_good_rows(paints: dict[str, PaintInfo]) -> None:
    rep = parse_calibration_csv(csv_text(*GOOD), paints)
    assert rep.ok and not rep.warnings
    mx = [s for s in rep.samples if s.sample_id == "MX-1-W"][0]
    assert mx.holdout and mx.gap_um == 100 and mx.substrate == Substrate.WHITE
    assert mx.drawdown_id == "MX-1"
    assert mx.reflectance.shape == (N_BANDS,)
    assert rep.samples[0].components == {}
    assert rep.samples[2].effective_gap_um == 150


def test_unknown_paint_and_sum(paints: dict[str, PaintInfo]) -> None:
    rows = [
        f"MX-2-W,mixture,white,nope:0.5;arylide-yellow:0.5,,{spec()}",
        f"MX-3-W,mixture,white,phthalo-blue:0.5;arylide-yellow:0.49,,{spec()}",
        f"MX-4-W,mixture,white,phthalo-blue:0.5;arylide-yellow:0.499,,{spec()}",
    ]
    rep = parse_calibration_csv(csv_text(*rows), paints)
    assert (2, "components", "unknown_paint") in codes(rep)
    assert (3, "components", "fractions_sum") in codes(rep)
    # 0.999 is within the 0.002 tolerance
    assert not [c for c in codes(rep) if c[0] == 4]
    assert [s.sample_id for s in rep.samples] == ["MX-4-W"]


def test_spectrum_cell_errors(paints: dict[str, PaintInfo]) -> None:
    cells = [0.5] * N_BANDS
    col = SPECTRUM_COLUMNS.index
    row_missing = "MX-5-W,mixture,white,phthalo-blue:1,," + ",".join(
        "" if i == col("r430") else str(v) for i, v in enumerate(cells)
    )
    row_text = "MX-6-W,mixture,white,phthalo-blue:1,," + ",".join(
        "abc" if i == col("r700") else str(v) for i, v in enumerate(cells)
    )
    row_range = "MX-7-W,mixture,white,phthalo-blue:1,," + ",".join(
        "45.2" if i == col("r500") else str(v) for i, v in enumerate(cells)
    )
    row_neg = "MX-8-W,mixture,white,phthalo-blue:1,," + ",".join(
        "-0.01" if i == col("r400") else str(v) for i, v in enumerate(cells)
    )
    rep = parse_calibration_csv(csv_text(row_missing, row_text, row_range, row_neg), paints)
    errs = codes(rep)
    assert (2, "r430", "missing_value") in errs
    assert (3, "r700", "not_numeric") in errs
    assert (4, "r500", "out_of_range") in errs
    assert (5, "r400", "out_of_range") in errs
    pct = [i for i in rep.issues if i.row == 4][0]
    assert "percent" in pct.message
    assert rep.samples == []


def test_wrong_wavelength_headers(paints: dict[str, PaintInfo]) -> None:
    bad = HEADER.replace("r550", "r55O")
    rep = parse_calibration_csv(csv_text(f"SUB-W,substrate_white,white,,,{spec()}", header=bad))
    assert (1, "r55O", "bad_wavelength_header") in codes(rep)
    short = ",".join(HEADER.split(",")[:-4])  # drop r700 ... r730
    rep = parse_calibration_csv(
        csv_text(f"SUB-W,substrate_white,white,,,{spec(n=N_BANDS - 4)}", header=short)
    )
    err = [i for i in rep.errors if i.code == "bad_wavelength_header"][0]
    assert "r700" in err.message
    swapped = HEADER.replace("r400,r410", "r410,r400")
    rep = parse_calibration_csv(csv_text(f"SUB-W,substrate_white,white,,,{spec()}", header=swapped))
    assert any(i.code == "bad_wavelength_header" for i in rep.errors)
    uneven = HEADER.replace("r410", "r405")
    rep = parse_calibration_csv(csv_text(f"SUB-W,substrate_white,white,,,{spec()}", header=uneven))
    assert any("evenly" in i.message for i in rep.errors)
    missing = HEADER.replace("substrate,", "")
    rep = parse_calibration_csv(csv_text(f"SUB-W,substrate_white,,,{spec()}", header=missing))
    assert (1, "substrate", "missing_column") in codes(rep)


def test_colormunki_grid_is_canonical() -> None:
    wl = list(range(380, 731, 10))
    header = "sample_id,type,substrate,components,notes," + ",".join(f"r{w}" for w in wl)
    vals = ",".join(f"{(w - 380) / 1000:.3f}" for w in wl)
    rep = parse_calibration_csv(csv_text(f"SUB-W,substrate_white,white,,,{vals}", header=header))
    assert rep.ok and not rep.warnings
    np.testing.assert_allclose(rep.samples[0].reflectance, (np.arange(380, 731, 10) - 380) / 1000)


def test_400_700_file_is_extended_by_holding_edges() -> None:
    wl = list(range(400, 701, 10))
    header = "sample_id,type,substrate,components,notes," + ",".join(f"r{w}" for w in wl)
    vals = ",".join(f"{(w - 380) / 1000:.3f}" for w in wl)
    rep = parse_calibration_csv(csv_text(f"SUB-W,substrate_white,white,,,{vals}", header=header))
    assert rep.ok and [i.code for i in rep.warnings] == ["resampled"]
    assert "held at the edge" in rep.warnings[0].message
    r = rep.samples[0].reflectance
    assert r.shape == (N_BANDS,)
    np.testing.assert_allclose(r[:3], 0.02)  # 380, 390 held at the 400 nm value
    np.testing.assert_allclose(r[-4:], 0.32)  # 710-730 held at the 700 nm value


def test_5nm_grid_is_resampled() -> None:
    wl = list(range(380, 731, 5))
    header = "sample_id,type,substrate,components,notes," + ",".join(f"r{w}" for w in wl)
    vals = ",".join(f"{(w - 380) / 1000:.4f}" for w in wl)
    rep = parse_calibration_csv(csv_text(f"SUB-W,substrate_white,white,,,{vals}", header=header))
    assert rep.ok and [i.code for i in rep.warnings] == ["resampled"]
    assert "held" not in rep.warnings[0].message


def test_masses_override_components(paints: dict[str, PaintInfo]) -> None:
    header = HEADER.replace("notes,", "notes,components_mass_g,")
    # blue density 1.1, yellow 1.2 -> volumes 5/1.1 and 5/1.2
    row_ok = f"MX-9-W,mixture,white,phthalo-blue:0.52;arylide-yellow:0.48,,phthalo-blue:5;arylide-yellow:5,{spec()}"
    row_far = f"MX-10-W,mixture,white,phthalo-blue:0.3;arylide-yellow:0.7,,phthalo-blue:5;arylide-yellow:5,{spec()}"
    rep = parse_calibration_csv(csv_text(row_ok, row_far, header=header), paints)
    assert rep.ok
    s = rep.samples[0]
    v_b, v_y = 5 / 1.1, 5 / 1.2
    assert s.components["phthalo-blue"] == pytest.approx(v_b / (v_b + v_y))
    assert s.planned_components == {"phthalo-blue": 0.52, "arylide-yellow": 0.48}
    w = [(i.row, i.code) for i in rep.warnings]
    assert (3, "mass_deviation") in w
    assert (2, "mass_deviation") not in w


def test_sample_id_rules(paints: dict[str, PaintInfo]) -> None:
    rows = [
        f"MX-11-B,mixture,white,phthalo-blue:1,,{spec()}",
        f"MX-12-W,mixture,white,phthalo-blue:1,,{spec()}",
        f"MX-12-W,mixture,white,phthalo-blue:1,,{spec()}",
        f"MT-x-W,masstone_over_white,black,phthalo-blue:1,,{spec()}",
        f"SUB-W,substrate_white,white,phthalo-blue:1,,{spec()}",
        f"MX-13-W,blend,white,phthalo-blue:1,,{spec()}",
    ]
    rep = parse_calibration_csv(csv_text(*rows), paints)
    errs = codes(rep)
    assert (2, "sample_id", "bad_sample_id") in errs
    assert (4, "sample_id", "duplicate_sample_id") in errs
    assert (5, "substrate", "substrate_mismatch") in errs
    assert (6, "components", "unexpected_components") in errs
    assert (7, "type", "bad_type") in errs
    assert (3, "sample_id", "missing_pair") in codes(rep, "warning")


def test_notes_tokens(paints: dict[str, PaintInfo]) -> None:
    rows = [
        f"MX-14-W,mixture,white,phthalo-blue:1,gap_um=abc,{spec()}",
        f"MX-15-W,mixture,white,phthalo-blue:1,foo=1;holdout;looks streaky,{spec()}",
        f"MT-y-W,masstone_over_white,white,phthalo-blue:1,holdout,{spec()}",
    ]
    rep = parse_calibration_csv(csv_text(*rows), paints)
    assert (2, "notes", "bad_gap") in codes(rep)
    assert (3, "notes", "unknown_note_key") in codes(rep, "warning")
    assert (4, "notes", "holdout_ignored") in codes(rep, "warning")
    mx15 = [s for s in rep.samples if s.sample_id == "MX-15-W"][0]
    assert mx15.holdout


def test_no_paints_mapping_skips_id_checks() -> None:
    rep = parse_calibration_csv(csv_text(f"MX-16-W,mixture,white,anything:1,,{spec()}"))
    assert rep.ok


def test_empty_file() -> None:
    assert parse_calibration_csv("").errors[0].code == "empty_file"
    assert parse_calibration_csv(HEADER + "\n").errors[0].code == "empty_file"


def test_json_schema_committed_and_valid_for_sample_rows() -> None:
    committed = (ROOT / "docs" / "calibration_row.schema.json").read_text()
    assert committed == schema_json(), "run `uv run paintmixer schema --out ../docs/...`"
    schema = calibration_row_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    rows = list(csv.DictReader(io.StringIO((SAMPLE_DATA / "calibration_starter5.csv").read_text())))
    for r in rows:
        validator.validate(r)
    bad = dict(rows[0], type="blend")
    assert not validator.is_valid(bad)
    assert json.loads(committed)["title"].startswith("PaintMixer")
