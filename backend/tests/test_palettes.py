from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"


def _colour(c: TestClient, name: str, hex_: str) -> int:
    r = c.post(f"{API}/colors", json={"name": name, "hex": hex_})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_palette_crud_and_order(client: TestClient) -> None:
    a, b, d = (
        _colour(client, n, h)
        for n, h in (("Sage", "#859072"), ("Fog", "#a5b0ba"), ("Slate", "#626c78"))
    )
    r = client.post(f"{API}/palettes", json={"name": "Facade refresh", "color_ids": [b, a, b]})
    assert r.status_code == 201, r.text
    pal = r.json()
    assert pal["color_ids"] == [b, a]  # order kept, repeats dropped
    pal = client.patch(f"{API}/palettes/{pal['id']}", json={"color_ids": [d, a]}).json()
    assert pal["color_ids"] == [d, a]
    r = client.post(f"{API}/palettes", json={"name": "Bad", "color_ids": [9999]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_colors"
    client.delete(f"{API}/colors/{d}")
    assert client.get(f"{API}/palettes/{pal['id']}").json()["color_ids"] == [a]
    assert [p["name"] for p in client.get(f"{API}/palettes").json()] == ["Facade refresh"]
    assert client.delete(f"{API}/palettes/{pal['id']}").status_code == 204
    assert client.get(f"{API}/palettes/{pal['id']}").status_code == 404
