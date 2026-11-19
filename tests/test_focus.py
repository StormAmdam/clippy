"""An instruction for the highlight picker ("find practical advice about pricing") on one Make Clips job."""
from clippy import config, picker


def test_the_instruction_goes_into_both_prompts_cleaned_up():
    cfg = config.Settings(focus='  practical "advice"\n about pricing  ')
    assert picker.focus_of(cfg) == "practical advice about pricing"
    scout = picker._scout_prompt({"title": "Talk"}, "[0] 0:00 hello", 3, cfg, 2.5)
    assert 'asked for: "practical advice about pricing"' in scout and "return fewer" in scout
    assert "practical advice about pricing" in picker._refine_prompt("ctx", 0, 1, 30, "why", cfg, [])


def test_without_an_instruction_the_prompts_are_unchanged():
    cfg = config.Settings()
    assert "asked for" not in picker._scout_prompt({"title": "Talk"}, "[0] 0:00 hello", 3, cfg, 2.5)
    assert "wants clips about" not in picker._refine_prompt("ctx", 0, 1, 30, "why", cfg, [])


def test_an_instruction_is_a_job_option_and_never_reuses_old_picks(tmp_output, monkeypatch):
    from fastapi.testclient import TestClient

    from clippy import server
    assert "focus" in server.ALLOWED
    assert config.load({"focus": "pricing"}).focus == "pricing"
    import inspect

    from clippy import pipeline
    assert "and not cfg.focus" in inspect.getsource(pipeline.run)   # a new instruction needs new picks
    made = []
    monkeypatch.setattr(server, "_new_job", lambda **f: made.append(f) or {"id": "j"})
    TestClient(server.app, base_url="http://127.0.0.1:7860").post(
        "/api/jobs", json={"url": "https://youtu.be/abcdefghijk", "options": {"focus": "pricing", "nope": 1}})
    assert made[0]["options"] == {"focus": "pricing"}
