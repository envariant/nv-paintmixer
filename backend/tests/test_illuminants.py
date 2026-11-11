from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from paintmixer.colorsci.illuminants import (
    SERIES,
    adapt_to_d65,
    appearance,
    de_under,
    nearest_in_series,
)
from paintmixer.colorsci.spectral import N_BANDS, Illuminant, white_point

API = "/api/v1"


def test_every_illuminant_integrates_and_has_a_white() -> None:
    for ill in Illuminant:
        w = white_point(ill)
        assert abs(w[1] - 100.0) < 1e-6, ill
        assert np.all(w > 0), ill


def test_catalogue_covers_every_illuminant_once() -> None:
    codes = [m.code for s in SERIES for m in s.members]
    assert sorted(codes) == sorted(Illuminant)
    assert all(s.default in [m.code for m in s.members] for s in SERIES)


def test_nearest_in_series_keeps_closest_cct() -> None:
    assert nearest_in_series("D", "F12") == Illuminant.D50  # 3000 K -> 5003 K
    assert nearest_in_series("LED", "D50") == Illuminant.LED_B4  # 5003 K -> 5109 K
    assert nearest_in_series("F", "D65") == Illuminant.F7


def test_adaptation_maps_white_to_d65_white() -> None:
    for ill in (Illuminant.A, Illuminant.F11, Illuminant.LED_B1):
        np.testing.assert_allclose(
            adapt_to_d65(white_point(ill), ill), white_point("D65"), atol=1e-9
        )


def test_grey_looks_neutral_under_any_light() -> None:
    grey = np.full(N_BANDS, 0.3)
    for ill in Illuminant:
        a = appearance(grey, ill)
        assert abs(a.display_lab[1]) < 0.5 and abs(a.display_lab[2]) < 0.5, ill


def test_identical_spectra_match_everywhere() -> None:
    r = np.linspace(0.1, 0.6, N_BANDS)
    assert all(de_under(r, r, ill) < 1e-9 for ill in Illuminant)


def test_illuminants_endpoint(client: TestClient) -> None:
    out = client.get(f"{API}/illuminants").json()
    d = next(s for s in out if s["id"] == "D")
    assert d["default"] == "D65" and d["range"] == "5003–9300 K"
    assert [m["code"] for m in d["members"]] == ["D50", "D55", "D65", "D75", "D93"]


def test_appearance_endpoint(client: TestClient) -> None:
    ref = list(np.linspace(0.1, 0.6, N_BANDS))
    other = list(np.linspace(0.6, 0.1, N_BANDS))
    r = client.post(
        f"{API}/appearance",
        json={"reference": ref, "spectra": [ref, other], "illuminants": ["D65", "A", "LED-B3"]},
    )
    assert r.status_code == 200, r.text
    under = r.json()["under"]
    assert [u["illuminant"] for u in under] == ["D65", "A", "LED-B3"]
    for u in under:
        assert u["de2000"][0] < 1e-6 and u["de2000"][1] > 5
        assert u["reference"]["hex"].startswith("#")
    # under D65 the display colour is the colour itself
    d65 = under[0]
    np.testing.assert_allclose(d65["reference"]["lab"], d65["reference"]["display_lab"], atol=1e-3)


def test_solve_accepts_new_illuminants(fitted_client: TestClient) -> None:
    r = fitted_client.post(
        f"{API}/solve",
        json={"target": {"lab": [60, -10, 15], "name": "T"}, "illuminant": "LED-B3", "top_n": 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["illuminant"] == "LED-B3"
