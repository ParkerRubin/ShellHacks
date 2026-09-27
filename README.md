# JARVIS

Voice-controlled camera assistant. Talk to it (ElevenLabs agent), it sees through the webcam (Gemini), and it acts on the computer: photos, video, zoom, OCR to clipboard, screen help, web search, notes, reports, and background watching.

## Run

```
pip uninstall -y google-generativeai          # old, deprecated Gemini SDK (replaced by google-genai)
pip install --upgrade -r requirements.txt     # OpenCV 5, google-genai, current ElevenLabs
python setup_agent.py --set-prompt            # registers all tools on the agent
python jarvis.py
```

## Local vision (OpenCV Zoo, no API calls)

Models live in `models/` and download automatically if missing. Wrapper code in `zoo/` is from [opencv_zoo](https://github.com/opencv/opencv_zoo) (Apache-2.0).

- **Faces:** YuNet 2026. Handles tilted heads, dim rooms, and distance far better than Haar cascades (which OpenCV 5 dropped from the main package anyway).
- **Hands and gestures:** MediaPipe palm detector + 21-point hand landmarks. Thumbs up = photo after a 3-2-1 countdown, peace sign = start/stop recording, open palm = mute/unmute mic, thumbs down = reset zoom and tracking. Hold for about half a second. `G` toggles, `GESTURES=0` disables.
- **Object tracking:** VitTrack. Say "track the mug" (one Gemini call to find it), or right-drag a box around anything (free). The servo head and zoom follow it. Right-click or thumbs down to go back to faces.

`.env` needs `ELEVENLABS_API_KEY` and `GEMINI_API_KEY`. Optional: `ELEVENLABS_AGENT_ID`, `GEMINI_MODEL`, `CAM_INDEX` (default 1), `CAM_RES` (default `native`, same as robot.py), `CAM_BACKEND` (auto, dshow, msmf), `HALF_DUPLEX` (1 = mic off while JARVIS talks; set 0 with headphones), `AUTONOMY` (off, aware, proactive; default aware), `GLANCE_EVERY` (default 90s, skipped when nothing changed), `AUTO_BUDGET` (max background Gemini calls per run, default 25), `GEMINI_FALLBACKS` (models to fall back to when one hits its quota), `SPEAK_GAP` (min seconds between unprompted remarks, default 120), `WATCH_EVERY` (seconds), `FACE_MIN` (smallest face that counts, as a share of frame height, default 0.10; raise it if background people still get picked up), `LOCK_HOLD` (seconds the lock survives you turning away, default 1.5), `SERVO_PORT` (default auto), `SERVO_GAIN` (default 0.5; higher = snappier, lower = calmer), `SERVO_LEAD` (seconds to aim ahead of you when you move, default 0.08), `CAM_HFOV` (camera field of view, default 60), `CAM_LATENCY` (default 0.07s), `AIM_Y` (where your eyes sit vertically, default 0.45), `SERVO_INVERT_PAN` / `SERVO_INVERT_TILT`, `SERVO_ENABLED=0` to skip the Arduino.

Everything from a run is saved to `captures/<date_time>/`: photos, videos, screenshots, `notes.md`, `report.html`.

## Window and controls

A clickable control bar is always on screen: zoom out, zoom level (click to reset), zoom in, Photo, Rec, Follow, Mic, autonomy, Fit/Fill, Full. Mouse wheel zooms toward the cursor, and dragging pans when zoomed. Drag the window to any size or shape.

Right-drag a box to track an object, right-click to stop.

Keys: `SPACE` mic mute / wake, `G` gestures, `A` autonomy, `C` follow me, `S` servo test, `F` fullscreen, `M` fit/fill, `T` pin on top, `P` photo, `R` record, `+`/`-` zoom, arrows pan, `0` reset, `ESC` quit.

## Servo head

Upload `jarvis_servo/jarvis_servo.ino` with the Arduino IDE (pan signal on pin 9, tilt on pin 10). On power-up it wiggles once so you know it's alive. `jarvis.py` finds the Arduino automatically, and the HUD shows `SERVO:COMx` when connected. Close the Arduino IDE's Serial Monitor first, since only one program can hold the port. If it turns away from you, set `SERVO_INVERT_PAN=1` (or `SERVO_INVERT_TILT=1`) in `.env`. Two servos on the Arduino's 5V pin often brown out, so an external 5V supply (grounds connected) is the fix if they jitter or don't move.

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
| `turn_camera` | `direction` (required), `degrees` |
| `track_object` | `target` (required) |

Try saying: "zoom in on the label", "what brand is this", "take a photo of this, call it receipt", "record for 10 seconds", "copy the text on this page", "what's this error on my screen", "find where to buy this", "tell me when someone walks in", "make a report for an insurance claim", "go full screen", "follow me", "go to sleep", "be more proactive", "what have I been doing?".
