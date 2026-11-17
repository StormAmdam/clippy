import importlib
import json


def test_upload_waits_for_undo_window():
    from clippy.server import _due_for_upload
    items = [{"id": "a", "status": "approved", "approved": 100.0},
             {"id": "b", "status": "approved", "approved": 95.0}]
    assert _due_for_upload(items, now=104.0) is None                 # both approved < 10 s ago
    assert _due_for_upload(items, now=106.0)["id"] == "b"             # oldest approval first, once 10 s passed
    assert _due_for_upload([], now=500.0) is None


def test_undo_moves_approved_short_back_to_waiting(tmp_output):
    from fastapi.testclient import TestClient

    from clippy import server
    (tmp_output / "_auto").mkdir()
    (tmp_output / "_auto" / "review.json").write_text(json.dumps(
        [{"id": "r1", "file": "A/clips/01.mp4", "status": "pending", "created": 1, "title": "T", "description": "D"}]))
    server = importlib.reload(server)
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    assert c.post("/api/review/r1", json={"action": "approve"}).json()["status"] == "approved"
    assert c.post("/api/review/r1", json={"action": "restore"}).json()["status"] == "pending"


def _queue(tmp_output, *items):
    (tmp_output / "_auto").mkdir(exist_ok=True)
    (tmp_output / "_auto" / "review.json").write_text(json.dumps(list(items)))


def test_undo_retry_and_reject_are_refused_once_the_upload_started(tmp_output):
    from fastapi.testclient import TestClient

    from clippy import autopilot, server
    _queue(tmp_output, {"id": "u1", "file": "A/clips/01.mp4", "status": "uploading", "created": 1, "approved": 1,
                        "title": "T", "description": "D"})
    server = importlib.reload(server)
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    for action in ("restore", "retry", "reject"):
        assert c.post("/api/review/u1", json={"action": action}).status_code == 409, action
    assert autopilot.get_item("u1")["status"] == "uploading"


def test_undo_pressed_as_the_upload_starts_is_never_silently_ignored(tmp_output, monkeypatch):
    import threading
    import time

    from fastapi import HTTPException

    from clippy import autopilot, server
    _queue(tmp_output, {"id": "r1", "file": "A/clips/01.mp4", "status": "approved", "created": 1,
                        "approved": time.time() - 60, "title": "T", "description": "D"})
    server = importlib.reload(server)
    answers, pressed = [], []

    def press_undo():
        try:
            server.review_act("r1", server.ReviewAction(action="restore"))
            answers.append("undone")
        except HTTPException as e:
            answers.append(e.status_code)

    real_items = autopilot.review_items

    def publisher_reads_queue(status=None):
        items = real_items(status)
        if not pressed:                            # the user's Undo lands while the publisher is choosing
            t = threading.Thread(target=press_undo)
            pressed.append(t)
            t.start()
            t.join(0.5)
        return items

    monkeypatch.setattr(autopilot, "review_items", publisher_reads_queue)
    claimed = server._claim_next_upload(time.time())
    pressed[0].join(5)
    status = real_items()[0]["status"]
    if claimed:                                    # the upload won, so the Undo must have been told so
        assert (status, answers) == ("uploading", [409])
    else:                                          # the Undo won, so nothing uploads
        assert (status, answers) == ("pending", ["undone"])
