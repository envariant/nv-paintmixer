"""Worksheet outputs: JSON-able dict, calibration CSV skeleton and a printable HTML sheet."""

from __future__ import annotations

import csv
import html
import io
from typing import Any

from paintmixer.calibration.format import BASE_COLUMNS, SPECTRUM_COLUMNS, format_components
from paintmixer.domain import PaintInfo
from paintmixer.worksheet.plan import WorksheetPlan


def plan_to_dict(plan: WorksheetPlan, paints: dict[str, PaintInfo]) -> dict[str, Any]:
    o = plan.options
    rows = []
    for d in plan.drawdowns:
        for sid, sub, stype in d.sample_ids():
            rows.append(
                {
                    "sample_id": sid,
                    "drawdown_id": d.drawdown_id,
                    "type": stype.value,
                    "substrate": sub.value,
                    "notes": d.notes,
                }
            )
    return {
        "options": dict(o.__dict__),
        "warnings": plan.warnings,
        "n_drawdowns": len(plan.drawdowns),
        "n_rows": plan.n_rows,
        "n_holdout": sum(d.holdout for d in plan.drawdowns),
        "drawdowns": [
            {
                "drawdown_id": d.drawdown_id,
                "group": d.group,
                "type": d.type.value,
                "components": d.components,
                "masses_g": {p: round(m, 4) for p, m in d.masses_g.items()},
                "masses_rounded_g": {
                    p: round(round(m / o.scale_resolution_g) * o.scale_resolution_g, 6)
                    for p, m in d.masses_g.items()
                },
                "gap_um": d.gap_um,
                "holdout": d.holdout,
                "low_mass": d.low_mass,
                "sample_ids": [s for s, _, _ in d.sample_ids()],
                "notes": d.notes,
            }
            for d in plan.drawdowns
        ],
        "rows": rows,
        "totals_g": {p: round(v, 3) for p, v in plan.totals_g.items()},
        "low_mass": [w.__dict__ for w in plan.low_mass],
        "paints": {
            p.id: {"name": p.label, "role": p.role.value, "density_g_per_ml": p.density_g_per_ml}
            for p in paints.values()
            if p.id in plan.totals_g
        },
    }


def plan_to_csv(plan: WorksheetPlan) -> str:
    """Calibration CSV skeleton: one row per sample, spectra and weighed masses left blank."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([*BASE_COLUMNS, "components_mass_g", *SPECTRUM_COLUMNS])
    for d in plan.drawdowns:
        for sid, sub, stype in d.sample_ids():
            w.writerow(
                [sid, stype.value, sub.value, format_components(d.components), d.notes, ""]
                + [""] * len(SPECTRUM_COLUMNS)
            )
    return buf.getvalue()


_CSS = """
body{font:11pt/1.35 system-ui,sans-serif;color:#111;background:#fff;margin:16mm}
h1{font-size:16pt;margin:0 0 4pt}h2{font-size:12pt;margin:14pt 0 4pt}
table{border-collapse:collapse;width:100%;margin-bottom:8pt}
th,td{border:1px solid #777;padding:2pt 4pt;text-align:left;vertical-align:top}
th{background:#eee}.num{text-align:right;font-variant-numeric:tabular-nums}
.blank{min-width:22mm}.box{display:inline-block;width:9pt;height:9pt;border:1px solid #333;
margin-right:3pt}.low{font-weight:700}.meta{color:#444;font-size:9pt}
tr{break-inside:avoid}@media print{body{margin:10mm}}
"""


def plan_to_html(plan: WorksheetPlan, paints: dict[str, PaintInfo], title: str = "") -> str:
    o = plan.options
    esc = html.escape

    def name(pid: str) -> str:
        return esc(paints[pid].label if pid in paints else pid)

    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{esc(title or 'Calibration worksheet')}</title><style>{_CSS}</style></head><body>",
        f"<h1>{esc(title or 'Calibration worksheet')}</h1>",
        f"<p class='meta'>Batch {o.batch_g:g} g per drawdown · scale resolution "
        f"{o.scale_resolution_g:g} g · standard gap {o.standard_gap_um:g} µm · "
        f"{len(plan.drawdowns)} drawdowns, {plan.n_rows} readings rows · every "
        f"{o.holdout_every}th mixture is a hold-out · seed {o.seed}</p>",
    ]
    for wmsg in plan.warnings:
        out.append(f"<p><strong>Note:</strong> {esc(wmsg)}</p>")
    out.append(
        "<h2>Paint needed (incl. spare)</h2><table><tr><th>Paint</th><th class='num'>g</th></tr>"
    )
    for pid, g in plan.totals_g.items():
        out.append(f"<tr><td>{name(pid)}</td><td class='num'>{g:.1f}</td></tr>")
    out.append("</table>")
    if plan.low_mass:
        out.append("<h2>Low-mass warnings</h2><ul>")
        for lw in plan.low_mass:
            out.append(f"<li><strong>{esc(lw.drawdown_id)}</strong>: {esc(lw.message)}</li>")
        out.append("</ul>")
    out.append(
        "<h2>Drawdowns</h2><table><tr><th>Drawdown</th><th>Paint</th><th class='num'>Target g</th>"
        "<th class='blank'>Actual g</th><th>Gap</th><th>Readings (3 per background)</th></tr>"
    )
    for d in plan.drawdowns:
        comps = list(d.masses_g.items()) or [("—", 0.0)]
        span = len(comps)
        readings = "<br>".join(
            f"{esc(sid)} " + "<span class='box'></span>" * 3 for sid, _, _ in d.sample_ids()
        )
        label = esc(d.drawdown_id) + (" <em>(hold-out)</em>" if d.holdout else "")
        for k, (pid, m) in enumerate(comps):
            low = " class='num low'" if pid in d.low_mass else " class='num'"
            cells = [f"<td>{name(pid) if pid != '—' else '—'}</td>"]
            cells.append(
                f"<td{low}>{m:.3f}{' !' if pid in d.low_mass else ''}</td>"
                if d.masses_g
                else "<td></td>"
            )
            cells.append("<td class='blank'></td>")
            if k == 0:
                gap = f"{d.gap_um:g} µm" if d.components else ""
                out.append(
                    f"<tr><td rowspan='{span}'>{label}</td>{''.join(cells)}"
                    f"<td rowspan='{span}'>{gap}</td><td rowspan='{span}'>{readings}</td></tr>"
                )
            else:
                out.append(f"<tr>{''.join(cells)}</tr>")
    out.append("</table></body></html>")
    return "".join(out)
