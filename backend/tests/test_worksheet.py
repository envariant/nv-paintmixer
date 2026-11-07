from __future__ import annotations

import itertools

import numpy as np
import pytest

from paintmixer.calibration.format import SampleType, parse_calibration_csv
from paintmixer.domain import PaintInfo, PaintRole
from paintmixer.worksheet.plan import (
    BLACK_TINTS,
    CHROMATIC_TINTS,
    WorksheetOptions,
    plan_worksheet,
    target_masses,
)
from paintmixer.worksheet.render import plan_to_csv, plan_to_dict, plan_to_html

STARTER = [
    "titanium-white",
    "carbon-black",
    "phthalo-blue",
    "quinacridone-magenta",
    "arylide-yellow",
]


def starter(paints: dict[str, PaintInfo]) -> list[PaintInfo]:
    return [paints[p] for p in STARTER]


def test_structure(paints: dict[str, PaintInfo]) -> None:
    plan = plan_worksheet(starter(paints))
    ids = [d.drawdown_id for d in plan.drawdowns]
    assert ids[:2] == ["SUB-W", "SUB-B"]
    assert len(ids) == len(set(ids))
    # white thickness series, one masstone per other paint
    assert {"MT-titanium-white-75", "MT-titanium-white-150", "MT-titanium-white-300"} <= set(ids)
    for p in STARTER[1:]:
        assert f"MT-{p}" in ids
    # tints: chromatic 5/15/35/65, black 1/3/10/30
    for p in STARTER[2:]:
        for f in CHROMATIC_TINTS:
            assert f"TN-{p}-{round(f * 100)}" in ids
    for f in BLACK_TINTS:
        assert f"TN-carbon-black-{round(f * 100)}" in ids
    # every pair of chromatics at 3 ratios + a 60 % white variant
    for a, b in itertools.combinations(STARTER[2:], 2):
        for r in (25, 50, 75):
            assert f"PR-{a}-{b}-{r}" in ids
        pw = next(d for d in plan.drawdowns if d.drawdown_id == f"PW-{a}-{b}")
        assert pw.components == {a: 0.2, b: 0.2, "titanium-white": 0.6}
    groups = {d.group for d in plan.drawdowns}
    assert {"neutral", "dark", "random"} <= groups
    # dark mixes: 10-35 % black, 2-3 chromatics, no white
    for d in plan.drawdowns:
        if d.group == "dark":
            assert 0.10 <= d.components["carbon-black"] <= 0.35
            assert "titanium-white" not in d.components
            assert 2 <= len(d.components) - 1 <= 3
        if d.group == "random":
            assert 2 <= len(d.components) <= 5
            assert min(d.components.values()) >= 0.05 - 1e-9
            assert all(abs(v * 100 - round(v * 100)) < 1e-6 for v in d.components.values())
    # every drawdown has two backgrounds except the substrate references
    assert plan.n_rows == 2 * len(ids) - 2


def test_fractions_and_mass_conservation(paints: dict[str, PaintInfo]) -> None:
    opts = WorksheetOptions(batch_g=12.0)
    plan = plan_worksheet(starter(paints), opts)
    for d in plan.drawdowns:
        if not d.components:
            continue
        assert sum(d.components.values()) == pytest.approx(1.0, abs=1e-3)
        assert sum(d.masses_g.values()) == pytest.approx(12.0)
        # volume fraction recovered from mass / density
        vols = {p: m / paints[p].density_g_per_ml for p, m in d.masses_g.items()}
        tot = sum(vols.values())
        for p, f in d.components.items():
            assert vols[p] / tot == pytest.approx(f / sum(d.components.values()), abs=1e-9)
    # totals = sum of all masses x 1.2
    for pid, total in plan.totals_g.items():
        raw = sum(d.masses_g.get(pid, 0.0) for d in plan.drawdowns)
        assert total == pytest.approx(raw * 1.2)


def test_target_mass_formula() -> None:
    paints = {
        "a": PaintInfo("a", PaintRole.WHITE, 2.0),
        "b": PaintInfo("b", PaintRole.CHROMATIC, 1.0),
    }
    m = target_masses({"a": 0.5, "b": 0.5}, paints, 9.0)
    assert m == pytest.approx({"a": 6.0, "b": 3.0})


def test_holdout_every_nth(paints: dict[str, PaintInfo]) -> None:
    for n in (2, 3, 4):
        plan = plan_worksheet(starter(paints), WorksheetOptions(holdout_every=n))
        mixes = [d for d in plan.drawdowns if d.type == SampleType.MIXTURE]
        flags = [d.holdout for d in mixes]
        assert flags == [(i % n) == n - 1 for i in range(len(mixes))]
        assert not any(d.holdout for d in plan.drawdowns if d.type != SampleType.MIXTURE)


def test_low_mass_flags(paints: dict[str, PaintInfo]) -> None:
    plan = plan_worksheet(starter(paints), WorksheetOptions(batch_g=10.0, scale_resolution_g=0.01))
    flagged = {(w.drawdown_id, w.paint_id) for w in plan.low_mass}
    assert ("TN-carbon-black-1", "carbon-black") in flagged
    for w in plan.low_mass:
        assert w.mass_g < 0.1
        assert w.suggested_batch_g * w.mass_g / 10.0 >= 0.1 - 1e-9
    # coarse scale -> everything small is flagged, very small suggests dilution
    coarse = plan_worksheet(starter(paints), WorksheetOptions(batch_g=10.0, scale_resolution_g=0.1))
    tn1 = [w for w in coarse.low_mass if w.drawdown_id == "TN-carbon-black-1"][0]
    assert tn1.suggest_dilution and "diluted stock" in tn1.message
    big = plan_worksheet(starter(paints), WorksheetOptions(batch_g=200.0))
    assert not big.low_mass


def test_seeded_reproducible(paints: dict[str, PaintInfo]) -> None:
    a = plan_worksheet(starter(paints), WorksheetOptions(seed=5))
    b = plan_worksheet(starter(paints), WorksheetOptions(seed=5))
    c = plan_worksheet(starter(paints), WorksheetOptions(seed=6))
    assert [d.components for d in a.drawdowns] == [d.components for d in b.drawdowns]
    assert [d.components for d in a.drawdowns] != [d.components for d in c.drawdowns]


def test_missing_roles_warn(paints: dict[str, PaintInfo]) -> None:
    plan = plan_worksheet([paints["phthalo-blue"], paints["arylide-yellow"]])
    text = " ".join(plan.warnings)
    assert "No white" in text and "No black" in text and "Fewer than 3" in text
    assert not any(d.type == SampleType.TINT for d in plan.drawdowns)


def test_csv_skeleton_round_trips_through_validator(paints: dict[str, PaintInfo]) -> None:
    plan = plan_worksheet(starter(paints))
    text = plan_to_csv(plan)
    # blank spectra are errors until measured...
    rep = parse_calibration_csv(text, paints)
    assert not rep.ok and {i.code for i in rep.errors} == {"missing_value"}
    # ...and fill in cleanly
    lines = text.splitlines()
    filled = [lines[0]]
    for ln in lines[1:]:
        cells = ln.split(",")
        cells[-31:] = ["0.5"] * 31
        filled.append(",".join(cells))
    rep = parse_calibration_csv("\n".join(filled), paints)
    assert rep.ok, rep.errors[:3]
    assert len(rep.samples) == plan.n_rows
    assert sum(s.holdout for s in rep.samples) == 2 * sum(d.holdout for d in plan.drawdowns)


def test_dict_and_html(paints: dict[str, PaintInfo]) -> None:
    plan = plan_worksheet(starter(paints))
    d = plan_to_dict(plan, paints)
    assert d["n_rows"] == plan.n_rows and len(d["rows"]) == plan.n_rows
    assert d["drawdowns"][2]["masses_rounded_g"]
    for dd in d["drawdowns"]:
        for v in dd["masses_rounded_g"].values():
            assert abs(v * 100 - round(v * 100)) < 1e-6
    h = plan_to_html(plan, paints, "Starter set")
    assert h.startswith("<!doctype html>") and "Actual g" in h
    assert h.count("class='box'") == 3 * plan.n_rows
    assert np.isfinite(sum(d["totals_g"].values()))
