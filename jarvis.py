"""
JARVIS: voice-driven camera assistant that acts on your computer.
ElevenLabs Conversational AI (voice + tool calls) + Gemini (vision) + OpenCV (camera).

Window keys:
  Clickable control bar at the bottom. Mouse wheel zooms toward the cursor, drag pans when zoomed.
  Right-drag a box around anything to track it (right-click to stop). Gestures: thumbs up photo, peace record,
  open palm mic, thumbs down reset.
  SPACE mic mute / wake   A autonomy   G gestures   S servo test   C follow me (auto-framing)   F fullscreen   M fit/fill   T pin on top
  P photo   R record   + / - zoom   arrows pan   0 reset zoom   H help   ESC quit
The window can be dragged to any size or shape; the picture adapts.
"""
import os, re, sys, json, time, html, threading, subprocess, webbrowser, datetime, pathlib, urllib.parse, urllib.request
import warnings; warnings.filterwarnings("ignore")
import cv2
import numpy as np
from google import genai
from google.genai import types as gtypes
from collections import deque
from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation, ClientTools
from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface

# ------------------------------------------------------------------ config
load_dotenv()
AGENT_ID      = os.getenv("ELEVENLABS_AGENT_ID", "agent_0901m3g7etm0fcn8tfnew95me755")
VISION_MODEL  = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
CAM_INDEX     = int(os.getenv("CAM_INDEX", "1"))
CAM_RES       = os.getenv("CAM_RES", "native").lower()        # "native" = camera defaults, same as robot.py; or e.g. 1280x720
CAM_BACKEND   = os.getenv("CAM_BACKEND", "auto").lower()      # auto, dshow, msmf
HALF_DUPLEX   = os.getenv("HALF_DUPLEX", "1") == "1"          # mute mic while JARVIS talks (stops it hearing itself); 0 if on headphones
MAX_ZOOM      = 8.0
WATCH_EVERY   = float(os.getenv("WATCH_EVERY", "4"))      # seconds between watch checks
SERVO_ENABLED = os.getenv("SERVO_ENABLED", "1") == "1"        # tries to connect; runs fine without the Arduino
SERVO_PORT    = os.getenv("SERVO_PORT", "auto")                # "auto" finds the Arduino, or e.g. COM3
SERVO_KP      = float(os.getenv("SERVO_KP", "10"))             # tracking strength (degrees per update at full-frame error)
PAN_DIR       = -1 if os.getenv("SERVO_INVERT_PAN", "0") == "1" else 1    # flip if it turns away from you
TILT_DIR      = -1 if os.getenv("SERVO_INVERT_TILT", "0") == "1" else 1
GEMINI_FALLBACKS = [m.strip() for m in os.getenv("GEMINI_FALLBACKS", "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash").split(",") if m.strip()]
AUTO_BUDGET   = int(os.getenv("AUTO_BUDGET", "25"))            # max background Gemini calls per run (free tier is ~20/day/model)
GESTURES      = os.getenv("GESTURES", "1") == "1"              # hand gestures (local models, no API calls)
AUTONOMY      = os.getenv("AUTONOMY", "aware")                # off, aware (silent awareness), proactive (speaks up on its own)
GLANCE_EVERY  = float(os.getenv("GLANCE_EVERY", "90"))        # min seconds between background scene checks (skipped if nothing changed)
SPEAK_GAP     = float(os.getenv("SPEAK_GAP", "120"))          # minimum seconds between unprompted remarks
WIN           = "JARVIS"
IS_WIN        = sys.platform.startswith("win")

if not os.getenv("GEMINI_API_KEY"): sys.exit("GEMINI_API_KEY is missing from .env")
if not os.getenv("ELEVENLABS_API_KEY"): sys.exit("ELEVENLABS_API_KEY is missing from .env")
GEMINI = genai.Client(api_key=os.getenv("GEMINI_API_KEY"), http_options=gtypes.HttpOptions(timeout=30000))
client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

BASE    = pathlib.Path(__file__).resolve().parent
SESSION = BASE / "captures" / datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
SESSION.mkdir(parents=True, exist_ok=True)
NOTES   = SESSION / "notes.md"
REPORT  = SESSION / "report.html"

# ------------------------------------------------------------------ shared state
class State:
    lock = threading.Lock()
    raw = None            # latest full camera frame
    view = None           # latest zoomed frame (what photos/recordings/look use)
    zoom_t, cx_t, cy_t = 1.0, 0.5, 0.5   # zoom targets
    zoom, cx, cy = 1.0, 0.5, 0.5         # smoothed actual values
    fit_mode = "fit"
    fullscreen = False
    topmost = False
    window_cmds = []      # queued window changes, applied on the GUI thread
    fps = 30.0
    writer = None; rec_path = None; rec_start = 0.0; rec_stop_at = None
    status = ""; status_until = 0.0
    flash_until = 0.0
    cap_user = ("", 0.0); cap_agent = ("", 0.0)
    watch_target = None; watch_token = 0
    show_help_until = time.time() + 12
    log = []              # session entries for the report
    counters = {}
    faces = []            # normalized (x, y, w, h) boxes in the raw frame
    crop = (0.0, 0.0, 1.0, 1.0)   # current zoom crop, normalized
    follow = False        # auto-framing: zoom/pan tracks the main face
    last_face_t = 0.0
    mic_muted = False
    speaking_until = 0.0  # when JARVIS's queued audio finishes playing
    voice_on = False; want_voice = True
    last_user_t = 0.0     # last time the user spoke
    disp_map = (0, 0, 1, 1); buttons = []; bar_top = 10000; drag = None; rdrag = None
    face_target = None    # smoothed box of the person being tracked
    hands = []            # [(gesture, box_norm, landmarks_norm)]
    countdown_until = 0.0
    target = None         # smoothed box of the person being tracked
    close_hits = 0
    quit = False

S = State()
convo = None

def set_status(msg, secs=3.0):
    S.status, S.status_until = msg, time.time() + secs
    print(f"[status] {msg}")

def add_log(kind, **kw):
    entry = {"kind": kind, "time": datetime.datetime.now().strftime("%H:%M:%S"), **kw}
    S.log.append(entry)
    return entry

def next_path(kind, ext, label=""):
    S.counters[kind] = S.counters.get(kind, 0) + 1
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:40]
    return SESSION / f"{kind}_{S.counters[kind]:03d}{'_' + slug if slug else ''}{ext}"

def current_view():
    with S.lock:
        return None if S.view is None else S.view.copy()

def current_raw():
    with S.lock:
        return None if S.raw is None else S.raw.copy()

def arg(p, key, default=None):
    v = p.get(key) if isinstance(p, dict) else None
    return default if v is None or (isinstance(v, str) and not v.strip()) else v

def num(v, default=None):
    try: return float(v)
    except (TypeError, ValueError): return default

# ------------------------------------------------------------------ computer actions
def open_path(path):
    path = str(path)
    if IS_WIN: os.startfile(path)
    elif sys.platform == "darwin": subprocess.Popen(["open", path])
    else: subprocess.Popen(["xdg-open", path])

def copy_to_clipboard(text):
    if IS_WIN: subprocess.run("clip", input=text.encode("utf-16"), check=True, shell=True)
    elif sys.platform == "darwin": subprocess.run(["pbcopy"], input=text.encode(), check=True)
    else: subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)

def append_note(text):
    with open(NOTES, "a", encoding="utf-8") as f:
        f.write(f"- **{datetime.datetime.now():%H:%M:%S}** {text}\n")

# ------------------------------------------------------------------ gemini helpers
def _jpeg(img, max_side=1280):
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    if s < 1: img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()

class QuotaExhausted(Exception):
    pass

MODEL_CHAIN = [VISION_MODEL] + [m for m in GEMINI_FALLBACKS if m != VISION_MODEL]
_blocked = {}                       # model name -> blocked-until timestamp
GEM = {"calls": 0, "background": 0}

def check_models():
    """Drop fallback models this API key can't use (listing models doesn't cost quota)."""
    global MODEL_CHAIN
    try:
        ok = {m.name.split("/")[-1] for m in GEMINI.models.list() if "generateContent" in (m.supported_actions or [])}
        chain = [m for m in MODEL_CHAIN if m in ok]
        if VISION_MODEL not in ok: print(f"Warning: {VISION_MODEL} isn't available to this key")
        MODEL_CHAIN = chain or MODEL_CHAIN
    except Exception as e:
        print(f"Couldn't list Gemini models ({e})")
    print("Vision models:", " -> ".join(MODEL_CHAIN))

def vision_available():
    return any(_blocked.get(m, 0) <= time.time() for m in MODEL_CHAIN)

def gemini(prompt, img=None, max_tokens=1024, json_mode=False, images=None):
    jpg = lambda im, side=1280: gtypes.Part.from_bytes(data=_jpeg(im, side), mime_type="image/jpeg")
    parts = [prompt] + ([jpg(img)] if img is not None else [])
    for label, im in images or []:
        parts += [label, jpg(im, 768)]
    cfg = gtypes.GenerateContentConfig(max_output_tokens=max_tokens,       # thinking tokens count against this, keep it roomy
                                       response_mime_type="application/json" if json_mode else None)
    for name in MODEL_CHAIN:
        if _blocked.get(name, 0) > time.time(): continue
        try:
            r = GEMINI.models.generate_content(model=name, contents=parts, config=cfg)
            GEM["calls"] += 1
            return (r.text or "").strip()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "exhausted" in msg.lower():
                daily = "PerDay" in msg
                m = re.search(r"retry(?:Delay)?(?: in)?['\"]?[:\s]*['\"]?([\d.]+)s", msg)
                _blocked[name] = time.time() + (6 * 3600 if daily else (float(m.group(1)) + 1 if m else 60))
                print(f"[gemini] {name}: {'daily quota used up' if daily else 'rate limited'}, trying the next model")
                continue
            if "404" in msg or "not found" in msg.lower() or "not supported" in msg.lower():
                _blocked[name] = time.time() + 86400
                print(f"[gemini] {name} unavailable, trying the next model"); continue
            raise
    set_status("Gemini quota used up: vision paused", 10)
    raise QuotaExhausted("My vision allowance from Google is used up for now, so I can't see at the moment. "
                         "Turning on billing for the Gemini key fixes it.")

def gemini_json(prompt, img, max_tokens=1024):
    txt = gemini(prompt, img, max_tokens, json_mode=True)
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}

# ------------------------------------------------------------------ tools (called by the ElevenLabs agent)
TOOLS = {}
def tool(fn):
    def wrapper(params):
        params = params if isinstance(params, dict) else {}
        shown = {k: v for k, v in params.items() if k != "tool_call_id"}
        print(f">>> TOOL {fn.__name__} {shown}")
        try: out = fn(params)
        except QuotaExhausted as e: out = str(e)
        except Exception as e: out = f"{fn.__name__} failed: {e}"
        print(f"<<< {fn.__name__}: {str(out)[:200]}")
        return str(out)
    TOOLS[fn.__name__] = wrapper
    return fn

@tool
def look(p):
    frame = current_view()
    if frame is None: return "The camera isn't giving me a picture right now."
    q = arg(p, "question", "")
    set_status("Looking...", 4)
    prompt = ("You are the eyes of a voice assistant. Answer in 1 to 3 short spoken sentences, no markdown or lists. "
              "Be specific: brands, readable text, colors, counts. If you are unsure, say so. ")
    prompt += f"Question: {q}" if q else "Describe what is in front of the camera, focusing on the main subject."
    ans = gemini(prompt, frame) or "I couldn't make that out clearly."
    add_log("look", text=ans, question=q or "What do you see?")
    return ans

@tool
def take_photo(p):
    frame = current_view()
    if frame is None: return "The camera isn't giving me a picture right now."
    label = arg(p, "label", "")
    path = next_path("photo", ".jpg", label)
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    S.flash_until = time.time() + 0.25
    set_status(f"Saved {path.name}")
    add_log("photo", file=path.name, label=label, caption=None)     # captioned in one batch at report time
    return f"Photo saved as {path.name}."

def _start_recording(max_seconds=None):
    frame = current_view()
    if frame is None: return "The camera isn't giving me a picture right now."
    with S.lock:
        if S.writer is not None: return f"Already recording to {S.rec_path.name}."
        h, w = frame.shape[:2]
        path = next_path("video", ".mp4")
        fps = max(5.0, min(60.0, S.fps))
        writer = None
        for code in ("avc1", "mp4v"):                 # avc1 plays in browsers, mp4v is the fallback
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*code), fps, (w, h))
            if writer.isOpened(): break
        if not writer or not writer.isOpened(): return "I couldn't start the video writer."
        S.writer, S.rec_path, S.rec_start = writer, path, time.time()
        S.rec_stop_at = time.time() + max_seconds if max_seconds else None
    set_status(f"Recording {path.name}")
    return f"Recording started{f' for {int(max_seconds)} seconds' if max_seconds else ''}."

def _stop_recording():
    with S.lock:
        if S.writer is None: return "I'm not recording right now."
        S.writer.release()
        path, dur = S.rec_path, time.time() - S.rec_start
        S.writer, S.rec_path, S.rec_stop_at = None, None, None
    add_log("video", file=path.name, seconds=round(dur, 1))
    set_status(f"Saved {path.name}")
    return f"Recording saved as {path.name}, {dur:.0f} seconds long."

@tool
def start_recording(p): return _start_recording(num(arg(p, "max_seconds")))

@tool
def stop_recording(p): return _stop_recording()

@tool
def zoom(p):
    S.follow = False
    target, direction, level = arg(p, "target"), str(arg(p, "direction", "")).lower(), num(arg(p, "level"))
    if target:
        frame = current_raw()
        if frame is None: return "The camera isn't giving me a picture right now."
        set_status(f"Finding {target}...", 4)
        res = gemini_json(
            f'Find "{target}" in this image. Reply only with JSON: '
            '{"found": true or false, "box_2d": [ymin, xmin, ymax, xmax]} with coordinates normalized 0 to 1000.', frame)
        box = res.get("box_2d")
        if not res.get("found") or not box or len(box) != 4:
            return f"I couldn't find {target} in view."
        y0, x0, y1, x1 = [float(v) / 1000 for v in box]
        bw, bh = max(x1 - x0, 0.02), max(y1 - y0, 0.02)
        S.cx_t, S.cy_t = (x0 + x1) / 2, (y0 + y1) / 2
        S.zoom_t = max(1.0, min(MAX_ZOOM, 1 / (max(bw, bh) * 1.5)))
        return f"Zoomed onto {target} at {S.zoom_t:.1f}x."
    if direction in ("in", "out"):
        if direction == "out" and S.zoom_t <= 1.01:
            return "Already at the widest view."
        S.zoom_t = max(1.0, min(MAX_ZOOM, S.zoom_t * (1.6 if direction == "in" else 1 / 1.6)))
        if S.zoom_t <= 1.01: S.cx_t, S.cy_t = 0.5, 0.5
        return f"Zoom is now {S.zoom_t:.1f}x."
    if level is not None:
        S.zoom_t = max(1.0, min(MAX_ZOOM, level))
        if S.zoom_t <= 1.01: S.cx_t, S.cy_t = 0.5, 0.5
        return f"Zoom set to {S.zoom_t:.1f}x."
    return f"Zoom is {S.zoom_t:.1f}x."

@tool
def pan(p):
    S.follow = False
    d = str(arg(p, "direction", "center")).lower()
    step = 0.5 / S.zoom_t
    if d == "center": S.cx_t, S.cy_t = 0.5, 0.5
    elif d == "left": S.cx_t -= step
    elif d == "right": S.cx_t += step
    elif d == "up": S.cy_t -= step
    elif d == "down": S.cy_t += step
    else: return "Direction must be left, right, up, down, or center."
    S.cx_t, S.cy_t = min(max(S.cx_t, 0), 1), min(max(S.cy_t, 0), 1)
    return "Moved." if S.zoom_t > 1.01 else "Moved, though at 1x zoom there is nothing more to see that way. Zoom in first."

WINDOW_PRESETS = {"small": (640, 360), "large": (1600, 900), "wide": (1800, 520), "tall": (560, 960), "windowed": (1280, 720)}

@tool
def set_window(p):
    mode = str(arg(p, "mode", "")).lower()
    if mode in ("fit", "fill"):
        S.fit_mode = mode
        return f"Window mode set to {mode}."
    if mode == "custom":
        w, h = int(num(arg(p, "width"), 1280)), int(num(arg(p, "height"), 720))
        S.window_cmds.append(("size", (w, h)))
        return f"Window resized to {w} by {h}."
    if mode in ("fullscreen", "pin", "unpin") or mode in WINDOW_PRESETS:
        S.window_cmds.append((mode, WINDOW_PRESETS.get(mode)))
        return f"Window set to {mode}."
    return "Mode must be fullscreen, windowed, wide, tall, small, large, fit, fill, pin, unpin, or custom."

@tool
def read_text(p):
    frame = current_view()
    if frame is None: return "The camera isn't giving me a picture right now."
    then = str(arg(p, "then", "copy")).lower()
    set_status("Reading text...", 5)
    text = gemini("Transcribe all readable text in this image exactly, keeping line breaks. "
                  "Output only the text. If there is no readable text, output NONE.", frame, 2048)
    if not text or text.strip().upper() == "NONE": return "I don't see any readable text."
    add_log("text", text=text)
    words = len(text.split())
    if then == "say": return text[:600]
    if then == "save":
        append_note("Text read from camera:\n\n```\n" + text + "\n```")
        return f"Saved {words} words to your notes."
    copy_to_clipboard(text)
    set_status("Text copied to clipboard")
    return f"Copied {words} words to your clipboard. It starts: {text[:140]}"

@tool
def look_at_screen(p):
    from PIL import ImageGrab
    q = arg(p, "question", "")
    shot = cv2.cvtColor(np.array(ImageGrab.grab()), cv2.COLOR_RGB2BGR)
    path = next_path("screen", ".png")
    cv2.imwrite(str(path), shot)
    prompt = ("This is a screenshot of the user's computer. Answer in 1 to 3 short spoken sentences, no markdown. ")
    prompt += f"Question: {q}" if q else "Say what is on the screen and anything that needs attention."
    ans = gemini(prompt, shot, 1024) or "I couldn't make sense of the screen."
    add_log("screen", file=path.name, text=ans, question=q or "What's on my screen?")
    return ans

@tool
def save_note(p):
    text = arg(p, "text", "")
    if not text: return "What should I write down?"
    append_note(text); add_log("note", text=text)
    return "Noted."

@tool
def search_web(p):
    q = arg(p, "query", "")
    if not q: return "What should I search for?"
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(q))
    add_log("search", text=q)
    return f"Opened a search for {q}."

@tool
def open_item(p):
    what = str(arg(p, "what", "folder")).lower()
    def last(kind):
        for e in reversed(S.log):
            if e["kind"] == kind and e.get("file"): return SESSION / e["file"]
    target = {"folder": SESSION, "notes": NOTES, "report": REPORT,
              "last_photo": last("photo"), "last_video": last("video")}.get(what)
    if target is None or not pathlib.Path(target).exists():
        return f"There's no {what.replace('_', ' ')} yet."
    open_path(target)
    return f"Opened the {what.replace('_', ' ')}."

@tool
def make_report(p):
    title = arg(p, "title", "JARVIS Session Report")
    purpose = arg(p, "purpose", "general record")
    if not S.log and not NOTES.exists(): return "There's nothing in this session to report yet."
    photos = [e for e in S.log if e["kind"] == "photo" and e.get("caption") is None][-12:]
    images = []
    for e in photos:
        im = cv2.imread(str(SESSION / e["file"]))
        if im is not None: images.append((f"Photo {e['file']}:", im))
    facts = []
    for e in S.log:
        if e["kind"] == "photo": facts.append(f"[{e['time']}] Photo {e['file']} ({e.get('label') or 'no label'}): {e.get('caption') or ''}")
        elif e["kind"] == "video": facts.append(f"[{e['time']}] Video {e['file']}, {e['seconds']}s")
        elif e["kind"] in ("look", "screen"): facts.append(f"[{e['time']}] Asked '{e.get('question')}': {e['text']}")
        else: facts.append(f"[{e['time']}] {e['kind']}: {e.get('text', '')[:500]}")
    notes = NOTES.read_text(encoding="utf-8") if NOTES.exists() else ""
    set_status("Writing report...", 8)
    txt = gemini(f"You are writing a report whose purpose is: {purpose}. The photos are attached, each labeled with its file name. "
                 'Reply only with JSON: {"captions": {"<file name>": "one factual sentence: subject, condition, readable text"}, '
                 '"summary": "clear factual summary in short paragraphs, with a short list of key findings or next steps if useful"}. '
                 "Only use the photos and information below; do not invent details. Plain text inside the JSON, no markdown headers.\n\n"
                 + "\n".join(facts) + "\n\nNotes:\n" + notes, None, 4096, json_mode=True, images=images)
    m = re.search(r"\{.*\}", txt or "", re.S)
    res = json.loads(m.group(0)) if m else {}
    for e in photos: e["caption"] = (res.get("captions") or {}).get(e["file"], "")
    summary = res.get("summary") or "(summary unavailable)"
    esc = html.escape
    cards = []
    for e in S.log:
        if e["kind"] in ("photo", "screen") and e.get("file"):
            cap = e.get("caption") or e.get("text") or ""
            cards.append(f'<figure><a href="{esc(e["file"])}"><img src="{esc(e["file"])}"></a>'
                         f'<figcaption><b>{esc(e["time"])}</b> {esc(e.get("label") or "")}<br>{esc(cap)}</figcaption></figure>')
        elif e["kind"] == "video":
            cards.append(f'<figure><video src="{esc(e["file"])}" controls></video>'
                         f'<figcaption><b>{esc(e["time"])}</b> <a href="{esc(e["file"])}">{esc(e["file"])}</a> ({e["seconds"]}s)</figcaption></figure>')
    obs = "".join(f"<li><b>{esc(e['time'])}</b> {esc(e.get('question') or e['kind'])}: {esc(e.get('text', ''))}</li>"
                  for e in S.log if e["kind"] in ("look", "screen", "text", "note", "search"))
    REPORT.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1000px;margin:40px auto;padding:0 16px;color:#1a1a1a;background:#fafafa}}
h1{{margin-bottom:4px}}.meta{{color:#666}}.summary{{white-space:pre-wrap;background:#fff;border:1px solid #ddd;border-radius:8px;padding:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}figure{{margin:0;background:#fff;border:1px solid #ddd;border-radius:8px;overflow:hidden}}
img,video{{width:100%;display:block}}figcaption{{padding:10px;font-size:14px}}li{{margin:6px 0}}</style></head><body>
<h1>{esc(title)}</h1><div class="meta">{datetime.datetime.now():%B %d, %Y %I:%M %p} &middot; Purpose: {esc(purpose)} &middot; Folder: {esc(SESSION.name)}</div>
<h2>Summary</h2><div class="summary">{esc(summary)}</div>
<h2>Captures</h2><div class="grid">{''.join(cards) or '<p>No captures.</p>'}</div>
<h2>Observations and notes</h2><ul>{obs or '<li>None.</li>'}</ul></body></html>""", encoding="utf-8")
    open_path(REPORT)
    return "Report saved and opened. " + summary[:300]

def notify_agent(msg):
    c = convo
    print(f"[alert] {msg}")
    for name in ("send_user_message", "send_contextual_update"):
        fn = getattr(c, name, None)
        if fn:
            try: fn(msg); return
            except Exception as e: print(f"[alert] {name} failed: {e}")

PERSON_WORDS = ("person", "someone", "somebody", "anyone", "anybody", "people", "face", "human", "visitor",
                "man", "woman", "guy", "girl", "boy", "kid", "roommate", "friend")

def _thumb(frame):
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 48), interpolation=cv2.INTER_AREA).astype(np.int16)

def scene_changed(a, b, thresh=6.0):
    return a is None or b is None or float(np.abs(a - b).mean()) > thresh

def watch_loop(target, token):
    person = any(w in target.lower() for w in PERSON_WORDS)
    baseline = len(S.faces)                                   # "someone walks in" while you're sitting there = one more face
    last_thumb, last_check = None, 0.0
    while S.watch_token == token and not S.quit:
        frame = current_raw()
        if person:                                            # free: uses the local face detector, no API calls
            if len(S.faces) > baseline:
                S.watch_target = None
                name = take_photo({"label": f"watch {target}"})
                add_log("note", text=f"Watch alert: {target} appeared.")
                notify_agent(f"[Camera alert] {target} just appeared ({len(S.faces)} people in view now). {name} "
                             "Tell the user in one short sentence.")
                return
            baseline = min(baseline, len(S.faces))
            time.sleep(0.3); continue
        thumb = _thumb(frame) if frame is not None else None
        if frame is not None and scene_changed(last_thumb, thumb) and time.time() - last_check > max(WATCH_EVERY, 10):
            last_thumb, last_check = thumb, time.time()
            try:
                res = gemini_json(f'Is {target} clearly visible in this image? Reply only with JSON: '
                                  '{"present": true or false, "detail": "short description"}', frame, 512)
            except QuotaExhausted:
                notify_agent("[Camera alert] The vision quota ran out, so the watch has stopped. Tell the user in one sentence.")
                S.watch_target = None; return
            except Exception as e:
                res = {}; print(f"[watch] {e}")
            if res.get("present") and S.watch_token == token:
                S.watch_target = None
                name = take_photo({"label": f"watch {target}"})
                add_log("note", text=f"Watch alert: {target} appeared. {res.get('detail', '')}")
                notify_agent(f"[Camera alert] {target} just appeared: {res.get('detail', '')}. {name} "
                             "Tell the user in one short sentence.")
                return
        time.sleep(1)

@tool
def watch_for(p):
    target = str(arg(p, "target", "")).strip()
    if not target or target.lower() in ("stop", "none", "nothing", "cancel"):
        was = S.watch_target
        S.watch_target, S.watch_token = None, S.watch_token + 1
        return f"Stopped watching for {was}." if was else "I wasn't watching for anything."
    S.watch_target, S.watch_token = target, S.watch_token + 1
    threading.Thread(target=watch_loop, args=(target, S.watch_token), daemon=True).start()
    return f"Watching for {target}. I'll tell you when I see it."


@tool
def follow_me(p):
    on = str(arg(p, "on", "true")).lower() not in ("false", "off", "0", "no", "stop")
    S.follow = on
    if not on: S.zoom_t, S.cx_t, S.cy_t = 1.0, 0.5, 0.5
    return "Auto-framing on. I'll keep you centered." if on else "Auto-framing off."

@tool
def sleep(p):
    # mute after JARVIS finishes its short goodbye line
    def later():
        time.sleep(max(1.5, S.speaking_until - time.time() + 0.3)); S.mic_muted = True
        set_status("Mic muted. Press SPACE to wake me.", 6)
    threading.Thread(target=later, daemon=True).start()
    return "Going quiet. Say one short line like 'Standing by.' and nothing else."


# ------------------------------------------------------------------ autonomy
# Nothing here decides *what* to say. Local sensors (face detector) note events; a vision model looks at the
# scene plus recent context and decides whether a thoughtful assistant would speak. Rails only stop it from
# interrupting or talking too often.
class A:
    level = AUTONOMY if AUTONOMY in ("off", "aware", "proactive") else "aware"
    present = False; present_since = 0.0; absent_since = 0.0
    people = 0; people_since = 0.0
    last_think = 0.0; think_asap = False; last_scene = ""
    last_spoke = 0.0; last_ping = 0.0; last_thumb = None
    events = []           # (time, text)
    busy = False

def _ago(sec):
    sec = max(0, int(sec))
    return f"{sec // 60} min ago" if sec >= 60 else f"{sec}s ago"

def ctx(text):
    """Silent background note: the agent knows it but doesn't respond."""
    c = convo
    if c is None or not S.voice_on or A.level == "off": return
    try: c.send_contextual_update(text); print(f"[ctx] {text}")
    except Exception as e: print(f"[ctx] failed: {e}")

def say(text, gap=None):
    """Let the agent speak on its own, but never over the user or too often."""
    now, c = time.time(), convo
    gap = SPEAK_GAP if gap is None else gap
    if (A.level != "proactive" or c is None or not S.voice_on or S.mic_muted
            or now < S.speaking_until + 1.5 or now - S.last_user_t < 12 or now - A.last_spoke < gap):
        return False
    try:
        c.send_user_message(text); A.last_spoke = now; print(f"[proactive] {text}")
        return True
    except Exception as e:
        print(f"[proactive] failed: {e}"); return False

def event(text):
    A.events = (A.events + [(time.time(), text)])[-8:]
    ctx(f"[Presence] {text}")
    A.think_asap = True

def think(triggered_by_event):
    frame = current_raw()
    if frame is None: return
    now = time.time()
    events = "; ".join(f"{t} ({_ago(now - ts)})" for ts, t in A.events[-5:]) or "none"
    you, you_t = S.cap_user; me, me_t = S.cap_agent
    talk = (f'User last said "{you}" {_ago(now - you_t)}. ' if you else "User hasn't spoken yet. ") + \
           (f'JARVIS last said "{me}" {_ago(now - me_t)}.' if me else "")
    sitting = f"The user has been in front of the camera for {_ago(now - A.present_since).replace(' ago', '')}." if A.present else ""
    try:
        res = gemini_json(
            "You are the judgment of JARVIS, a warm, sharp desk assistant who sees through a webcam and talks out loud. "
            "Decide if JARVIS should say something unprompted right now, the way a thoughtful person sitting at the desk would. "
            "Good reasons: someone arrived or came back, a new person appeared, the user is showing or holding something up, "
            "something looks wrong or unsafe, they've been at it a long time, or a genuinely useful observation. "
            "Stay quiet when the scene is routine or unchanged, when the user seems focused, or when it would just be filler.\n"
            f'Previous observation: "{A.last_scene or "none"}"\nRecent events: {events}\n{talk}\n{sitting}\n'
            'Reply only with JSON: {"summary": "one sentence: who is there, what they are doing or holding", '
            '"speak": true or false, "say": "if speak, the short natural sentence or question JARVIS would say"}', frame)
    except QuotaExhausted:
        print("[think] vision quota used up, autonomy pausing"); return
    except Exception as e:
        print(f"[think] {e}"); return
    summary = (res.get("summary") or "").strip()
    if summary and summary != A.last_scene:
        A.last_scene = summary
        add_log("scene", text=summary)
        ctx(f"[Scene {datetime.datetime.now():%H:%M}] {summary}")
    if res.get("speak") and res.get("say"):
        say(f"[Camera event] {summary} You want to say: \"{res['say']}\" Say it naturally in your own words, one short sentence.",
            gap=30 if triggered_by_event else None)

def _think_async(ev):
    def run():
        try: think(ev)
        finally: A.busy = False
    A.busy = True
    threading.Thread(target=run, daemon=True).start()

def autonomy_loop():
    while not S.quit:
        time.sleep(0.5)
        now = time.time()
        seen = now - S.last_face_t < 3
        if seen and not A.present:
            away = now - A.absent_since if A.absent_since else 0
            A.present, A.present_since = True, now
            event(f"user is back after {_ago(away).replace(' ago', '')} away" if away > 20 else "user is in front of the camera")
        elif A.present and now - S.last_face_t > 10:
            A.present, A.absent_since = False, S.last_face_t
            event("user stepped away from the camera")
        n = len(S.faces) if seen else 0
        if n != A.people:
            if A.people_since == 0: A.people_since = now
            elif now - A.people_since > 3:               # count held steady for 3s
                if n > A.people and A.people >= 1: event(f"{n} people are now in view")
                A.people, A.people_since = n, 0.0
        else:
            A.people_since = 0.0
        if not (S.voice_on and A.level != "off"):
            continue
        if A.present and now - A.last_ping > 20:           # keep the call alive while you're here
            A.last_ping = now
            try: convo.register_user_activity()
            except Exception: pass
        if GEM["background"] >= AUTO_BUDGET or not vision_available():
            A.think_asap = False; continue                  # save the remaining quota for things you ask for
        due = A.present and now - A.last_think > GLANCE_EVERY
        if due and not A.think_asap:
            frame = current_raw()
            thumb = _thumb(frame) if frame is not None else None
            if not scene_changed(A.last_thumb, thumb, 8.0):
                A.last_think = now; continue                # nothing new to look at: skip the call
        if (A.think_asap or due) and not A.busy and now > S.speaking_until + 2 and now - S.last_user_t > 6:
            ev, A.think_asap, A.last_think = A.think_asap, False, now
            frame = current_raw()
            A.last_thumb = _thumb(frame) if frame is not None else None
            GEM["background"] += 1
            _think_async(ev)

@tool
def set_autonomy(p):
    lvl = str(arg(p, "level", "aware")).lower()
    if lvl not in ("off", "aware", "proactive"): return "Level must be off, aware, or proactive."
    A.level = lvl
    set_status(f"Autonomy: {lvl}")
    return {"off": "Autonomy off. I'll only act when asked.",
            "aware": "I'll keep an eye on things quietly and only speak when you talk to me.",
            "proactive": "I'll speak up on my own when something worth mentioning happens."}[lvl]

# ------------------------------------------------------------------ hand gestures (OpenCV Zoo MediaPipe hand models)
def _photo_countdown():
    S.countdown_until = time.time() + 3
    time.sleep(3)
    take_photo({"label": "gesture"})

def _gesture_record():
    (_stop_recording if S.writer else _start_recording)()

GESTURE_ACTIONS = {                      # gesture -> (label shown on screen, action)
    "ThumbsUp":   ("photo in 3", lambda: threading.Thread(target=_photo_countdown, daemon=True).start()),
    "Two":        ("record", _gesture_record),
    "Five":       ("mic", lambda: toggle_mic()),
    "ThumbsDown": ("reset", lambda: (stop_tracking("Reset"), zoom({"level": 1}))),
}
HANDS = None

def load_hand_models():
    global HANDS
    if not GESTURES: return
    try:
        sys.path.insert(0, str(BASE))
        from zoo.gestures import HandGestures
        HANDS = HandGestures(zoo_model("palm_detection_mediapipe", "palm_detection_mediapipe_2023feb.onnx"),
                             zoo_model("handpose_estimation_mediapipe", "handpose_estimation_mediapipe_2023feb.onnx"))
        print("Hand gestures: on (thumbs up = photo, peace = record, open palm = mic, thumbs down = reset)")
    except Exception as e:
        HANDS = None; print(f"Hand gestures off: {e}")

def hands_loop():
    """Runs beside the camera loop (~8 checks/sec) so gesture detection never slows the video."""
    hist, fired = deque(maxlen=6), {}
    while not S.quit:
        t0 = time.time()
        frame = current_raw()
        if HANDS is None or frame is None:
            time.sleep(0.5); continue
        try: res = HANDS.detect(frame)
        except Exception as e: print(f"[hands] {e}"); time.sleep(1); continue
        h, w = frame.shape[:2]
        S.hands = [(g, (b[0] / w, b[1] / h, (b[2] - b[0]) / w, (b[3] - b[1]) / h), [(x / w, y / h) for x, y in lm])
                   for g, b, lm, _ in res]
        g = next((r[0] for r in res if r[0] in GESTURE_ACTIONS), None)
        hist.append(g)
        now = time.time()
        if g and hist.count(g) >= 4 and now - fired.get(g, 0) > 3:     # held ~0.5s, then 3s cooldown
            fired[g] = now; hist.clear()
            label, action = GESTURE_ACTIONS[g]
            print(f"[gesture] {g} -> {label}")
            set_status(f"Gesture: {label}")
            ctx(f"[Gesture] The user made a {g} gesture ({label}).")
            try: action()
            except Exception as e: print(f"[gesture] {e}")
        time.sleep(max(0.0, 0.12 - (time.time() - t0)))

# ------------------------------------------------------------------ servos (pan/tilt head)
class Servo:
    ser = None; port = None
    pan = 90.0; tilt = 90.0; sent = (None, None); last_send = 0.0
    manual_until = 0.0     # after a turn_camera command, tracking waits so it doesn't fight you

    @classmethod
    def connect(cls):
        if not SERVO_ENABLED: return
        try:
            import serial, serial.tools.list_ports
        except ImportError:
            print("pyserial not installed, servos off"); return
        ports = [SERVO_PORT] if SERVO_PORT != "auto" else \
            [p.device for p in serial.tools.list_ports.comports()
             if any(k in f"{p.description} {p.manufacturer}".lower() for k in ("arduino", "ch340", "usb serial", "usb-serial", "cp210"))]
        for port in ports:
            try:
                cls.ser = serial.Serial(port, 115200, timeout=0.2); cls.port = port
                banner, t0 = b"", time.time()                    # opening the port resets the Arduino (~2-3s incl. wiggle)
                while time.time() - t0 < 4 and b"ready" not in banner.lower():
                    banner += cls.ser.read(64)
                txt = banner.decode(errors="ignore").strip()
                print(f"Servos connected on {port}: " + (txt if txt else "no reply (old firmware? upload jarvis_servo.ino)"))
                cls.send(force=True); return
            except Exception as e:
                print(f"Servo port {port}: {e}")
        print("No Arduino found, servos off. Set SERVO_PORT in .env if it's plugged in.")

    @classmethod
    def send(cls, force=False):
        if cls.ser is None: return
        cls.pan, cls.tilt = min(max(cls.pan, 20), 160), min(max(cls.tilt, 45), 135)
        cur = (int(round(cls.pan)), int(round(cls.tilt)))
        now = time.time()
        if force or (cur != cls.sent and now - cls.last_send > 0.03):
            try: cls.ser.write(f"{cur[0]},{cur[1]}\n".encode()); cls.sent, cls.last_send = cur, now
            except Exception as e: print(f"Servo write failed: {e}"); cls.ser = None

    @classmethod
    def track(cls, now):
        """Closed-loop: nudge the head so the main face moves toward the center of the frame."""
        if cls.ser is None or now < cls.manual_until: return
        if S.target is not None:
            x, y, w, h = S.target
            ex, ey = (x + w / 2) - 0.5, (y + h / 2) - 0.45
            if abs(ex) > 0.06: cls.pan -= PAN_DIR * max(-4, min(4, ex * SERVO_KP))
            if abs(ey) > 0.08: cls.tilt += TILT_DIR * max(-3, min(3, ey * SERVO_KP))
        elif now - S.last_face_t > 10:                           # nobody for a while: drift home
            cls.pan += (90 - cls.pan) * 0.02; cls.tilt += (90 - cls.tilt) * 0.02
        cls.send()

@tool
def turn_camera(p):
    if Servo.ser is None: return "The servo head isn't connected, so I can't physically turn."
    d = str(arg(p, "direction", "")).lower()
    deg = num(arg(p, "degrees"), 25)
    if d == "left": Servo.pan += PAN_DIR * deg
    elif d == "right": Servo.pan -= PAN_DIR * deg
    elif d == "up": Servo.tilt -= TILT_DIR * deg
    elif d == "down": Servo.tilt += TILT_DIR * deg
    elif d == "center": Servo.pan, Servo.tilt = 90, 90
    else: return "Direction must be left, right, up, down, or center."
    Servo.manual_until = time.time() + 8
    Servo.send(force=True)
    return f"Turned {d}."

# ------------------------------------------------------------------ camera + window
# Face detection: YuNet (small pretrained neural net that ships with OpenCV's model zoo) handles tilted heads,
# dim rooms, and faces further away far better than the old Haar cascade. Falls back to Haar if the model is missing.
try:    # Haar cascades were moved out of the main package in OpenCV 5; only used if YuNet can't load
    _face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
except AttributeError:
    _face_cascade = None
ZOO_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
MODELS = BASE / "models"
_yunet = None

def zoo_model(subdir, fname):
    """Path to an OpenCV Zoo model, downloading it on first use."""
    path = MODELS / fname
    if not path.exists():
        print(f"Downloading {fname}...")
        MODELS.mkdir(exist_ok=True)
        urllib.request.urlretrieve(ZOO_URL + f"{subdir}/{fname}", path)
    return path

def load_face_model():
    global _yunet
    for fname in ("face_detection_yunet_2026may.onnx", "face_detection_yunet_2023mar.onnx"):
        try:
            _yunet = cv2.FaceDetectorYN.create(str(zoo_model("face_detection_yunet", fname)), "", (320, 320), 0.6, 0.3, 50)
            print(f"Face detector: YuNet ({fname})"); return
        except Exception as e:
            print(f"YuNet {fname} failed: {e}")
    _yunet = None
    print("Face detector: Haar fallback")

def detect_faces(frame):
    """Returns normalized (x, y, w, h) boxes, biggest first."""
    h, w = frame.shape[:2]
    if _yunet is not None:
        _yunet.setInputSize((w, h))
        _, res = _yunet.detect(frame)
        boxes = [] if res is None else [tuple(float(v) for v in r[:4]) for r in res]
    elif _face_cascade is not None:
        boxes = _face_cascade.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.2, 5, minSize=(80, 80))
    else:
        boxes = []
    out = []
    for x, y, bw, bh in boxes:
        x, y = max(0.0, x), max(0.0, y)
        out.append((x / w, y / h, min(bw, w - x) / w, min(bh, h - y) / h))
    return sorted(out, key=lambda b: -b[2] * b[3])

def update_target(faces, now):
    """Pick who to track and smooth their box. Sticks with the same person instead of jumping to whoever is biggest."""
    if not faces:
        if now - S.last_face_t > 0.6: S.face_target = None  # brief misses (blinks, motion blur) keep the lock
        return
    S.last_face_t = now
    if S.face_target is None:
        S.face_target = faces[0]; return
    tx, ty, tw, th = S.face_target
    tcx, tcy = tx + tw / 2, ty + th / 2
    def score(b):                                           # prefer close to the current target, then size
        d = ((b[0] + b[2] / 2 - tcx) ** 2 + (b[1] + b[3] / 2 - tcy) ** 2) ** 0.5
        return d - 0.5 * b[2] * b[3]
    best = min(faces, key=score)
    if ((best[0] + best[2] / 2 - tcx) ** 2 + (best[1] + best[3] / 2 - tcy) ** 2) ** 0.5 > 0.35 and best is not faces[0]:
        best = faces[0]                                     # target clearly gone: take the biggest face
    a = 0.45                                                # smoothing: higher = snappier, lower = steadier
    S.face_target = tuple(o * (1 - a) + n * a for o, n in zip(S.face_target, best))

# ------------------------------------------------------------------ object tracking (VitTrack, OpenCV Zoo)
class Obj:
    tracker = None; label = ""; box = None; lost = 0; pending = None; score = 0.0

def start_tracking(box, label):
    """box: normalized (x, y, w, h) in the raw frame. The tracker itself is created on the camera thread."""
    Obj.pending = (box, label)

def stop_tracking(reason=""):
    if Obj.tracker is None and Obj.pending is None: return
    Obj.tracker, Obj.box, Obj.pending = None, None, None
    if reason: set_status(reason)

def update_object(frame):
    h, w = frame.shape[:2]
    if Obj.pending:
        (x, y, bw, bh), Obj.label = Obj.pending; Obj.pending = None
        try:
            p = cv2.TrackerVit_Params(); p.net = str(zoo_model("object_tracking_vittrack", "object_tracking_vittrack_2023sep.onnx"))
            Obj.tracker = cv2.TrackerVit_create(p)
            Obj.tracker.init(frame, (int(x * w), int(y * h), max(8, int(bw * w)), max(8, int(bh * h))))
            Obj.box, Obj.lost = (x, y, bw, bh), 0
            set_status(f"Tracking {Obj.label}")
        except Exception as e:
            Obj.tracker = None; set_status(f"Tracker failed: {e}")
        return
    if Obj.tracker is None: return
    ok, b = Obj.tracker.update(frame)
    Obj.score = float(Obj.tracker.getTrackingScore())
    if ok and Obj.score >= 0.3:
        Obj.box, Obj.lost = (b[0] / w, b[1] / h, b[2] / w, b[3] / h), 0
    else:
        Obj.lost += 1
        if Obj.lost > 20:                                   # ~0.7s of low confidence: it's gone
            label = Obj.label
            stop_tracking(f"Lost the {label}")
            ctx(f"[Presence] Lost track of the {label}.")

@tool
def track_object(p):
    target = str(arg(p, "target", "")).strip()
    if not target or target.lower() in ("stop", "none", "nothing", "cancel", "me", "my face"):
        stop_tracking("Back to tracking faces")
        return "Stopped tracking the object. Back to following faces."
    frame = current_raw()
    if frame is None: return "The camera isn't giving me a picture right now."
    set_status(f"Finding {target}...", 4)
    res = gemini_json(f'Find "{target}" in this image. Reply only with JSON: '
                      '{"found": true or false, "box_2d": [ymin, xmin, ymax, xmax]} with coordinates normalized 0 to 1000.', frame)
    box = res.get("box_2d")
    if not res.get("found") or not box or len(box) != 4:
        return f"I can't find {target} in view."
    y0, x0, y1, x1 = [float(v) / 1000 for v in box]
    start_tracking((x0, y0, max(x1 - x0, 0.02), max(y1 - y0, 0.02)), target)
    if Servo.ser is None: S.follow = True                  # no servo head: follow it with digital zoom instead
    return f"Locked on to {target}. I'll keep it in view."

def update_follow(now):
    """Digital auto-framing (like Center Stage): keep the main face centered and framed."""
    if not S.follow: return
    if S.target is not None:
        x, y, w, h = S.target
        tx, ty = x + w / 2, y + h * 0.9                 # a bit below the face so shoulders are in frame
        tz = max(1.0, min(3.0, 0.28 / max(h, 0.01)))    # face fills ~28% of the view height
        if abs(tx - S.cx_t) > 0.02: S.cx_t += (tx - S.cx_t) * 0.15
        if abs(ty - S.cy_t) > 0.02: S.cy_t += (ty - S.cy_t) * 0.15
        if abs(tz - S.zoom_t) > 0.08: S.zoom_t += (tz - S.zoom_t) * 0.08
    elif now - S.last_face_t > 2.0:                     # nobody there: drift back to wide
        S.zoom_t += (1.0 - S.zoom_t) * 0.05
        S.cx_t += (0.5 - S.cx_t) * 0.05; S.cy_t += (0.5 - S.cy_t) * 0.05

def apply_zoom(frame):
    # ease toward targets so zoom/pan animate smoothly (also shows in recordings)
    S.zoom += (S.zoom_t - S.zoom) * 0.25
    S.cx += (S.cx_t - S.cx) * 0.25
    S.cy += (S.cy_t - S.cy) * 0.25
    h, w = frame.shape[:2]
    if S.zoom <= 1.01:
        S.crop = (0.0, 0.0, 1.0, 1.0); return frame
    cw, ch = int(w / S.zoom), int(h / S.zoom)
    x0 = int(min(max(S.cx * w - cw / 2, 0), w - cw))
    y0 = int(min(max(S.cy * h - ch / 2, 0), h - ch))
    S.crop = (x0 / w, y0 / h, cw / w, ch / h)
    return cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=cv2.INTER_LINEAR)

def draw_faces(img):
    """Green boxes, mapped from raw-frame coords into the zoomed view."""
    h, w = img.shape[:2]
    cx0, cy0, cw, ch = S.crop
    ft = S.face_target if Obj.box is None else None
    boxes = ([ft] if ft else []) + [f for f in S.faces if ft is None or abs(f[0] - ft[0]) + abs(f[1] - ft[1]) > 0.08]
    for i, (x, y, bw, bh) in enumerate(boxes):
        x1, y1 = int((x - cx0) / cw * w), int((y - cy0) / ch * h)
        x2, y2 = int((x + bw - cx0) / cw * w), int((y + bh - cy0) / ch * h)
        if x2 < 0 or y2 < 0 or x1 > w or y1 > h: continue
        tracked = i == 0 and ft is not None
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0) if tracked else (0, 160, 0), 2 if tracked else 1)
        if tracked and (S.follow or Servo.ser): put(img, "TRACKING", (x1, max(18, y1 - 8)), 0.55, (0, 255, 0), 1)
    def to_view(nx, ny): return int((nx - cx0) / cw * w), int((ny - cy0) / ch * h)
    if Obj.box is not None:                                   # tracked object: orange
        x, y, bw, bh = Obj.box
        p1, p2 = to_view(x, y), to_view(x + bw, y + bh)
        cv2.rectangle(img, p1, p2, (0, 165, 255), 2)
        put(img, f"TRACKING {Obj.label.upper()}", (p1[0], max(18, p1[1] - 8)), 0.55, (0, 165, 255), 1)
    for g, (x, y, bw, bh), lm in S.hands:                     # hands: skeleton + gesture name
        pts = [to_view(px, py) for px, py in lm]
        for a, b in ((0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(0,17),(17,18),(18,19),(19,20)):
            cv2.line(img, pts[a], pts[b], (255, 200, 80), 1, cv2.LINE_AA)
        if g in GESTURE_ACTIONS:
            put(img, GESTURE_ACTIONS[g][0], (pts[0][0] - 30, pts[0][1] + 22), 0.55, (255, 200, 80), 1)
    if S.rdrag:                                               # right-drag selection box
        (sx, sy), (ex, ey) = S.rdrag
        a, b = screen_to_view(sx, sy, w, h), screen_to_view(ex, ey, w, h)
        cv2.rectangle(img, a, b, (0, 165, 255), 1)
    left = S.countdown_until - time.time()                    # thumbs-up photo countdown
    if left > 0:
        txt = str(int(left) + 1)
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 4, 8)
        put(img, txt, ((w - tw) // 2, (h + th) // 2), 4, (255, 255, 255), 8)
    return img

def screen_to_view(mx, my, w, h):
    x0, y0, nw, nh = S.disp_map
    return int((mx - x0) / max(nw, 1) * w), int((my - y0) / max(nh, 1) * h)

def fit_to_window(img, ww, wh, mode):
    ih, iw = img.shape[:2]
    if ww < 50 or wh < 50:
        S.disp_map = (0, 0, iw, ih); return img.copy()
    ww, wh = min(ww, 3840), min(wh, 2160)
    if (ww, wh) == (iw, ih):
        S.disp_map = (0, 0, iw, ih); return img.copy()
    if mode == "fill":
        s = max(ww / iw, wh / ih)
        r = cv2.resize(img, (max(1, int(iw * s)), max(1, int(ih * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        y0, x0 = (r.shape[0] - wh) // 2, (r.shape[1] - ww) // 2
        S.disp_map = (-x0, -y0, r.shape[1], r.shape[0])
        return r[y0:y0 + wh, x0:x0 + ww].copy()
    s = min(ww / iw, wh / ih)
    nw, nh = max(1, int(iw * s)), max(1, int(ih * s))
    out = np.zeros((wh, ww, 3), np.uint8)
    y0, x0 = (wh - nh) // 2, (ww - nw) // 2
    S.disp_map = (x0, y0, nw, nh)
    out[y0:y0 + nh, x0:x0 + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    return out

def put(img, text, org, scale, color=(255, 255, 255), thick=1):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)

def wrap(text, n):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n: lines.append(cur); cur = w
        else: cur = (cur + " " + w).strip()
    return lines + ([cur] if cur else [])

def voice_label():
    if not S.voice_on: return "VOICE OFF - SPACE to wake", (150, 150, 150)
    if S.mic_muted: return "MIC MUTED - SPACE", (150, 150, 150)
    if time.time() < S.speaking_until: return "SPEAKING", (255, 220, 120)
    return "LISTENING", (100, 255, 100)

def draw_hud(img):
    h, w = img.shape[:2]
    sc = max(0.45, min(1.2, min(w, h) / 900))
    lh = int(34 * sc)
    now = time.time()
    if now < S.flash_until:
        cv2.addWeighted(img, 0.4, np.full_like(img, 255), 0.6, 0, img)
    top = f"JARVIS  {S.zoom_t:.1f}x  {S.fit_mode.upper()}  {S.fps:.0f}fps" + ("  FOLLOW" if S.follow else "") + f"  AUTO:{A.level.upper()}" + (f"  SERVO:{Servo.port}" if Servo.ser else "") + f"  AI:{GEM['calls']}"
    put(img, top, (int(16 * sc), lh), sc, (120, 230, 255), 2)
    vl, vc = voice_label()
    put(img, vl, (int(16 * sc), lh * 2), sc * 0.7, vc, 2)
    x = w - int(16 * sc)
    if S.writer is not None:
        t = int(now - S.rec_start)
        label = f"REC {t // 60:02d}:{t % 60:02d}"
        (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, sc, 2)
        put(img, label, (x - tw, lh), sc, (60, 60, 255), 2)
        if int(now * 2) % 2: cv2.circle(img, (x - tw - int(18 * sc), lh - int(9 * sc)), int(9 * sc), (0, 0, 255), -1)
    if S.watch_target:
        put(img, f"WATCHING: {S.watch_target}", (int(16 * sc), lh * 3), sc * 0.7, (120, 255, 120), 2)
    y = min(S.bar_top, h - 50) - int(10 * sc)
    n = max(20, int(w / (sc * 19)))
    for (txt, ts), who, col in ((S.cap_agent, "JARVIS", (255, 220, 120)), (S.cap_user, "You", (255, 255, 255))):
        if txt and now - ts < 8:
            for line in reversed(wrap(f"{who}: {txt}", n)[-3:]):
                put(img, line, (int(16 * sc), y), sc * 0.75, col, 1); y -= int(lh * 0.9)
    if S.status and now < S.status_until:
        put(img, S.status, (int(16 * sc), y - int(lh * 0.3)), sc * 0.8, (120, 230, 255), 2)
    draw_buttons(img)
    return img

def button_defs():
    return [
        ("-",                               lambda: zoom({"direction": "out"}),   False),
        (f"{S.zoom_t:.1f}x",                lambda: zoom({"level": 1}),           S.zoom_t > 1.01),
        ("+",                               lambda: zoom({"direction": "in"}),    False),
        ("Photo",                           lambda: threading.Thread(target=take_photo, args=({},), daemon=True).start(), False),
        ("Stop" if S.writer else "Rec",     lambda: threading.Thread(target=_stop_recording if S.writer else _start_recording, daemon=True).start(), S.writer is not None),
        ("Follow",                          lambda: follow_me({"on": not S.follow}), S.follow),
        ("Mic" if not S.mic_muted else "Muted", toggle_mic,                      not S.mic_muted and S.voice_on),
        ({"off": "Auto off", "aware": "Aware", "proactive": "Proactive"}[A.level],             lambda: set_autonomy({"level": {"off": "aware", "aware": "proactive"}.get(A.level, "off")}), A.level == "proactive"),
        (S.fit_mode.capitalize(),           lambda: setattr(S, "fit_mode", "fill" if S.fit_mode == "fit" else "fit"), False),
        ("Full",                            lambda: S.window_cmds.append(("toggle_fullscreen", None)), S.fullscreen),
    ]

def draw_buttons(img):
    """Always-visible, clickable control bar along the bottom (mouse wheel zooms, drag pans)."""
    h, w = img.shape[:2]
    defs = button_defs()
    pad, gap = 10, 6
    scale = 0.55
    widths = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] + 2 * pad for t, _, _ in defs]
    total = sum(widths) + gap * (len(defs) - 1)
    if total > w - 12:                                      # shrink to fit narrow windows
        k = (w - 12) / total; scale *= k; widths = [int(x * k) for x in widths]; pad = int(pad * k); gap = max(2, int(gap * k))
        total = sum(widths) + gap * (len(defs) - 1)
    bh = max(22, int(34 * scale / 0.55))
    y1 = h - 8; y0 = y1 - bh
    x = (w - total) // 2
    overlay = img.copy()
    cv2.rectangle(overlay, (x - 6, y0 - 6), (x + total + 6, y1 + 6), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    S.buttons = []
    for (label, fn, active), bw in zip(defs, widths):
        col = (60, 150, 60) if active else (70, 70, 70)
        cv2.rectangle(img, (x, y0), (x + bw, y1), col, -1)
        cv2.rectangle(img, (x, y0), (x + bw, y1), (160, 160, 160), 1)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        cv2.putText(img, label, (x + (bw - tw) // 2, y0 + (bh + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
        S.buttons.append(((x, y0, x + bw, y1), fn))
        x += bw + gap
    S.bar_top = y0 - 6

def screen_to_raw(mx, my):
    """Window pixel -> normalized position in the full (unzoomed) camera frame."""
    x0, y0, nw, nh = S.disp_map
    u, v = (mx - x0) / max(nw, 1), (my - y0) / max(nh, 1)
    cx0, cy0, cw, ch = S.crop
    return cx0 + u * cw, cy0 + v * ch

def on_mouse(ev, mx, my, flags, _):
    if ev == cv2.EVENT_LBUTTONDOWN:
        for (x0, y0, x1, y1), fn in S.buttons:
            if x0 <= mx <= x1 and y0 <= my <= y1:
                fn(); return
        S.drag = (mx, my, S.cx_t, S.cy_t)
    elif ev == cv2.EVENT_MOUSEMOVE and S.drag and (flags & cv2.EVENT_FLAG_LBUTTON) and S.zoom_t > 1.01:
        sx, sy, cx, cy = S.drag
        _, _, nw, nh = S.disp_map
        S.follow = False
        S.cx_t = min(max(cx - (mx - sx) / max(nw, 1) / S.zoom_t, 0), 1)
        S.cy_t = min(max(cy - (my - sy) / max(nh, 1) / S.zoom_t, 0), 1)
    elif ev == cv2.EVENT_LBUTTONUP:
        S.drag = None
    elif ev == cv2.EVENT_RBUTTONDOWN:
        S.rdrag = ((mx, my), (mx, my))
    elif ev == cv2.EVENT_MOUSEMOVE and S.rdrag and (flags & cv2.EVENT_FLAG_RBUTTON):
        S.rdrag = (S.rdrag[0], (mx, my))
    elif ev == cv2.EVENT_RBUTTONUP and S.rdrag:
        (sx, sy), _ = S.rdrag; S.rdrag = None
        if abs(mx - sx) < 8 or abs(my - sy) < 8:
            stop_tracking("Back to tracking faces"); return   # right-click without dragging = stop
        ax, ay = screen_to_raw(min(sx, mx), min(sy, my)); bx, by = screen_to_raw(max(sx, mx), max(sy, my))
        start_tracking((ax, ay, bx - ax, by - ay), "selection")
    elif ev == cv2.EVENT_MOUSEWHEEL:
        S.follow = False
        up = flags > 0                                        # wheel delta lives in the high bits; sign = direction
        if up:                                                # zoom toward the cursor
            rx, ry = screen_to_raw(mx, my)
            S.cx_t += (rx - S.cx_t) * 0.35; S.cy_t += (ry - S.cy_t) * 0.35
        S.zoom_t = max(1.0, min(MAX_ZOOM, S.zoom_t * (1.2 if up else 1 / 1.2)))
        if S.zoom_t <= 1.01: S.cx_t, S.cy_t = 0.5, 0.5

def apply_window_cmds():
    while S.window_cmds:
        mode, size = S.window_cmds.pop(0)
        if mode in ("fullscreen", "toggle_fullscreen"):
            S.fullscreen = True if mode == "fullscreen" else not S.fullscreen
            cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if S.fullscreen else cv2.WINDOW_NORMAL)
        elif mode in ("pin", "unpin"):
            S.topmost = mode == "pin"
            try: cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1 if S.topmost else 0)
            except Exception: pass
        elif size:
            if S.fullscreen:
                S.fullscreen = False
                cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(WIN, *size)

KEY_LEFT, KEY_UP, KEY_RIGHT, KEY_DOWN = (2424832, 2490368, 2555904, 2621440) if IS_WIN else (65361, 65362, 65363, 65364)

def toggle_mic():
    if not S.voice_on:
        S.mic_muted = False; S.want_voice = True; set_status("Waking up...")
    else:
        S.mic_muted = not S.mic_muted
        set_status("Mic muted" if S.mic_muted else "Listening")

def servo_test():
    if Servo.ser is None: set_status("No servos connected"); return
    set_status(f"Servo test on {Servo.port}")
    Servo.manual_until = time.time() + 4
    for p, t in ((60, 90), (120, 90), (90, 70), (90, 110), (90, 90)):
        Servo.pan, Servo.tilt = p, t; Servo.send(force=True); time.sleep(0.6)

def handle_key(k):
    if k == -1: return
    c = chr(k & 0xFF).lower() if k < 256 else ""
    if k == 27: print("ESC pressed."); shutdown()
    elif c == " ": toggle_mic()
    elif c == "c": follow_me({"on": not S.follow})
    elif c == "s": threading.Thread(target=servo_test, daemon=True).start()
    elif c == "g":
        global HANDS
        if HANDS: HANDS, S.hands = None, []; set_status("Gestures off")
        else: load_hand_models(); set_status("Gestures on" if HANDS else "Gestures unavailable")
    elif c == "a": set_autonomy({"level": {"off": "aware", "aware": "proactive"}.get(A.level, "off")})
    elif c == "f": S.window_cmds.append(("toggle_fullscreen", None))
    elif c == "m": S.fit_mode = "fill" if S.fit_mode == "fit" else "fit"
    elif c == "t": S.window_cmds.append(("unpin" if S.topmost else "pin", None))
    elif c == "p": threading.Thread(target=take_photo, args=({},), daemon=True).start()
    elif c == "r": threading.Thread(target=_stop_recording if S.writer else _start_recording, daemon=True).start()
    elif c in ("+", "="): zoom({"direction": "in"})
    elif c in ("-", "_"): zoom({"direction": "out"})
    elif c == "0": zoom({"level": 1})
    elif c == "h": S.show_help_until = time.time() + (0 if time.time() < S.show_help_until else 3600)
    elif k == KEY_LEFT: pan({"direction": "left"})
    elif k == KEY_RIGHT: pan({"direction": "right"})
    elif k == KEY_UP: pan({"direction": "up"})
    elif k == KEY_DOWN: pan({"direction": "down"})

def open_camera():
    for idx in dict.fromkeys([CAM_INDEX, 0, 1, 2]):
        if CAM_BACKEND in ("dshow", "msmf"):
            cam = cv2.VideoCapture(idx, cv2.CAP_DSHOW if CAM_BACKEND == "dshow" else cv2.CAP_MSMF)
        else:
            cam = cv2.VideoCapture(idx)                  # same as robot.py
        if cam.isOpened():
            if CAM_RES != "native":
                w, h = (int(v) for v in CAM_RES.split("x"))
                cam.set(cv2.CAP_PROP_FRAME_WIDTH, w); cam.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            ok, _ = cam.read()
            if ok:
                print(f"Camera {idx}: {int(cam.get(3))}x{int(cam.get(4))}")
                return cam
        cam.release()
    return None

def camera_loop():
    cam = open_camera()
    if cam is None:
        print("No camera found. Set CAM_INDEX in .env."); set_status("No camera found", 3600)
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    if cam is not None:
        WINDOW_PRESETS["windowed"] = (int(cam.get(3)) or 640, int(cam.get(4)) or 480)
    cv2.resizeWindow(WIN, *WINDOW_PRESETS["windowed"])
    cv2.setMouseCallback(WIN, on_mouse)
    last_t, fails, n, fps_logged = time.time(), 0, 0, False
    blank = np.zeros((720, 1280, 3), np.uint8)
    while not S.quit:
        ok, frame = cam.read() if cam is not None else (False, None)
        if not ok:
            fails += 1
            if cam is not None and fails > 30:
                cam.release(); cam = open_camera(); fails = 0
            frame = blank
        else:
            fails = 0
        now = time.time(); n += 1
        S.fps = S.fps * 0.9 + (1 / max(now - last_t, 1e-3)) * 0.1
        last_t = now
        if n == 90 and not fps_logged:
            fps_logged = True
            print(f"Running at ~{S.fps:.0f} fps" + ("  (slow: try CAM_RES=native or CAM_BACKEND=dshow in .env)" if S.fps < 15 else ""))
        if ok:
            S.faces = detect_faces(frame)
            update_target(S.faces, now)
            update_object(frame)
        S.target = Obj.box if Obj.box is not None else S.face_target
        Servo.track(now)
        update_follow(now)
        view = apply_zoom(frame)
        with S.lock:
            if ok: S.raw, S.view = frame, view
            if S.writer is not None: S.writer.write(view)
        if S.rec_stop_at and now >= S.rec_stop_at:
            threading.Thread(target=_stop_recording, daemon=True).start(); S.rec_stop_at = None
        apply_window_cmds()
        try: _, _, ww, wh = cv2.getWindowImageRect(WIN)
        except Exception: ww, wh = view.shape[1], view.shape[0]
        disp = draw_faces(view.copy())
        cv2.imshow(WIN, draw_hud(fit_to_window(disp, ww, wh, S.fit_mode)))
        handle_key(cv2.waitKeyEx(1))
        try: closed = cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1
        except Exception: closed = True
        S.close_hits = S.close_hits + 1 if closed else 0
        if S.close_hits >= 5:
            print("Window closed."); shutdown()

def shutdown():
    if S.quit: return
    S.quit = True
    print("Shutting down...")
    try: _stop_recording()
    except Exception: pass
    try: convo and convo.end_session()
    except Exception: pass
    os._exit(0)

# ------------------------------------------------------------------ voice session
class SmartAudio(DefaultAudioInterface):
    """Mic gate: sends silence while muted, and (half-duplex) while JARVIS is talking,
    so it never hears itself through the speakers and answers its own voice."""
    def start(self, input_callback):
        def gated(audio):
            if S.mic_muted or (HALF_DUPLEX and time.time() < S.speaking_until + 0.35):
                audio = b"\x00" * len(audio)
            input_callback(audio)
        super().start(gated)

    def output(self, audio):
        now = time.time()
        S.speaking_until = max(now, S.speaking_until) + len(audio) / 32000   # 16 kHz, 16-bit mono
        super().output(audio)

    def interrupt(self):
        S.speaking_until = 0.0
        super().interrupt()

def build_client_tools():
    ct = ClientTools()
    for name, fn in TOOLS.items(): ct.register(name, fn)
    return ct

def on_agent(t):  print("JARVIS:", t); S.cap_agent = (t, time.time())
def on_user(t):   print("You:", t);    S.cap_user = (t, time.time()); S.last_user_t = time.time()

def main():
    global convo
    check_models()
    load_face_model()
    load_hand_models()
    Servo.connect()
    threading.Thread(target=camera_loop, daemon=True).start()
    threading.Thread(target=hands_loop, daemon=True).start()
    threading.Thread(target=autonomy_loop, daemon=True).start()
    for _ in range(50):
        if S.view is not None: break
        time.sleep(0.1)
    print(f"Session folder: {SESSION}")
    print(f"Tools: {', '.join(TOOLS)}")
    print("SPACE mutes/unmutes the mic, or wakes JARVIS if the call ended.")
    try:
        while not S.quit:
            if not S.want_voice:
                time.sleep(0.1); continue
            S.want_voice = False
            convo = Conversation(
                client, AGENT_ID, requires_auth=True,
                audio_interface=SmartAudio(),
                client_tools=build_client_tools(),
                callback_agent_response=on_agent,
                callback_user_transcript=on_user,
            )
            convo.start_session()
            S.voice_on = True
            set_status("Voice connected")
            convo.wait_for_session_end()
            S.voice_on = False
            convo = None
            if not S.quit: set_status("Call ended. Press SPACE to wake me.", 8)   # no auto-reconnect = no surprise greetings
    except KeyboardInterrupt:
        shutdown()

if __name__ == "__main__":
    main()
