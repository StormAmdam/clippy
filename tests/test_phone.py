"""Review on a phone: a separate, limited server on the Wi-Fi, opened with the secret in a QR code."""
import httpx
import pytest
from fastapi.testclient import TestClient

from clippy import autopilot, phone


@pytest.fixture
def shorts(tmp_output):
    d = tmp_output / "abc123" / "clips-p1"
    d.mkdir(parents=True)
    (d / "01-short.mp4").write_bytes(b"0123456789" * 1000)
    (d / "01-short.jpg").write_bytes(b"jpg")
    (tmp_output / "abc123" / "source.mp4").write_bytes(b"the whole video")
    autopilot._add_items([{"id": "r1", "status": "pending", "file": "abc123/clips-p1/01-short.mp4", "created": 1.0,
                           "thumb": "abc123/clips-p1/01-short.jpg", "title": "Mine", "profile_name": "Space"}])
    yield tmp_output
    phone.stop()


@pytest.fixture
def on(shorts):
    s = phone.start()
    base = f"http://127.0.0.1:{s['port']}"
    return base, phone._state["token"]


def test_nothing_without_the_secret_and_a_wrong_link_is_refused(on):
    base, token = on
    assert httpx.get(base + "/").status_code == 401
    assert httpx.get(base + "/api/review").status_code == 401
    assert httpx.get(base + "/media/abc123/clips-p1/01-short.mp4").status_code == 401
    assert httpx.get(base + "/pair", params={"key": "guess"}).status_code == 403


def test_the_qr_secret_lets_a_phone_in_and_it_can_only_review(on):
    base, token = on
    with httpx.Client(base_url=base) as c:
        r = c.get("/pair", params={"key": token})
        assert r.status_code == 303 and r.headers["location"] == "/" and "httponly" in r.headers["set-cookie"].lower()
        assert "Clippy Review" in c.get("/").text
        [item] = c.get("/api/review").json()
        assert item["id"] == "r1" and item["title"] == "Mine" and "description" in item
        v = c.get("/media/abc123/clips-p1/01-short.mp4", headers={"Range": "bytes=0-9"})
        assert v.status_code == 206 and v.content == b"0123456789"          # phones can seek in the video
        assert "attachment" in c.get("/media/abc123/clips-p1/01-short.mp4", params={"download": 1}).headers[
            "content-disposition"]
        assert c.get("/media/abc123/source.mp4").status_code == 404           # not a short in Review
        assert c.get("/media/../settings.json").status_code == 404
        for path in ("/api/settings", "/api/jobs", "/api/extensions", "/api/phone"):
            assert c.get(path).status_code == 404                              # the rest of Clippy isn't here
        assert c.post("/api/review/r1", json={"action": "approve"}).json()["status"] == "approved"
        assert c.post("/api/review/r1", json={"action": "restore"}).json()["status"] == "pending"
        assert c.post("/api/review/r1", json={"action": "save"}).status_code == 400
        bad = c.post("/api/review/r1", json={"action": "reject"}, headers={"Origin": "http://evil.example"})
        assert bad.status_code == 403 and autopilot.get_item("r1")["status"] == "pending"
    assert phone.status()["devices"][0]["ip"] == "127.0.0.1"


def test_turning_it_off_logs_phones_out(on):
    base, token = on
    with httpx.Client(base_url=base) as c:
        c.get("/pair", params={"key": token})
        assert c.get("/api/review").status_code == 200
        phone.stop()
        with pytest.raises(httpx.ConnectError):
            c.get("/api/review")
    s = phone.start()
    assert phone._state["token"] != token                                     # an old link doesn't work again
    assert httpx.get(f"http://127.0.0.1:{s['port']}/pair", params={"key": token}).status_code == 403


def test_only_devices_on_this_network(shorts):
    outside = TestClient(phone.app, base_url="http://192.168.1.5:7880", client=("8.8.8.8", 4000))
    assert outside.get("/").status_code == 403
    rebound = TestClient(phone.app, base_url="http://evil.example:7880", client=("192.168.1.20", 4000))
    assert rebound.get("/").status_code == 403
    home = TestClient(phone.app, base_url="http://192.168.1.5:7880", client=("192.168.1.20", 4000))
    assert home.get("/").status_code == 401                                   # in the house, but no secret yet


def test_the_pc_controls_it_and_shows_the_code(shorts):
    from clippy import server
    here = TestClient(server.app, base_url="http://127.0.0.1:7860", client=("127.0.0.1", 50000))
    away = TestClient(server.app, base_url="http://192.168.1.5:7860", client=("192.168.1.20", 50000))
    assert away.post("/api/phone", json={"on": True}).status_code == 403
    assert away.get("/api/phone").status_code == 403                          # the address holds the secret
    s = here.post("/api/phone", json={"on": True}).json()
    assert s["on"] and (not s.get("ip") or s["url"].endswith(phone._state["token"]))
    if s.get("url"):
        svg = here.get("/api/phone/qr.svg")
        assert svg.status_code == 200 and svg.text.startswith("<svg")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg.text                  # or an <img> can't show it
    assert here.post("/api/phone", json={"on": False}).json()["on"] is False
    assert here.get("/api/phone/qr.svg").status_code == 409
