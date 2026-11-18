"""What people see when YouTube won't give Clippy a video: plain words and what to do, and an automatic retry with a
newer yt-dlp when YouTube changed something."""
import subprocess

import pytest

from clippy import download


@pytest.mark.parametrize("raw,expect", [
    ("ERROR: [youtube] jNQXAC9IVRw: Sign in to confirm you’re not a bot. Use --cookies-from-browser", "isn't a bot"),
    ("ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate for some users.", "adults"),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "private"),
    ("ERROR: [youtube] x: Video unavailable. This video has been removed by the uploader", "isn't available"),
    ("ERROR: [youtube] x: Join this channel to get access to members-only content", "members only"),
    ("ERROR: [youtube] x: HTTP Error 429: Too Many Requests", "limiting"),
    ("ERROR: Unsupported URL: https://example.com/page", "isn't a video"),
    ("ERROR: [youtube] x: Unable to download API page: <urlopen error [Errno 11001] getaddrinfo failed>", "internet"),
    ("ERROR: [youtube] x: Requested format is not available", "needs an update"),
])
def test_known_failures_are_said_plainly(raw, expect):
    msg = download.explain(raw)
    assert expect in msg and "yt-dlp:" in msg
    assert "--cookies" not in msg.split("(yt-dlp:")[0]           # no command-line advice in the app's own words


def test_unknown_failures_keep_yt_dlps_words():
    assert download.explain("ERROR: something new") == "ERROR: something new"
    assert download.explain("") == "unknown error"


def test_an_old_yt_dlp_is_updated_and_the_link_tried_again(monkeypatch):
    answers = [subprocess.CompletedProcess([], 1, "", "ERROR: [youtube] x: Requested format is not available"),
               subprocess.CompletedProcess([], 0, '{"id": "abc", "title": "Works now", "duration": 10}', "")]
    monkeypatch.setattr(download.subprocess, "run", lambda *a, **k: answers.pop(0))
    refreshed = []
    monkeypatch.setattr(download, "_refresh_ytdlp", lambda: refreshed.append(1) or True)
    assert download.probe("https://www.youtube.com/watch?v=abcdefghijk")["title"] == "Works now"
    assert refreshed == [1]


def test_a_bot_check_is_not_retried_and_says_what_to_do(monkeypatch):
    monkeypatch.setattr(download.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        [], 1, "", "ERROR: [youtube] x: Sign in to confirm you're not a bot"))
    monkeypatch.setattr(download, "_refresh_ytdlp", lambda: pytest.fail("not an old-yt-dlp failure"))
    with pytest.raises(RuntimeError, match="Upload Video"):
        download.probe("https://www.youtube.com/watch?v=abcdefghijk")
