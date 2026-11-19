from clippy import picker
from clippy.config import Settings

from conftest import make_words


def ten_second_sentences(n=10):
    return [{"id": i, "s": 10.0 * i, "e": 10.0 * i + 10.0, "i0": i, "i1": i + 1, "text": f"s{i}"} for i in range(n)]


def test_fit_trims_end_keeps_hook():
    # a 100 s range must be cut back from the END (never the start) until it fits 60 s
    assert picker._fit(ten_second_sentences(), 0, 9, Settings(min_seconds=20, max_seconds=60)) == (0, 5)


def test_fit_extends_too_short_clip_forward():
    assert picker._fit(ten_second_sentences(), 0, 0, Settings(min_seconds=20, max_seconds=60)) == (0, 1)


def test_finalize_drops_leading_fillers_in_english():
    words = make_words("I mean, so Elon has a plan.")
    sents = picker.build_sentences(words)
    clip = picker._finalize(sents, words, 0, 0, Settings(), "en")
    assert clip["i0"] == 3                      # starts on "Elon"
    assert clip["start"] == 1.42                # just after "so" ends (1.40) + 0.02


def test_finalize_keeps_words_for_other_languages():
    words = make_words("I mean, so Elon has a plan.")
    sents = picker.build_sentences(words)
    assert picker._finalize(sents, words, 0, 0, Settings(), "no")["i0"] == 0


def teaser_fixture():
    words = make_words("One two three. Four five six. Seven eight nine. Ten eleven twelve.", step=1.0, length=0.8)
    return picker.build_sentences(words), words


def test_teaser_rejects_first_sentence_and_lines_too_close_to_start():
    sents, words = teaser_fixture()
    assert picker._teaser(sents, words, 0, 0, 3) is None   # the opening line is not a flash-forward
    assert picker._teaser(sents, words, 1, 0, 3) is None   # starts only 3 s in (< 4 s)
    assert picker._teaser(sents, words, 4, 0, 3) is None   # outside the clip


def test_teaser_accepts_line_inside_clip():
    sents, words = teaser_fixture()
    assert picker._teaser(sents, words, 2, 0, 3) == {"i0": 6, "i1": 9, "start": 5.94, "end": 8.92}


def test_parse_json_strips_think_and_fences():
    assert picker.parse_json('<think>hmm</think>```json\n{"a": 1}\n```') == {"a": 1}


def test_heat_by_sentence_uses_spikes_not_intro():
    heat = [{"s": float(i), "e": float(i + 1), "v": v} for i, v in enumerate([1.0] * 3 + [0.3] * 50 + [0.9] + [0.3] * 46)]
    sents = [{"s": 0.5, "e": 1.5}, {"s": 53.2, "e": 53.8}, {"s": 80.0, "e": 81.0}]
    assert picker._heat_by_sentence(sents, heat) == [0.0, 1.0, 0.0]


def test_tidy_post_moves_trailing_hashtags_out_of_the_caption():
    # the AI often ends its caption with the same hashtags it also returns separately
    caption, tags = picker.tidy_post("Who would you trust? 👇 #linux #ai #Coding",
                                     ["#Linux", "#AI", "#openSource"])
    assert caption == "Who would you trust? 👇"
    assert tags == ["#Linux", "#AI", "#openSource", "#Coding"]


def test_tidy_post_handles_hashtag_only_lines_and_bare_tags():
    caption, tags = picker.tidy_post("From Antarctica to a spacewalk.\nWhat scares you?\n#astronaut #space",
                                     ["astronaut", "#Courage", "#courage", ""])
    assert caption == "From Antarctica to a spacewalk.\nWhat scares you?"
    assert tags == ["#astronaut", "#Courage", "#space"]


def test_tidy_post_keeps_hashtags_used_inside_a_sentence():
    caption, tags = picker.tidy_post("Why #NASA keeps flying. Agree?", ["#NASA", "#space"])
    assert caption == "Why #NASA keeps flying. Agree?"
    assert tags == ["#NASA", "#space"]


def test_tidy_post_caps_the_hashtag_count():
    _, tags = picker.tidy_post("x #a #b #c #d", ["#e", "#f", "#g", "#h"])
    assert tags == ["#e", "#f", "#g", "#h", "#a", "#b"]


def test_scout_splits_a_chunk_the_ai_says_is_too_long_and_keeps_going(monkeypatch):
    import re

    from clippy import llm as llm_mod
    seen = {"too_long": 0, "ok": []}

    class SmallContextAI:
        base, model, context = "http://fake/v1", "tiny", 0

        def __init__(self, cfg, log=print):
            self.cfg = cfg

        def wait_ready(self, *a, **k):
            pass

        def budget_chars(self, out_tokens=3000):
            return self.cfg.llm_chunk_chars                      # server didn't say: start big

        def json(self, system, user, schema, max_tokens=3000, temperature=0.4):
            if schema is picker.SCOUT_SCHEMA:
                if len(user) > 4000:
                    seen["too_long"] += 1
                    raise llm_mod.ContextTooSmall("context size exceeded")
                ids = [int(i) for i in re.findall(r"^\[(\d+)\]", user, re.M)]
                seen["ok"].append(len(user))
                return {"clips": [{"start_id": ids[0], "end_id": ids[0] + 9, "score": 70, "why": "w", "hook": "h"}]}
            raise RuntimeError("refine not needed here")          # picker falls back to the raw pick

    monkeypatch.setattr(picker, "LLM", SmallContextAI)
    words = make_words(" ".join(f"sentence number {i} is here." for i in range(300)))
    clips = picker.pick_clips(Settings(clips=3, min_seconds=20, max_seconds=40), {"title": "T"},
                              {"words": words, "language": "en"}, log=lambda m: None)
    assert seen["too_long"] >= 1 and seen["ok"] and max(seen["ok"]) <= 4000
    assert len(clips) == 3


def test_with_eyes_only_the_kept_candidates_are_finalized(monkeypatch):
    """vision.ranker rates the rough candidates first: the extras never get the slow finishing pass."""
    import re
    refined = []

    class AI:
        base, model, context = "http://fake/v1", "m", 0

        def __init__(self, cfg, log=print):
            self.cfg = cfg

        def wait_ready(self, *a, **k):
            pass

        def budget_chars(self, out_tokens=3000):
            return 200000

        def json(self, system, user, schema, max_tokens=3000, temperature=0.4):
            if schema is picker.SCOUT_SCHEMA:
                return {"clips": [{"start_id": i, "end_id": i + 9, "score": 90 - i, "why": "w", "hook": f"h{i}"}
                                  for i in (0, 20, 40, 60, 80)]}
            a = int(re.search(r"Current pick: sentences (\d+)", user).group(1))
            refined.append(a)
            return {"thoughts": "", "start_id": a, "end_id": a + 9, "title": f"T{a}", "caption": "c", "hashtags": [],
                    "emphasis": [], "emoji": [], "teaser_id": -1, "score": 80}

    monkeypatch.setattr(picker, "LLM", AI)
    looks = {"h0": 2, "h20": 9, "h40": 9, "h60": 3}

    def rank(cands, progress=None):
        for c in cands:
            c["look"], c["look_why"] = looks.get(c["hook"], 5), "why"
        return sorted(cands, key=lambda c: -(0.75 * c["score"] + 2.5 * c["look"]))
    words = make_words(" ".join(f"sentence number {i} is here." for i in range(120)))
    clips = picker.pick_clips(Settings(clips=2, min_seconds=20, max_seconds=40), {"title": "T"},
                              {"words": words, "language": "en"}, log=lambda m: None, rank=rank)
    # 4 rated (75, 72.5, 60, 30 by what's said and how it looks); only the best 2 get the finishing pass
    assert sorted(refined) == [0, 20]
    assert [c["title"] for c in clips] == ["T20", "T0"] and [c["look"] for c in clips] == [9, 2]
    assert clips[0]["score"] == round(0.75 * 80 + 2.5 * 9) and clips[0]["score_said"] == 80
