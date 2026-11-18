"""A video that's already downloaded must re-render even when YouTube won't answer
(offline, rate-limited, or "Sign in to confirm you're not a bot")."""
import json

import pytest


class _Reached(Exception):
    pass


@pytest.fixture(autouse=True)
def _tools_present(monkeypatch):
    from clippy import pipeline
    monkeypatch.setattr(pipeline, "have_tools", lambda: [])     # these tests are about YouTube, not ffmpeg/yt-dlp


def _downloaded(out, vid="tzGLLFFhqeU", source="source.mp4"):
    d = out / vid
    d.mkdir(parents=True)
    (d / "info.json").write_text(json.dumps({"id": vid, "title": "Saved title", "duration": 61.0}))
    (d / source).write_bytes(b"x")
    return d


def _youtube_refuses(*a, **k):
    raise RuntimeError("yt-dlp could not read that link: ERROR: Sign in to confirm you're not a bot")


@pytest.mark.parametrize("url", ["https://www.youtube.com/watch?v=tzGLLFFhqeU", "https://youtu.be/tzGLLFFhqeU?t=4",
                                 "https://www.youtube.com/shorts/tzGLLFFhqeU", "https://m.youtube.com/watch?feature=x&v=tzGLLFFhqeU"])
def test_pipeline_uses_the_saved_info_when_youtube_refuses(tmp_output, monkeypatch, url):
    from clippy import config, pipeline
    _downloaded(config.output_root(config.load()))
    seen = {}

    def stop_at_download(u, info, workdir, *a, **k):
        seen.update(info=info, workdir=workdir)
        raise _Reached

    monkeypatch.setattr(pipeline, "probe", _youtube_refuses)
    monkeypatch.setattr(pipeline, "download", stop_at_download)
    with pytest.raises(_Reached):
        pipeline.run(url, log=lambda *a: None)
    assert seen["info"]["title"] == "Saved title"
    assert seen["workdir"].name == "tzGLLFFhqeU"


@pytest.mark.parametrize("setup", ["nothing", "only-a-half-finished-download", "info-without-video"])
def test_youtube_errors_still_show_when_there_is_no_saved_copy(tmp_output, monkeypatch, setup):
    from clippy import config, pipeline
    out = config.output_root(config.load())
    if setup == "only-a-half-finished-download":
        _downloaded(out, source="source.f298.mp4.part")
    elif setup == "info-without-video":
        _downloaded(out).joinpath("source.mp4").unlink()
    monkeypatch.setattr(pipeline, "probe", _youtube_refuses)
    with pytest.raises(RuntimeError, match="not a bot"):
        pipeline.run("https://www.youtube.com/watch?v=tzGLLFFhqeU", log=lambda *a: None)
