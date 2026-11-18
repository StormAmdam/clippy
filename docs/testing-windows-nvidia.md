# Testing the Windows app on a PC with an NVIDIA graphics card

GitHub's Windows test machines have no graphics card, so these parts of Clippy can only be checked on a real PC:
speech-to-text on the graphics card ("NVIDIA acceleration"), the AI engine's graphics-card version, and video
encoding on the graphics card (NVENC). Everything else (the installer, updating, making a clip on the processor,
start at login, notifications, folders with letters like ö) is already tested automatically on every change.

It takes about an hour, most of it waiting for downloads. Write down what you see at each step, especially anything
marked **Note:**. If something goes wrong, take a screenshot (Windows key + Shift + S) and keep the two log files
listed at the end.

## Get the test version

1. On Windows, open the latest test build:
   [github.com/StormAmdam/clippy/actions/workflows/windows-app.yml](https://github.com/StormAmdam/clippy/actions/workflows/windows-app.yml?query=branch%3Awindows-app).
   Click the top run with a green tick.
2. Sign in to GitHub if it asks (downloads there need an account).
3. Scroll down to **Artifacts** and click **Clippy-windows-0.1.0-dev.…** (about 360 MB). It downloads as a zip.
4. Open the zip and drag **Clippy-Setup-0.1.0-dev.…-win64.exe** out to your Desktop.

## Before you start

- **Graphics driver.** Open Task Manager (Ctrl+Shift+Esc) → Performance → GPU. Under the graph it shows the card's
  name and its driver version. **Note:** the card name and driver version. A driver from 2023 or newer is needed
  (version 527 or higher).
- **Free space.** About 25 GB on the C: drive. Clippy picks an AI model that fits your PC; the biggest is 17.7 GB.
- **A test video.** A 5–10 minute YouTube video where someone talks, for example an interview or a podcast clip.

## 1. Install (or update over the Clippy you have)

1. If Clippy is already installed on this Windows, keep it, with its models and shorts: the new installer updates it,
   and that's part of the test. Close its window first.
2. Run **Clippy-Setup-…-win64.exe**. If Windows says **"Windows protected your PC"**, click **More info**, then
   **Run anyway**.
3. Clippy opens in its own window.

**Note:** if you updated: are your earlier shorts (**Library**) and AI models (**AI & Tools**) still there? Did the
installer say anything unusual?

## 2. Set up everything

1. Go to **AI & Tools** and press **Set Up Everything**. It downloads the video tools, the speech model, the NVIDIA
   part and an AI model. This is the long wait.
2. When it's done, look at the parts:
   - **NVIDIA acceleration** should say **"Whisper runs on your NVIDIA card"**. This part only appears when Clippy
     sees an NVIDIA card.
   - **AI engine** should say **"llama.cpp b…, runs on your NVIDIA graphics card"**.

3. Go to **Settings**. Under **AI that picks the clips** it should say **Using Qwen… on Built-in AI**, not a model from
   another AI app you have (like Ollama).

**Note:** what do those lines say? If anything failed, copy the error text. If the AI engine says "runs on your
processor", press its remove button, download it again, and note what it says then. If you already had a model
downloaded, the AI engine may say it "downloads by itself on the next video": that's fine, or press its Download
button.

## 3. Make clips

1. Go to **Make Clips**, paste the YouTube link, and press **Make Clips**. (Clippy should have opened in its own
   window, not as a tab in your browser.)
2. Keep Task Manager open on Performance → GPU while it works.
3. Watch the progress text in Clippy:
   - while transcribing it should say **"Transcribing on CUDA…"** (CUDA means the graphics card). "Transcribing on
     CPU…" means the graphics card wasn't used.
   - during **"AI is watching the video for the best moments…"** the GPU's memory use in Task Manager should go up.
   - during **"Rendering…"**, Task Manager's GPU page should show activity in the **Video Encode** graph (you may
     have to click a graph's title and pick "Video Encode").

If YouTube answers **"Sign in to confirm you're not a bot"**, wait a few minutes and press Make Clips again: YouTube
sometimes limits a home connection for a while. Any other error: take a screenshot.

**Note:** how long did the whole video take? Did it say CUDA or CPU while transcribing? Did Video Encode show
activity while rendering? Do the finished shorts play properly, with captions and emojis?

## 4. Ending Clippy ends the AI as well

1. Start making clips again (a different video, or the same one with other settings).
2. While it says **"AI is watching the video…"**, open Task Manager → **Details**. You'll see **llama-server.exe**
   (the AI) and **pythonw.exe** (Clippy).
3. Right-click **pythonw.exe** → **End task**.
4. Within a few seconds, **llama-server.exe** should disappear from the list too, and the GPU memory in the
   Performance tab should drop back down.

**Note:** did llama-server.exe disappear by itself?

## 5. Start at login, notifications and Quit

1. Open Clippy again from the Start menu. Go to **Settings** and turn on **Start Clippy when you log in**.
2. Restart the PC and log in. Don't open anything. Open Task Manager → Details: **pythonw.exe** should be running.
3. Open Clippy from the Start menu. The window should open quickly.
4. Go to **Autopilot**, create a channel (any topic), and press **Run**. When it finishes, a Windows notification
   should pop up: **"N new shorts for … are waiting for your review"**, from **Clippy**. Click it.
5. Close Clippy's window. Wait a minute: **pythonw.exe** should still be running (Start at login keeps it going).
6. Open Clippy again → **Settings** → **Quit Clippy** → **Quit**. Within a few seconds pythonw.exe and
   llama-server.exe should be gone from Task Manager.

**Note:** did Clippy start by itself after the restart? Did the notification appear, and did it say "Clippy"? What
happened when you clicked it? Did Quit Clippy stop it?

## 6. Uninstall

Copy the two log files (see below) somewhere safe first, for example a USB stick.

1. Open Windows Settings → Apps → Installed apps → **Clippy** → Uninstall. Answer **Yes** when it asks to keep your
   shorts.
2. Check that your shorts are in your **Videos\Clippy** folder, that the folder
   `%LOCALAPPDATA%\Programs\Clippy` is gone (paste that into File Explorer's address bar), and that Task Manager →
   **Startup apps** no longer lists Clippy.

**Note:** anything left behind?

## What to send

- your notes from each step
- screenshots of **AI & Tools**, and of any error
- these two files, from the Clippy folder (paste `%LOCALAPPDATA%\Programs\Clippy\data` into File Explorer's
  address bar), copied **before** uninstalling:
  - `clippy.log`: what Clippy itself did
  - `engine.log`: what the AI engine did (whether it found the graphics card: look for "CUDA0")
