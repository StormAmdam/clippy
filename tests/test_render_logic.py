import numpy as np
import pytest

from clippy import render
from clippy.config import Settings


def envelope(quiet_db):
    """5 s at 100 Hz: speech (-20 dB) at 0–1 s and 3–4 s, the gap at `quiet_db`."""
    env = np.full(500, quiet_db, dtype=np.float32)
    env[0:100] = -20
    env[300:400] = -20
    env[400:500] = -60
    return env


WORDS = [{"w": "hello", "s": 0.0, "e": 1.0}, {"w": "again", "s": 3.0, "e": 4.0}]


def test_keep_intervals_cuts_quiet_gap():
    keeps = render.keep_intervals(WORDS, 0.0, 5.0, 10, envelope(-60), Settings(max_pause=0.45))
    assert keeps == [(0, 12), (29, 50)]


def test_keep_intervals_keeps_gap_with_music_or_crowd():
    keeps = render.keep_intervals(WORDS, 0.0, 5.0, 10, envelope(-22), Settings(max_pause=0.45))
    assert keeps == [(0, 50)]


def test_map_time_skips_removed_gap():
    keeps = [(0.0, 2.0), (4.0, 8.0)]
    assert render._map_time(5.0, keeps) == 3.0
    assert render._map_time(3.0, keeps) == 2.0   # inside the removed gap → lands on the cut


def test_motion_intro_slam_and_teaser_boundary():
    zoom, blur, flash = render._motion(60, 30, [(0, 30, "start"), (30, 60, "part")], [], [30], Settings())
    assert zoom[0] == pytest.approx(1.17, abs=0.005)   # starts zoomed in, snaps out
    assert blur[30] == 1.0 and flash[30] == pytest.approx(0.6)
    assert flash[29] == 0.0 and blur[10] == 0.0


# ── Task 5: fuller frames for shots without a face ──

def test_fit_crop_centred_content_gets_4x3():
    from clippy.reframe import fit_crop_for
    energy = np.zeros(96)
    energy[40:57] = 1.0                       # columns 40–56 = pixels 800–1140 → centre 970 px
    assert fit_crop_for(energy, 1920, 1080) == (250.0, 1440.0)


def test_fit_crop_off_centre_content_is_clamped():
    from clippy.reframe import fit_crop_for
    energy = np.zeros(96)
    energy[10:31] = 1.0                       # pixels 200–620 → centre 410 px → window clamps to the left edge
    assert fit_crop_for(energy, 1920, 1080) == (0.0, 1440.0)


def test_fit_crop_edge_content_keeps_full_frame():
    from clippy.reframe import fit_crop_for
    assert fit_crop_for(np.ones(96), 1920, 1080) is None          # 25 % of the detail sits in the outer bands
    assert fit_crop_for(np.zeros(96), 1920, 1080) is None         # nothing to aim at
    narrow = np.zeros(96)
    narrow[40:57] = 1.0
    assert fit_crop_for(narrow, 1440, 1080) is None               # already 4:3 — cropping gains nothing


def test_voice_polish_removes_low_rumble():
    import subprocess
    def band_level(filters, hz):
        cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=40:d=2", "-f", "lavfi", "-i", "sine=f=1000:d=2",
               "-filter_complex", "[0][1]amix=inputs=2" + ("," + filters.rstrip(",") if filters else ""),
               "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
        x = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)[4000:28000]
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        freqs = np.fft.rfftfreq(len(x), 1 / 16000)
        return 20 * np.log10(spec[np.argmin(np.abs(freqs - hz))] + 1e-9)
    on, off = render._voice_filters(Settings(voice_polish=True)), render._voice_filters(Settings(voice_polish=False))
    assert off == ""
    # the compressor lowers overall level (loudnorm restores it later), so compare rumble *relative to* voice
    before = band_level("", 40) - band_level("", 1000)
    after = band_level(on, 40) - band_level(on, 1000)
    assert before - after > 6
    assert band_level(on, 1000) > band_level("", 1000) - 9     # the voice itself survives
