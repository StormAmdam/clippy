"""Top countdowns: the AI's candidates become a ranked "#3 … #1" short, helped by laughter and kept apart in time."""
import numpy as np
import pytest

from clippy import llm, top
from clippy.config import Settings

SENTENCES = [f"Sentence number {i} is here and it goes on for a while." for i in range(40)]


def transcript(laugh_after: int | None = None) -> dict:
    words, t = [], 0.0
    for i, s in enumerate(SENTENCES):
        if laugh_after is not None and i == laugh_after + 1:
            s = "Hahaha " + s                      # how Whisper writes an audience cracking up
        for w in s.split():
            words.append({"w": w, "s": round(t, 2), "e": round(t + 0.4, 2), "p": 0.9})
            t += 0.5
        t += 0.6
    return {"language": "en", "duration": t, "words": words}


class FakeAI:
    """Answers like a real model would, from a script."""
    moments: list = []
    post: dict = {}

    def __init__(self, cfg, log=print):
        self.model, self.base = "fake", "http://fake"

    def wait_ready(self, **k):
        pass

    def budget_chars(self, **k):
        return 100000

    def json(self, system, user, schema, **k):
        return {"moments": FakeAI.moments} if "start_id" in str(schema) else FakeAI.post


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setattr(llm, "LLM", FakeAI)
    FakeAI.moments, FakeAI.post = [], {}
    return FakeAI


def m(a, b, score, label):
    return {"start_id": a, "end_id": b, "score": score, "label": label, "why": "funny"}


def test_the_best_moment_comes_last_and_laughter_counts(ai):
    ai.moments = [m(2, 3, 80, "Second best"), m(10, 11, 70, "Third best"), m(20, 21, 90, "Best"),
                  m(30, 31, 75, "Laughed at")]
    ai.post = {"caption": "Which one got you?", "hashtags": ["#lol"],
               "moments": [{"label": "", "emphasis": ["number"], "emoji": [{"word": "number", "emoji": "😂"}]},
                           {"label": "", "emphasis": [], "emoji": []}, {"label": "Top One", "emphasis": [], "emoji": []}]}
    clip = top.pick_top(Settings(top_theme="funny", top_count=3), {"title": "T"}, transcript(laugh_after=31),
                        log=lambda m: None)
    segs = clip["segments"]
    assert [s["rank"] for s in segs] == [3, 2, 1]
    # "Laughed at" (75 + 12 for the laugh right after) beats "Second best" (80); "Third best" (70) drops out.
    # The AI's second pass renamed #1 and left the others as they were.
    assert [s["label"] for s in segs] == ["Second best", "Laughed at", "Top One"]
    assert clip["title"] == "Top 3 Funniest Moments" and clip["format"] == "top"
    assert clip["caption"] == "Which one got you?" and "#lol" in clip["hashtags"] and "#funny" in clip["hashtags"]
    assert clip["emoji"] == [{"word": "number", "emoji": "😂"}]
    for s in segs:
        assert 4 <= s["end"] - s["start"] <= 16 and s["i1"] > s["i0"]


def test_moments_right_next_to_each_other_are_avoided(ai):
    ai.moments = [m(10, 11, 95, "A"), m(12, 13, 94, "Right after A"), m(25, 26, 60, "Far away"),
                  m(35, 36, 55, "Also far")]
    clip = top.pick_top(Settings(top_count=3), {"title": "T"}, transcript(), log=lambda m: None)
    assert [s["label"] for s in clip["segments"]] == ["Also far", "Far away", "A"]
    ai.moments = [m(10, 11, 95, "A"), m(12, 13, 94, "Right after A")]          # nothing else: neighbours will do
    clip = top.pick_top(Settings(top_count=3), {"title": "T"}, transcript(), log=lambda m: None)
    assert [s["label"] for s in clip["segments"]] == ["Right after A", "A"] and clip["title"] == "Top 2 Funniest Moments"


def test_no_usable_moments_says_so(ai):
    ai.moments = [{"start_id": "x"}]
    with pytest.raises(RuntimeError, match="didn't find any funniest moments"):
        top.pick_top(Settings(), {"title": "T"}, transcript(), log=lambda m: None)


def test_unknown_themes_fall_back_to_funny():
    assert top.theme("does-not-exist")["id"] == "funny"
    assert top.title_for(top.theme("shocking"), 5) == "Top 5 Most Shocking Moments"


def test_videos_without_talking_rank_by_sound_and_action():
    picks = [{"start": 10, "end": 20, "score": 50, "beats": [12.0]}, {"start": 40, "end": 50, "score": 90},
             {"start": 70, "end": 80, "score": 70}, {"start": 90, "end": 99, "score": 10}]
    clip = top.from_visual(Settings(top_count=3), picks)
    assert [(s["rank"], s["score"]) for s in clip["segments"]] == [(3, 50), (2, 70), (1, 90)]
    assert clip["segments"][0]["beats"] == [12.0] and clip["mode"] == "visual"


def test_the_countdown_shows_its_title_then_each_rank():
    from clippy.overlay import Overlay
    ranks = [{"t0": 0.0, "t1": 6.0, "rank": 3, "label": "Burnt Turkey"},
             {"t0": 6.0, "t1": 12.0, "rank": 2, "label": "The Monkey"},
             {"t0": 12.0, "t1": 18.0, "rank": 1, "label": "Fake Thesis"}]
    words = [{"w": "hello", "s": 1.0, "e": 1.4}]
    ov = Overlay(Settings(), words, 18.0, "Top 3 Funniest Moments", [], [],
                 lambda t: {"caption_y": 1300, "title_y": 220}, ranks=ranks)
    assert [(round(c[0], 1), round(c[1], 1)) for c in ov.cards] == [(0.0, 2.2), (2.2, 6.0), (6.0, 12.0), (12.0, 18.0)]
    assert ov.cards[-1][4] is False                    # the last card stays to the end
    for t in (0.5, 3.0, 7.0, 13.0, 17.9):
        frame = np.zeros((1920, 1080, 3), np.uint8)
        ov.draw(frame, t)
        assert frame[150:700].any()                    # a card at the top
    off = Overlay(Settings(title_seconds=0), words, 18.0, "Top 3", [], [],
                  lambda t: {"caption_y": 1300, "title_y": 220}, ranks=ranks)
    assert len(off.cards) == 3                         # no hook title: straight into #3


def test_with_eyes_a_moment_that_looks_dull_drops_out(ai):
    ai.moments = [m(2, 3, 80, "Talking head"), m(10, 11, 78, "Big fall"), m(20, 21, 90, "Best"),
                  m(30, 31, 76, "Crazy jump")]
    looks = {"Talking head": 1, "Big fall": 9, "Best": 8, "Crazy jump": 9}

    def rank(cands):
        for c in cands:
            c["look"] = looks[c["label"]]
        return sorted(cands, key=lambda c: -(0.75 * c["score"] + 2.5 * c["look"]))
    clip = top.pick_top(Settings(top_theme="funny", top_count=3), {"title": "T"}, transcript(), log=lambda m: None,
                        rank=rank)
    labels = [s["label"] for s in clip["segments"]]
    assert "Talking head" not in labels and labels[-1] == "Best"        # #1 is still the best overall
    assert all("look" in s for s in clip["segments"])
