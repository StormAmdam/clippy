"""No-talking mode: deciding there's no speech, and picking clips from sound/action instead."""
import numpy as np

from clippy import highlights
from clippy.config import Settings
from clippy.transcribe import ENV_HZ

from conftest import make_words


def test_podcast_counts_as_speech():
    words = make_words(" ".join(["word"] * 600), step=0.5)          # 600 words in 5 minutes
    assert highlights.has_speech({"words": words, "duration": 300})


def test_music_or_gameplay_with_a_few_words_is_not_speech():
    words = make_words("yeah let's go oh no wow", start=100, step=40)  # 6 stray words in 10 minutes
    assert not highlights.has_speech({"words": words, "duration": 600})


def test_long_video_with_occasional_comments_is_not_speech():
    words = make_words(" ".join(["nice"] * 60), step=55)             # 60 words over an hour
    assert not highlights.has_speech({"words": words, "duration": 3600})


def test_audio_hits_finds_sudden_impacts_only():
    env = np.full(10 * ENV_HZ, -40.0, np.float32)
    for t in (2.0, 6.0):                                              # two hits, 0.3 s long
        env[int(t * ENV_HZ): int((t + 0.3) * ENV_HZ)] = -8.0
    hits = highlights.audio_hits(env, 0, 10)
    assert len(hits) == 2
    assert abs(hits[0] - 2.0) < 0.1 and abs(hits[1] - 6.0) < 0.1


def test_audio_hits_ignores_steady_loud_music():
    env = np.full(10 * ENV_HZ, -12.0, np.float32) + np.random.default_rng(0).normal(0, 0.5, 10 * ENV_HZ).astype(np.float32)
    assert highlights.audio_hits(env, 0, 10) == []


def _quiet_video_with_loud_moments(duration=600, loud=((200, 230), (400, 430))):
    env = np.full(duration * ENV_HZ, -38.0, np.float32)
    env += np.random.default_rng(1).normal(0, 1.0, len(env)).astype(np.float32)
    for a, b in loud:
        env[a * ENV_HZ: b * ENV_HZ] = -10.0
    return env


def test_picks_the_loud_moments_and_respects_lengths(monkeypatch):
    monkeypatch.setattr(highlights, "_visual_profile", lambda src, start, dur, fps=4.0: (5.0, []))
    monkeypatch.setattr(highlights, "_write_titles", lambda cfg, info, clips, log: [c.setdefault("title", "t") for c in clips])
    cfg = Settings(clips=2, min_seconds=20, max_seconds=60)
    env = _quiet_video_with_loud_moments()
    clips = highlights.pick_visual_clips(cfg, {"title": "x"}, "src.mp4", {"duration": 600}, env, log=lambda m: None)
    assert len(clips) == 2
    for c in clips:
        assert c["mode"] == "visual"
        assert cfg.min_seconds <= c["end"] - c["start"] <= cfg.max_seconds
        # each clip overlaps one of the loud moments
        assert any(c["start"] < b and c["end"] > a for a, b in ((200, 230), (400, 430)))
        if c["teaser"]:
            assert c["start"] <= c["teaser"]["start"] < c["teaser"]["end"] <= c["end"]
    a, b = sorted(clips, key=lambda c: c["start"])
    assert a["end"] <= b["start"]                                     # no overlap


def test_clip_starts_on_a_nearby_camera_cut(monkeypatch):
    cuts = []

    def profile(src, start, dur, fps=4.0):
        cuts.append(round(start + 3 + 1.5, 2))                       # a cut 1.5 s after each window's start
        return 5.0, [cuts[-1]]

    monkeypatch.setattr(highlights, "_visual_profile", profile)
    monkeypatch.setattr(highlights, "_write_titles", lambda cfg, info, clips, log: None)
    clips = highlights.pick_visual_clips(Settings(clips=1), {"title": "x"}, "src.mp4", {"duration": 600},
                                         _quiet_video_with_loud_moments(loud=((300, 340),)), log=lambda m: None)
    assert any(abs(clips[0]["start"] - (c + 0.04)) < 1e-6 for c in cuts)


def test_short_video_becomes_one_clip(monkeypatch):
    monkeypatch.setattr(highlights, "_write_titles", lambda cfg, info, clips, log: None)
    env = np.full(40 * ENV_HZ, -20.0, np.float32)
    clips = highlights.pick_visual_clips(Settings(clips=3, max_seconds=60), {"title": "x"}, "s", {"duration": 40}, env,
                                         log=lambda m: None)
    assert len(clips) == 1 and clips[0]["start"] == 0 and clips[0]["end"] == 40


def test_titles_fall_back_to_the_video_title_when_ai_is_offline(monkeypatch):
    from clippy import picker

    class Offline:
        def __init__(self, *a, **k): pass
        def wait_ready(self, *a, **k): raise RuntimeError("AI server not reachable")

    monkeypatch.setattr(picker, "LLM", Offline)
    clips = [{"start": 0, "end": 30, "why": "loud peak"}, {"start": 100, "end": 130, "why": "fast cuts"}]
    highlights._write_titles(Settings(), {"title": "Epic Goal Compilation"}, clips, log=lambda m: None)
    assert clips[0]["title"] == "Epic Goal Compilation · Part 1"
    assert clips[1]["title"] == "Epic Goal Compilation · Part 2"
    assert clips[0]["hashtags"] == []


def test_no_caption_clips_get_a_bigger_centred_square_window():
    from clippy.reframe import fit_crop_for, fit_geometry
    energy = np.zeros(96)
    energy[40:56] = 1.0                                               # action in the middle of a 16:9 frame
    x0, w = fit_crop_for(energy, 2560, 1440, aspect=1.0, edge_limit=0.35)
    assert w == 1440.0 and 0 < x0 < 2560 - 1440                       # square window inside the frame
    fh, top = fit_geometry(int(w), 1440, mid=True)
    assert fh == 1080 and top == (1920 - 1080) // 2                   # 1080x1080, vertically centred


def test_default_fit_layout_is_unchanged():
    from clippy.reframe import fit_geometry
    assert fit_geometry(1920, 1080) == fit_geometry(1920, 1080, mid=False)
