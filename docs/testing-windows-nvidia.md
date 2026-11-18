# Testing the Windows app on a PC with an NVIDIA graphics card

GitHub's Windows test machines have no graphics card, so these parts of Clippy can only be checked on a real PC:
speech-to-text on the graphics card ("NVIDIA acceleration"), the AI engine's graphics-card version, and video
encoding on the graphics card (NVENC). Everything else (the installer, updating, making a clip on the processor,
start at login, notifications, folders with letters like ö) is already tested automatically on every change.

It takes about an hour, most of it waiting for downloads. Write down what you see at each step, especially anything
marked **Note:**. If something goes wrong, the error text and the two log files listed at the end are the most
useful things to send.

## Before you start

- **Graphics driver.** Open Task Manager (Ctrl+Shift+Esc) → Performance → GPU. Under the graph it shows the card's
  name and its driver version. **Note:** the card name and driver version. A driver from 2023 or newer is needed
  (version 527 or higher).
- **Free space.** About 15 GB.
- **A test video.** A 5–10 minute YouTube video where someone talks, for example an interview or a podcast clip.

## 1. Update over the Clippy you already have

1. Leave your current Clippy installed, with its downloaded models and shorts. Close its window.
2. Run the new **Clippy-Setup-…-win64.exe**.
3. Clippy opens. Go to **Library** and **AI & Tools**.

**Note:** are your earlier shorts and downloaded AI models still there? Did the installer say anything unusual?

## 2. NVIDIA acceleration (Whisper on the graphics card)

1. Go to **AI & Tools**. There should be a part called **NVIDIA acceleration**. It only appears when Clippy sees an
   NVIDIA card.
2. If it isn't installed yet, press its download button (about 1.5 GB). Wait until it says
   **"Whisper runs on your NVIDIA card"**.

**Note:** did the NVIDIA acceleration part appear? Did it install? If it failed, copy the error text.

## 3. The AI engine on the graphics card

1. On **AI & Tools**, look at the **AI engine** part. It should say
   **"llama.cpp b…, runs on your NVIDIA graphics card"**.
2. If it says "runs on your processor", press its remove button and download it again.

**Note:** what does the AI engine line say?

## 4. Make clips

1. Go to **Make Clips**, paste the YouTube link, and press **Make Clips**.
2. Keep Task Manager open on Performance → GPU while it works.
3. Watch the progress text in Clippy:
   - while transcribing it should say **"Transcribing on CUDA…"** (CUDA means the graphics card). "Transcribing on
     CPU…" means the graphics card wasn't used.
   - during **"AI is watching the video for the best moments…"** the GPU's memory use in Task Manager should go up.
   - during **"Rendering…"**, Task Manager's GPU page should show activity in the **Video Encode** graph (you may
     have to click a graph's title and pick "Video Encode").

**Note:** how long did the whole video take? Did it say CUDA or CPU while transcribing? Did Video Encode show
activity while rendering? Do the finished shorts play properly, with captions and emojis?

## 5. Ending Clippy ends the AI as well

1. Start making clips again (a different video, or the same one with other settings).
2. While it says **"AI is watching the video…"**, open Task Manager → **Details**. You'll see **llama-server.exe**
   (the AI) and **pythonw.exe** (Clippy).
3. Right-click **pythonw.exe** → **End task**.
4. Within a few seconds, **llama-server.exe** should disappear from the list too, and the GPU memory in the
   Performance tab should drop back down.

**Note:** did llama-server.exe disappear by itself?

## 6. Start at login and notifications

1. Go to **Settings** and turn on **Start Clippy when you log in**.
2. Restart the PC and log in. Don't open anything. Open Task Manager → Details: **pythonw.exe** should be running.
3. Open Clippy from the Start menu. The window should open quickly.
4. Go to **Autopilot**, create a channel (any topic), and press **Run**. When it finishes, a Windows notification
   should pop up: **"N new shorts for … are waiting for your review"**, from **Clippy**. Click it.

**Note:** did Clippy start by itself after the restart? Did the notification appear, and did it say "Clippy"? What
happened when you clicked it?

## 7. Uninstall

1. Open Windows Settings → Apps → Installed apps → **Clippy** → Uninstall. Answer **Yes** when it asks to keep your
   shorts.
2. Check that your shorts are in your **Videos\Clippy** folder, that the folder
   `%LOCALAPPDATA%\Programs\Clippy` is gone (paste that into File Explorer's address bar), and that Task Manager →
   **Startup apps** no longer lists Clippy.

**Note:** anything left behind?

## What to send

- your notes from each step
- screenshots of **AI & Tools**, and of any error
- these two files, from the Clippy folder (`%LOCALAPPDATA%\Programs\Clippy`), copied **before** uninstalling:
  - `data\clippy.log`: what Clippy itself did
  - `data\engine.log`: what the AI engine did (whether it found the graphics card: look for "CUDA0")
