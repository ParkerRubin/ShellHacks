# JARVIS

Voice-controlled camera assistant. Talk to it (ElevenLabs agent), it sees through the webcam (Gemini), and it acts on the computer: photos, video, zoom, OCR to clipboard, screen help, web search, notes, reports, and background watching.

## Run

```
pip install -r requirements.txt
python setup_agent.py --set-prompt   # one time: registers all tools on the agent
python jarvis.py
```

`.env` needs `ELEVENLABS_API_KEY` and `GEMINI_API_KEY`. Optional: `ELEVENLABS_AGENT_ID`, `GEMINI_MODEL`, `CAM_INDEX` (default 1), `CAM_RES` (default `native`, same as robot.py), `CAM_BACKEND` (auto, dshow, msmf), `HALF_DUPLEX` (1 = mic off while JARVIS talks; set 0 with headphones), `AUTONOMY` (off, aware, proactive; default aware), `GLANCE_EVERY` (default 30s), `SPEAK_GAP` (min seconds between unprompted remarks, default 120), `WATCH_EVERY` (seconds), `SERVO_ENABLED=1` + `SERVO_PORT` once the Arduino is back.

Everything from a run is saved to `captures/<date_time>/`: photos, videos, screenshots, `notes.md`, `report.html`.

## Window

Drag it to any size or shape. `SPACE` mute mic / wake JARVIS, `A` cycle autonomy (off, aware, proactive), `C` follow me (auto-framing), `F` fullscreen, `M` fit (whole image) or fill (crop to fill), `T` pin on top, `P` photo, `R` record, `+`/`-` zoom, arrows pan, `0` reset, `H` help, `ESC` quit. All of these also work by voice.

## Tools

If `setup_agent.py` fails, add each of these by hand in the agent's Tools tab: type **Client**, exact name, **Wait for response on**, parameters and descriptions from `tools.json`.

| Tool | Parameters |
|---|---|
| `look` | `question` |
| `take_photo` | `label` |
| `start_recording` | `max_seconds` |
| `stop_recording` | none |
| `zoom` | `target`, `direction`, `level` |
| `pan` | `direction` (required) |
| `set_window` | `mode` (required), `width`, `height` |
| `read_text` | `then` |
| `look_at_screen` | `question` |
| `save_note` | `text` (required) |
| `search_web` | `query` (required) |
| `open_item` | `what` (required) |
| `make_report` | `title`, `purpose` |
| `watch_for` | `target` (required) |
| `follow_me` | `on` (required) |
| `sleep` | none |
| `set_autonomy` | `level` (required) |

Try saying: "zoom in on the label", "what brand is this", "take a photo of this, call it receipt", "record for 10 seconds", "copy the text on this page", "what's this error on my screen", "find where to buy this", "tell me when someone walks in", "make a report for an insurance claim", "go full screen", "follow me", "go to sleep", "be more proactive", "what have I been doing?".
