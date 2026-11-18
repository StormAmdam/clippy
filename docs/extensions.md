# Making a Clippy extension

An extension adds things to Clippy: caption styles, kinds of Top countdown, sound effects, Find Videos topics, or
code that runs after a short is made. People install extensions on Clippy's **Extensions** page, from the community
list or from a link to your GitHub repository or a .zip file.

An extension is a folder with an `extension.json` in it, plus any files it uses (fonts, sounds, preview pictures,
code). The [community/](../community) folder has four complete examples to copy from.

## Try it out

1. Make a folder named after your extension's id inside Clippy's `extensions` folder (the Extensions page shows
   where that is), for example `extensions/neon-captions/`.
2. Put your `extension.json` in it.
3. Open the Extensions page (or reload it). Your extension is listed and switched on (one with code waits until you
   say you trust it). Anything wrong with it is shown in red there.

## extension.json

```json
{
  "id": "neon-captions",
  "name": "Neon captions",
  "version": "1.0.0",
  "author": "Your name",
  "description": "One sentence about what it adds.",
  "homepage": "https://github.com/you/neon-captions"
}
```

`id` is lowercase letters, digits and dashes, and must match the folder's name. `name` is required; the rest is
optional but helps people decide. Then add any of the sections below.

### Caption styles

```json
"caption_styles": [
  {
    "id": "neon",
    "name": "Neon",
    "about": "Glowing, two words at a time",
    "base": "hormozi",
    "font": "fonts/MyFont.ttf",
    "size": 110,
    "upper": true,
    "words": 2,
    "stroke": 10,
    "shadow": 14,
    "active": "color",
    "tilt": 2,
    "pop": 1.2,
    "rest": 1.05,
    "emph_always": true,
    "title": "box",
    "preview": "neon.jpg"
  }
]
```

Start from a built-in look with `base` (`beast`, `hormozi`, `box` or `clean`) and change only what you need:

| Key | What it does |
|---|---|
| `font` | a .ttf or .otf file in your extension (fonts must allow being shared: SIL Open Font License or similar) |
| `size` | text size in pixels on the 1080×1920 video |
| `upper` | `true` for CAPITAL LETTERS |
| `words` | words on screen at once |
| `stroke`, `shadow` | outline and shadow thickness (0 for none) |
| `active` | how the word being said stands out: `color` or `box` |
| `tilt` | degrees the caption tilts back and forth (0 for none) |
| `pop`, `rest` | how big the spoken word pops, and its size after the pop (1.0 is normal) |
| `emph_always` | colour the AI's key words even when they aren't being said |
| `title` | look of the hook title: `beast` (comic) or `box` |

`preview` is a 360×640 picture shown on the Make Clips page. Draw one with Clippy's own renderer:
`python tools/style_preview.py extensions/neon-captions`.

### Countdown themes

```json
"countdown_themes": [
  {
    "id": "fails",
    "name": "Biggest fails",
    "emoji": "🤦",
    "title": "Top {n} Biggest Fails",
    "word": "embarrassing",
    "look_for": "the biggest fails: plans going wrong, mistakes, things breaking at the worst moment",
    "hashtags": ["#fail", "#fails"],
    "laughter": true
  }
]
```

`look_for` tells the AI what to find; write it like you'd explain it to a video editor. `title` is the countdown's
on-screen title (`{n}` becomes the number of moments). `word` finishes "score how ___ it is". `laughter: true` gives
extra points to moments where people laugh.

### Sound effects

```json
"sounds": {"whoosh": ["sounds/whoosh1.wav", "sounds/whoosh2.wav"], "pop": ["sounds/pop.wav"], "impact": ["sounds/hit.wav"]}
```

Clippy plays these instead of its own for transitions (whoosh), key words and emojis (pop) and the start (impact).
Use sounds you made or that are free to share (CC0). Short files work best: whoosh under a second, pop and impact
under half a second.

### Find Videos topics

```json
"finder_topics": {"chess": ["chess blunders", "chess podcast", "chess tournament highlights"]}
```

Each topic becomes a choice on Find Videos, searching YouTube for these phrases.

### Code

```json
"code": "main.py"
```

Clippy calls these functions in `main.py` if they exist:

```python
def clip_rendered(path, clip, video, **_):
    """After each short is made. path: the finished .mp4 (a pathlib.Path). clip: its title, caption, hashtags,
    duration and so on. video: the source video's title, id, uploader and so on."""


def video_done(result, folder, **_):
    """After a whole video is done. result: everything about it, with every short in result["clips"].
    folder: that video's folder in Clippy's output folder."""
```

Keep the `**_`: Clippy may pass more details later. If your code raises an error, Clippy writes it to the job's log
and carries on. An extension with code is switched off until the person says they trust it, and again after each
update. Never do anything a person wouldn't expect from your description.

## Sharing it

- **From your own GitHub repository:** people paste its link on the Extensions page. If the extension is in a
  subfolder, link to that folder (`https://github.com/you/repo/tree/main/neon-captions`).
- **In the community list:** open a pull request that adds your folder to [community/](../community) and runs
  `python tools/community_index.py` to update the list. Extensions are checked before they're listed, so keep code
  short and readable, and don't fetch or run anything from the internet.
