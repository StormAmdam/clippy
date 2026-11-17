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
