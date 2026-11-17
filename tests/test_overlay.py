import numpy as np
import pytest

from clippy.config import Settings
from clippy.overlay import STYLES, Overlay, Word, make_chunks



def overlay(words, style="hormozi", title="", emojis=()):
    return Overlay(Settings(), words, 3.0, title, ["money"], list(emojis),
                   lambda t: {"caption_y": 1300, "title_y": 200}, style)


def test_overlay_merges_whisper_split_numbers():
    ov = overlay([{"w": "win", "s": 0.0, "e": 0.4}, {"w": "$10", "s": 0.5, "e": 0.8},
                  {"w": ",000", "s": 0.8, "e": 1.0}, {"w": "now.", "s": 1.1, "e": 1.4}])
    texts = [w.text for c in ov.chunks for w in c.words]
    assert texts == ["WIN", "$10,000", "NOW"]


def test_make_chunks_respects_max_words_and_question_marks():
    w = lambda t, s: Word(t, s, s + 0.3)
    assert [[x.text for x in c] for c in make_chunks([w("a", 0), w("b", .3), w("c", .6), w("d", .9)], 3, 50)] == [["a", "b", "c"], ["d"]]
    assert [[x.text for x in c] for c in make_chunks([w("a", 0), w("b?", .3), w("c", .6)], 3, 50)] == [["a", "b?"], ["c"]]


@pytest.mark.parametrize("style", list(STYLES))
def test_overlay_draws_captions_title_and_emoji(style):
    ov = overlay([{"w": "make", "s": 0.1, "e": 0.4}, {"w": "money", "s": 0.5, "e": 0.9}], style,
                 title="How To Win", emojis=[{"word": "money", "emoji": "💰"}])
    frame = np.zeros((1920, 1080, 3), np.uint8)
    ov.draw(frame, 0.7)
    assert frame[1100:1500].any()       # caption area painted
    assert frame[150:500].any()         # title area painted


@pytest.mark.parametrize("style", ["beast", "hormozi"])
def test_popping_word_never_touches_its_neighbour(style):
    ov = overlay([{"w": "few", "s": 0.10, "e": 0.40}, {"w": "seconds", "s": 0.40, "e": 0.90}], style)
    frame = np.full((1920, 1080, 3), 128, np.uint8)                  # plain grey background
    ov.draw(frame, 0.40 + 0.07)                                       # "seconds" at the top of its pop
    band = frame[1100:1500].astype(int)
    ink = ((band.max(axis=2) < 40) | (band.max(axis=2) > 200)).any(axis=0)   # outline or fill, not shadow
    runs = int(ink[0]) + int(np.count_nonzero(np.diff(ink.astype(int)) == 1))
    assert runs == 2, f"{style}: the popping word runs into its neighbour ({runs} ink run)"
