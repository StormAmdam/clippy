"""Clippy controls uploads to the owner's channels, so only its own pages may drive it."""
import importlib

OWN = "http://127.0.0.1:7860"


def _app():
    from fastapi.testclient import TestClient

    from clippy import server
    server = importlib.reload(server)
    return server, TestClient(server.app, base_url=OWN)


def test_dns_rebinding_page_gets_refused(tmp_output):
    server, c = _app()
    assert c.get("/api/library").status_code == 200
    assert c.get("/api/library", headers={"Host": "evil.example:7860"}).status_code == 403


def test_other_website_cannot_trigger_actions(tmp_output):
    server, c = _app()
    job = server.STORE.create(url="x")
    r = c.post(f"/api/jobs/{job['id']}/cancel", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert server.STORE.get(job["id"])["state"] == "queued"
    r = c.post(f"/api/jobs/{job['id']}/cancel", headers={"Origin": OWN})      # Clippy's own page
    assert r.status_code == 200 and server.STORE.get(job["id"])["state"] == "cancelled"


def test_phone_on_the_same_network_still_works(tmp_output):
    server, c = _app()
    assert c.get("/api/library", headers={"Host": "192.168.1.20:7860"}).status_code == 200
    assert c.get("/api/library", headers={"Host": "[::1]:7860"}).status_code == 200
    assert c.get("/api/library", headers={"Host": "my-laptop.local:7860"}).status_code == 200
