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

`.env` needs `ELEVENLABS_API_KEY` and `GEMINI_API_KEY`. Optional: `ELEVENLABS_AGENT_ID`, `GEMINI_MODEL`, `CAM_INDEX` (default 1), `CAM_RES` (default `native`), `CAM_BACKEND` (auto, dshow, msmf), `HALF_DUPLEX` (1 = mic off while JARVIS talks; set 0 with headphones), `AUTONOMY` (off, aware, proactive; default aware), `GLANCE_EVERY` (default 90s, skipped when nothing changed), `AUTO_BUDGET` (max background Gemini calls per run, default 25), `GEMINI_FALLBACKS` (models to fall back to when one hits its quota), `SPEAK_GAP` (min seconds between unprompted remarks, default 120), `WATCH_EVERY` (seconds), `FACE_MIN` (smallest face that counts, as a share of frame height, default 0.10; raise it if background people still get picked up), `LOCK_HOLD` (seconds the lock survives you turning away, default 1.5), `SERVO_PORT` (default auto), `SERVO_GAIN` (default 0.5; higher = snappier, lower = calmer), `SERVO_LEAD` (seconds to aim ahead of you when you move, default 0.08), `CAM_HFOV` (camera field of view, default 60), `CAM_LATENCY` (default 0.07s), `AIM_Y` (where your eyes sit vertically, default 0.45), `SERVO_INVERT_PAN` / `SERVO_INVERT_TILT`, `SERVO_ENABLED=0` to skip the Arduino.

Everything from a run is saved to `captures/<date_time>/`: photos, videos, screenshots, `notes.md`, `report.html`.

## Window and controls

A clickable control bar is always on screen: zoom out, zoom level (click to reset), zoom in, Photo, Rec, Follow, Mic, autonomy, Fit/Fill, Full. Mouse wheel zooms toward the cursor, and dragging pans when zoomed. Drag the window to any size or shape.

Right-drag a box to track an object, right-click to stop.

Keys: left/right arrows turn the servo head by hand (auto-follow resumes 4s after your last press), `X` auto-follow off/on, `SPACE` mic mute / wake, `G` gestures, `A` autonomy, `C` follow me, `S` servo test, `F` fullscreen, `M` fit/fill, `T` pin on top, `P` photo, `R` record, `+`/`-` zoom, up/down arrows pan the zoomed view (left/right too if no servo is connected), `0` reset, `ESC` quit.

## Servo head

Upload `jarvis_servo/jarvis_servo.ino` with the Arduino IDE (pan signal on pin 9, tilt on pin 10). On power-up it wiggles once so you know it's alive. `jarvis.py` finds the Arduino automatically, and the HUD shows `SERVO:COMx` when connected. Close the Arduino IDE's Serial Monitor first, since only one program can hold the port. The head is pan-only (left and right). The first time it sees you, it nudges 8° to measure which way it turns and saves that to `models/servo_dirs.json`, so a backwards-mounted servo never runs away. Press `K` to recalibrate after remounting. `SERVO_INVERT_PAN=1` in `.env` skips calibration and forces the direction. Two servos on the Arduino's 5V pin often brown out, so an external 5V supply (grounds connected) is the fix if they jitter or don't move.

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

## Memory and positivity

JARVIS combines OpenCV face tracking, Arduino servo control, Gemini's `look` tool,
and an ElevenLabs voice agent. The optional MongoDB memory path adds encrypted
conversation history, consented face recognition, recall, and offline recovery.

#### Setup

Use Python 3.11 or later. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # Only on first setup; preserve an existing .env
python scripts/gen_key.py
```

Put the generated key in `ENCRYPTION_KEY` in `.env`. Keep it for future runs and
back it up securely: replacing it makes existing encrypted data unreadable.
Set `GEMINI_API_KEY` and `ELEVENLABS_API_KEY`. The audio interface may require
PyAudio and OS audio dependencies (`pip install 'elevenlabs[pyaudio]'`).

For memory, set `MEMORY_ENABLED=true`. Without an Atlas URI, encrypted memory
works locally in `data/fallback.sqlite3`. A missing/invalid encryption key disables
memory and `jarvis.py` prints `Memory: off`; everything else keeps working.
`MEMORY_ENABLED=false` bypasses all memory initialization. The `recall`,
`remember_me` and `forget_me` tools are always registered (see `tools.json`);
with memory off they answer that memory is disabled. `jarvis.py` downloads the
YuNet and SFace face models into `models/` the first time memory is on.

Run the app as usual with `python jarvis.py` (after `python setup_agent.py
--set-prompt`, which registers the memory tools and their prompt on the agent).

The existing `look` tool sends a full camera frame to Gemini. Memory's face
recognition runs locally; it stores no images.

#### Atlas setup

1. Create an Atlas cluster and a database user with access to your chosen DB.
2. Add your machine's IP to Atlas Network Access. Set `MONGODB_ATLAS_URI` to its
   `mongodb+srv://...` connection string and `MONGODB_DB=jarvis_dev` (or `jarvis_demo`).
3. Verify your account's embedding model, then provision the database:

```bash
python -m scripts.check_embeddings
python -m scripts.provision
```

`gemini-embedding-001` with 768 dimensions was verified against the configured
Gemini account during implementation on September 27, 2026. Re-run the check for
your account before provisioning. Leave `EMBEDDING_MODEL` empty to disable
embeddings. The original vision integration still uses `google-generativeai`;
new embeddings use `google-genai`.

Provisioning creates application-compatible `$jsonSchema` validators, a TTL index,
timeline/profile/face indexes, `interactions_vec` Vector Search, and
`interactions_text` Atlas Search. If search-index creation is unavailable, the
script prints JSON definitions for the Atlas UI. Wait for indexes to become READY.
Do not mix models or dimensions in an existing vector index; use a new database
or explicitly re-embed old records when changing models.

Configure the three client tools in your ElevenLabs dashboard using
[the agent prompt and tool definitions](docs/elevenlabs-agent-prompt.md).
Registration in Python alone does not configure the hosted agent.

#### Recognition and consent

```bash
python -m scripts.fetch_models
```

This downloads OpenCV Zoo's YuNet and SFace models to the ignored `models/`
directory. YuNet provides landmarks for SFace alignment. Without these files,
storage and recall still work, but enrollment is unavailable.

The agent must explain the data being saved and ask for explicit consent before
calling `remember_me(confirmed=true)`. Enrollment saves an encrypted face
signature and profile. Subsequent exchanges are associated with that profile;
earlier anonymous exchanges are never relinked. Recognition requires two
agreeing matches; naming uses a higher confidence threshold. Leaving the camera
clears identity. Face matching still requires real-world accuracy testing.

`forget_me` immediately removes the local profile, signature, and associated
history. If Atlas is configured, the response explicitly says remote deletion
is queued. A durable tombstone blocks late writes and replays the deletion after
any in-flight upload. Do not remove the local database while deletion is pending.
An operator can delete by the opaque profile ID:

```bash
python -m scripts.delete_user USER_PROFILE_UUID
```

#### What is persisted

- Consented transcripts, replies, Gemini results, names, preferences, and face
  vectors are inside authenticated Fernet ciphertext. Logs from the memory package
  contain operation/type information, not transcript text or credentials.
- Anonymous exchanges store **only fixed-vocabulary topic tags**, not scrubbed
  free text. Anonymous recall is scoped to the current voice session.
- Searchable topics come from a fixed non-personal vocabulary. Embeddings also
  use only these roughly two dozen tags, so recall is topic-level. This is not
  general semantic search over conversation text.
- Sensitive exchanges are not embedded. Personal recall requires personalization
  consent, filters by user, and rechecks identity after retrieval.
- An encrypted SQLite mirror and transactional outbox are maintained even when
  Atlas is online. UUID upserts make replay idempotent. This is a single-robot
  design, not a multi-device synchronization protocol.
- Interactions expire after 90 days; inactive profiles and signatures after 180
  days by default. Local cleanup runs hourly; Atlas uses interaction TTL indexes.
- Queued callbacks are in memory until committed by the worker. Abrupt process
  termination or a full 200-item queue can lose pending exchanges; overflow logs
  a warning and drops the oldest. Graceful shutdown drains within a bounded wait.

The original robot still prints conversation text to its terminal. Avoid retaining
terminal recordings if transcript privacy is required.

#### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MEMORY_ENABLED` | `true` in code; example uses `false` | Memory switch |
| `ENCRYPTION_KEY` | required when enabled | Fernet key |
| `MONGODB_ATLAS_URI` | empty | Empty means local-only |
| `MONGODB_DB` | `jarvis` | Database/environment |
| `LOCAL_FALLBACK_PATH` | `./data/fallback.sqlite3` | Encrypted local mirror/outbox |
| `RETENTION_DAYS` | `90` | Interaction lifetime |
| `PROFILE_RETENTION_DAYS` | `180` | Profile inactivity lifetime |
| `EMBEDDING_MODEL` | empty | Optional verified Gemini model |
| `EMBEDDING_DIM` | `768` | Must match model output and vector index |
| `FACE_DETECTION_MODEL` | `models/face_detection_yunet_2023mar.onnx` | Landmark model |
| `FACE_RECOGNITION_MODEL` | `models/face_recognition_sface_2021dec.onnx` | SFace model |
| `FACE_MATCH_THRESHOLD` | `0.363` | Recognition cosine threshold |
| `FACE_GREET_THRESHOLD` | `0.5` | Threshold for returning a saved name |

#### Tests and demos

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m scripts.smoke
python -m scripts.demo_memory                # Disposable local data; no cloud calls
python -m scripts.benchmark_memory           # Disposable 10,000-record local benchmark
python -m scripts.demo_memory --atlas        # Seeds/deletes demo data in the configured DB
```

Live Atlas tests require a **separate** `MONGODB_ATLAS_URI_TEST` environment
variable. They create and remove a uniquely named `jarvis_test_*` database:

```bash
python -m pytest -m atlas -q
```

No Atlas URI was available during implementation, so live validator/search/TTL
behavior remains unverified. The opt-in test covers validator rejection, TTL
configuration, idempotent replay, and deletion. Search quality/index readiness
and the 500 ms network target require the Atlas demo; local tests enforce the
recall caller's timeout even when the backend hangs.

Before the booth demo, test voice, `look`, face re-entry/deletion, and servo/frame
rate with memory enabled, offline, and disabled. Atlas Charts and its screenshot
are still manual setup; see [sponsor notes](docs/mongodb-prize.md).

Implementation details and explicit differences from the draft spec are in
[the implementation notes](docs/mongodb-implementation.md).

#### Positivity MVP (disabled by default)

The optional `jarvis/positivity/` package implements notice, opt-out, per-face
encouragement, draft remark validation and RAM-only expression proxy samples.
It works with memory disabled and preserves the existing pan calculation.

Keep `POSITIVITY_ENABLED=false` until the hardware voice spike and human review.
To exercise it later, configure `POSITIVITY_VOICE_ID` to match your ElevenLabs
agent, install `sounddevice`/OS audio support, and set `POSITIVITY_ENABLED=true`.
`POSITIVITY_PRIVACY_MODE=crop` sends only a <=256 px face crop to Gemini after
notice plus a two-second opt-out window; `tags_only` sends fixed local tags and a
bank draft instead. Neither mode persists images, remarks or samples. The existing
user-triggered `look` tool still sends its full frame as documented above.

The draft lexicon and bank have **not** undergone human or diverse-panel review.
Option A separate TTS playback is **unverified** alongside the live agent. Run
`python -m scripts.voice_spike --option all` on the demo machine to record A/B/C
results. See [implementation and deviations](docs/positivity-implementation.md)
and [voice spike status](docs/positivity-voice-spike.md). Captions, public-demo
privacy signage, live latency/FPS/soak checks and human review remain unfinished.
