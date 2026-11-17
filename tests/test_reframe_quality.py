"""Speed changes must not visibly degrade the picture: compose() is compared against slow,
high-quality references computed independently here."""
import cv2
import numpy as np

from clippy.reframe import OUT_H, OUT_W, Shot, compose, fit_geometry


def natural_frame(w=1920, h=1080):
    """Gradients + soft shapes + edges + mild noise — closer to footage than a checkerboard."""
    rng = np.random.default_rng(1)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([x / w * 200, y / h * 180, (x + y) / (w + h) * 160], axis=-1).astype(np.uint8)
    for _ in range(25):
        cx, cy, r = rng.integers(0, w), rng.integers(0, h), rng.integers(20, 160)
        cv2.circle(img, (int(cx), int(cy)), int(r), rng.integers(0, 255, 3).tolist(), -1, cv2.LINE_AA)
    cv2.putText(img, "CLIPPY 1234", (500, 560), cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 8, cv2.LINE_AA)
    img = cv2.GaussianBlur(img, (0, 0), 1.2).astype(np.float32) + rng.normal(0, 3, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def psnr(a, b):
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return 99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def test_crop_upscale_looks_like_lanczos():
    frame = natural_frame()
    shot = Shot(0, 10, layout="crop", cx=np.full(10, 960.0), cy=540.0, fw=200.0)
    out = compose(frame, shot, 0, 1.0)
    cw = 1080 * 9 / 16
    ref = cv2.resize(frame[:, int(960 - cw / 2): int(960 - cw / 2) + int(cw)], (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
    assert out.shape == (OUT_H, OUT_W, 3)
    assert psnr(out, ref) >= 35.0


def test_fit_background_looks_like_full_res_blur():
    frame = natural_frame()
    out = compose(frame, Shot(0, 10, layout="fit"), 0, 1.0)
    fh, top = fit_geometry(1920, 1080)
    # reference: cover-crop to 9:16, upscale, heavy blur at full resolution, darken to 55 %
    cw = int(1080 * 9 / 16)
    bg = cv2.resize(frame[:, (1920 - cw) // 2: (1920 - cw) // 2 + cw], (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
    bg = (cv2.GaussianBlur(bg, (0, 0), 24).astype(np.float32) * 0.55).astype(np.uint8)
    above = slice(0, top - 40)                      # background strip above the foreground
    assert psnr(out[above], bg[above]) >= 28.0
    fg_ref = cv2.resize(frame, (OUT_W, fh), interpolation=cv2.INTER_AREA)
    assert psnr(out[top: top + fh], fg_ref) >= 40.0
