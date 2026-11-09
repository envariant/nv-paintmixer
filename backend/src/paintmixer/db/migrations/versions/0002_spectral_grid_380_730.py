"""spectral grid 400-700 nm (31 bands) -> 380-730 nm (36 bands)

Stored spectra and K/S curves are extended by holding the edge values (380, 390 nm = 400 nm;
710-730 nm = 700 nm). With the folded ASTM weights this leaves every stored colour unchanged.

Revision ID: 0002
Revises: 0001
"""

import json
from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD, NEW, LEFT, RIGHT = 31, 36, 2, 3


def _is_spectrum(v: Any, n: int) -> bool:
    return isinstance(v, list) and len(v) == n and all(isinstance(x, (int, float)) for x in v)


def _up(v: Any) -> Any:
    if _is_spectrum(v, OLD):
        return [v[0]] * LEFT + list(v) + [v[-1]] * RIGHT
    if isinstance(v, list) and v and all(_is_spectrum(x, OLD) for x in v):
        return [_up(x) for x in v]
    return v


def _down(v: Any) -> Any:
    if _is_spectrum(v, NEW):
        return list(v[LEFT : NEW - RIGHT])
    if isinstance(v, list) and v and all(_is_spectrum(x, NEW) for x in v):
        return [_down(x) for x in v]
    return v


# table -> (primary key, plain spectrum columns, JSON-document columns with a "spectrum" key)
TABLES: dict[str, tuple[str, list[str], list[str]]] = {
    "calibration_sample": ("id", ["reflectance", "spread"], []),
    "fitted_model": ("id", ["K", "S", "tau", "substrate_white", "substrate_black"], []),
    "color_library_entry": ("id", ["spectrum"], []),
    "correction_log": ("id", ["measured_spectrum"], []),
    "job": ("id", [], ["target", "measured"]),
}


def _convert(fn: Callable[[Any], Any]) -> None:
    conn = op.get_bind()
    for table, (pk, cols, docs) in TABLES.items():
        names = cols + docs
        cols_sql = ", ".join(f'"{c}"' for c in names)
        rows = conn.execute(sa.text(f'SELECT "{pk}", {cols_sql} FROM "{table}"')).fetchall()
        for row in rows:
            updates: dict[str, str] = {}
            for i, c in enumerate(names, start=1):
                raw = row[i]
                if raw is None:
                    continue
                val = json.loads(raw) if isinstance(raw, str) else raw
                if c in docs:
                    if isinstance(val, dict) and "spectrum" in val:
                        new = dict(val, spectrum=fn(val["spectrum"]))
                    else:
                        new = val
                else:
                    new = fn(val)
                if new != val:
                    updates[c] = json.dumps(new)
            if updates:
                sets = ", ".join(f'"{c}" = :{c}' for c in updates)
                conn.execute(
                    sa.text(f'UPDATE "{table}" SET {sets} WHERE "{pk}" = :pk'),
                    {**updates, "pk": row[0]},
                )


def upgrade() -> None:
    _convert(_up)


def downgrade() -> None:
    _convert(_down)
