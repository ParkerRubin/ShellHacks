"""
JARVIS: voice-driven camera assistant that acts on your computer.
ElevenLabs Conversational AI (voice + tool calls) + Gemini (vision) + OpenCV (camera).

Window keys:
  SPACE mic mute / wake   C follow me (auto-framing)   F fullscreen   M fit/fill   T pin on top
  P photo   R record   + / - zoom   arrows pan   0 reset zoom   H help   ESC quit
The window can be dragged to any size or shape; the picture adapts.
"""
import os, re, sys, json, time, html, threading, subprocess, webbrowser, datetime, pathlib, urllib.parse
import warnings; warnings.filterwarnings("ignore")
import cv2
import numpy as np
import google.generativeai as genai
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
SERVO_ENABLED = os.getenv("SERVO_ENABLED", "0") == "1"    # flip on once the Arduino is back in use
SERVO_PORT    = os.getenv("SERVO_PORT", "COM3")
AUTONOMY      = os.getenv("AUTONOMY", "aware")                # off, aware (silent awareness), proactive (speaks up on its own)
GLANCE_EVERY  = float(os.getenv("GLANCE_EVERY", "30"))        # seconds between background scene checks while you're in frame
SPEAK_GAP     = float(os.getenv("SPEAK_GAP", "120"))          # minimum seconds between unprompted remarks
WIN           = "JARVIS"
IS_WIN        = sys.platform.startswith("win")

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
vision = genai.GenerativeModel(VISION_MODEL)
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

def gemini(prompt, img=None, max_tokens=1024, json_mode=False):
    parts = [prompt] + ([{"mime_type": "image/jpeg", "data": _jpeg(img)}] if img is not None else [])
    cfg = {"max_output_tokens": max_tokens}          # thinking tokens count against this, keep it roomy
    if json_mode: cfg["response_mime_type"] = "application/json"
    r = vision.generate_content(parts, generation_config=cfg, request_options={"timeout": 30})
    try: return r.text.strip()
    except Exception: return ""

def gemini_json(prompt, img, max_tokens=1024):
    txt = gemini(prompt, img, max_tokens, json_mode=True)
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}

def caption_async(entry, img):
    def run():
        try: entry["caption"] = gemini("Describe this photo in one factual sentence: main subject, condition, any readable text.", img, 512)
        except Exception as e: entry["caption"] = f"(caption failed: {e})"
    threading.Thread(target=run, daemon=True).start()

# ------------------------------------------------------------------ tools (called by the ElevenLabs agent)
TOOLS = {}
def tool(fn):
    def wrapper(params):
        params = params if isinstance(params, dict) else {}
        shown = {k: v for k, v in params.items() if k != "tool_call_id"}
        print(f">>> TOOL {fn.__name__} {shown}")
        try: out = fn(params)
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
    caption_async(add_log("photo", file=path.name, label=label, caption=None), frame)
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
    deadline = time.time() + 10                       # let pending photo captions finish
    while time.time() < deadline and any(e["kind"] == "photo" and e.get("caption") is None for e in S.log):
        time.sleep(0.5)
    if not S.log and not NOTES.exists(): return "There's nothing in this session to report yet."
    facts = []
    for e in S.log:
        if e["kind"] == "photo": facts.append(f"[{e['time']}] Photo {e['file']} ({e.get('label') or 'no label'}): {e.get('caption') or ''}")
        elif e["kind"] == "video": facts.append(f"[{e['time']}] Video {e['file']}, {e['seconds']}s")
        elif e["kind"] in ("look", "screen"): facts.append(f"[{e['time']}] Asked '{e.get('question')}': {e['text']}")
        else: facts.append(f"[{e['time']}] {e['kind']}: {e.get('text', '')[:500]}")
    notes = NOTES.read_text(encoding="utf-8") if NOTES.exists() else ""
    set_status("Writing report...", 8)
    summary = gemini(f"Write a clear, factual summary for a report whose purpose is: {purpose}. "
                     "Use short paragraphs and, if useful, a short bulleted list of key findings or next steps. "
                     "Only use the information below; do not invent details. Plain text, no markdown headers.\n\n"
                     + "\n".join(facts) + "\n\nNotes:\n" + notes, None, 2048) or "(summary unavailable)"
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

def watch_loop(target, token):
    while S.watch_token == token and not S.quit:
        frame = current_raw()
        if frame is not None:
            try:
                res = gemini_json(f'Is {target} clearly visible in this image? Reply only with JSON: '
                                  '{"present": true or false, "detail": "short description"}', frame, 512)
            except Exception as e:
                res = {}; print(f"[watch] {e}")
            if res.get("present") and S.watch_token == token:
                S.watch_target = None
                name = take_photo({"label": f"watch {target}"})
                add_log("note", text=f"Watch alert: {target} appeared. {res.get('detail', '')}")
                notify_agent(f"[Camera alert] {target} just appeared: {res.get('detail', '')}. {name} "
                             "Tell the user in one short sentence.")
                return
        time.sleep(WATCH_EVERY)

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
class A:
    level = AUTONOMY if AUTONOMY in ("off", "aware", "proactive") else "aware"
    present = False; present_since = 0.0; absent_since = 0.0; seen_once = False
    last_glance = 0.0; last_scene = ""; last_spoke = 0.0; last_ping = 0.0
    multi_since = None; multi_announced = False; break_nudged_at = 0.0

def _fmt(sec):
    m = int(sec // 60)
    return f"{m} minute{'s' if m != 1 else ''}" if m else f"{int(sec)} seconds"

def ctx(text):
    """Silent background note: the agent knows it but doesn't respond."""
    c = convo
    if c is None or not S.voice_on or A.level == "off": return
    try: c.send_contextual_update(text); print(f"[ctx] {text}")
    except Exception as e: print(f"[ctx] failed: {e}")

def say(text, gap=None):
    """Ask the agent to speak on its own, only when it won't talk over anyone."""
    now, c = time.time(), convo
    gap = SPEAK_GAP if gap is None else gap
    if (A.level != "proactive" or c is None or not S.voice_on or S.mic_muted
            or now < S.speaking_until + 1.5 or now - S.last_user_t < 15 or now - A.last_spoke < gap):
        return False
    try:
        c.send_user_message(text); A.last_spoke = now; print(f"[proactive] {text}")
        return True
    except Exception as e:
        print(f"[proactive] failed: {e}"); return False

def glance():
    frame = current_raw()
    if frame is None: return
    try:
        res = gemini_json(
            "You are the eyes of a friendly desk assistant watching through a webcam. "
            f'Previous observation: "{A.last_scene or "none"}". Reply only with JSON: '
            '{"summary": "one sentence: who is there, what they are doing, anything they are holding", '
            '"changed": true only if something meaningfully new vs the previous observation (an object held up, a new person, a new activity), '
            '"remark": "if changed, one short friendly thing an assistant might say or ask about it, else empty"}', frame)
    except Exception as e:
        print(f"[glance] {e}"); return
    summary = (res.get("summary") or "").strip()
    if not summary or summary == A.last_scene: return
    A.last_scene = summary
    add_log("scene", text=summary)
    ctx(f"[Scene {datetime.datetime.now():%H:%M}] {summary}")
    if res.get("changed") and res.get("remark"):
        say(f"[Camera event] You noticed: {summary} If it feels natural, say something like: \"{res['remark']}\" One short sentence.")

def autonomy_loop():
    while not S.quit:
        time.sleep(1)
        now = time.time()
        seen = now - S.last_face_t < 3
        # arrivals and departures, from the face detector (free, no API calls)
        if seen and not A.present:
            away = now - A.absent_since if A.absent_since else 0
            A.present, A.present_since = True, now
            ctx(f"[Presence] The user is in front of the camera{f' again after {_fmt(away)} away' if away else ''}.")
            if A.seen_once and away > 60:
                say(f"[Camera event] The user just came back after {_fmt(away)} away. Welcome them back in a few words.", gap=30)
            A.seen_once = True
        elif A.present and now - S.last_face_t > 10:
            A.present, A.absent_since = False, S.last_face_t
            ctx("[Presence] The user stepped away from the camera.")
        # someone else joins
        n = len(S.faces) if seen else 0
        if n >= 2:
            A.multi_since = A.multi_since or now
            if now - A.multi_since > 3 and not A.multi_announced:
                A.multi_announced = True
                ctx(f"[Presence] {n} people are in view.")
                say("[Camera event] Someone else just joined the user in frame. Acknowledge them briefly and naturally.", gap=45)
        elif A.multi_since and now - A.multi_since > 10:
            A.multi_since, A.multi_announced = None, False
        # long sitting: one stretch nudge per hour
        if A.present and now - A.present_since > 50 * 60 and now - A.break_nudged_at > 3600:
            if say(f"[Camera event] The user has been at the desk for {_fmt(now - A.present_since)} straight. Suggest a quick stretch break in one friendly sentence."):
                A.break_nudged_at = now
        if not (A.present and S.voice_on and A.level != "off"):
            continue
        # keep the call alive while you're here, even if you're quiet
        if now - A.last_ping > 20:
            A.last_ping = now
            try: convo.register_user_activity()
            except Exception: pass
        # periodic look at the scene: silent note, spoken only if something new and proactive
        if now - A.last_glance > GLANCE_EVERY and now > S.speaking_until + 2 and now - S.last_user_t > 8:
            A.last_glance = now
            glance()

@tool
def set_autonomy(p):
    lvl = str(arg(p, "level", "aware")).lower()
    if lvl not in ("off", "aware", "proactive"): return "Level must be off, aware, or proactive."
    A.level = lvl
    set_status(f"Autonomy: {lvl}")
    return {"off": "Autonomy off. I'll only act when asked.",
            "aware": "I'll keep an eye on things quietly and only speak when you talk to me.",
            "proactive": "I'll speak up on my own when something worth mentioning happens."}[lvl]

# ------------------------------------------------------------------ optional servo (off by default)
ser = None
if SERVO_ENABLED:
    try:
        import serial
        ser = serial.Serial(SERVO_PORT, 115200, timeout=1); time.sleep(2)
        print("Servos connected")
    except Exception as e:
        print("No servos:", e)
_pan_s, _pan_sent = 90.0, 90
def drive_servo(target):
    global _pan_s, _pan_sent
    _pan_s = _pan_s * 0.8 + target * 0.2
    val = int(_pan_s)
    if ser and abs(val - _pan_sent) >= 2:
        try: ser.write(f"{val},90\n".encode())
        except Exception: pass
        _pan_sent = val

# ------------------------------------------------------------------ camera + window
_face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

def detect_faces(frame):
    """Same detector settings as robot.py; returns normalized boxes, biggest first."""
    h, w = frame.shape[:2]
    boxes = _face_cascade.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.2, 5, minSize=(80, 80))
    out = [(x / w, y / h, bw / w, bh / h) for x, y, bw, bh in boxes]
    return sorted(out, key=lambda b: -b[2] * b[3])

def update_follow(now):
    """Digital auto-framing (like Center Stage): keep the main face centered and framed."""
    if not S.follow: return
    if S.faces:
        x, y, w, h = S.faces[0]
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
    for i, (x, y, bw, bh) in enumerate(S.faces):
        x1, y1 = int((x - cx0) / cw * w), int((y - cy0) / ch * h)
        x2, y2 = int((x + bw - cx0) / cw * w), int((y + bh - cy0) / ch * h)
        if x2 < 0 or y2 < 0 or x1 > w or y1 > h: continue
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        if S.follow and i == 0: put(img, "TRACKING", (x1, max(18, y1 - 8)), 0.55, (0, 255, 0), 1)
    return img

def fit_to_window(img, ww, wh, mode):
    ih, iw = img.shape[:2]
    if ww < 50 or wh < 50: return img.copy()
    ww, wh = min(ww, 3840), min(wh, 2160)
    if (ww, wh) == (iw, ih): return img.copy()
    if mode == "fill":
        s = max(ww / iw, wh / ih)
        r = cv2.resize(img, (max(1, int(iw * s)), max(1, int(ih * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        y0, x0 = (r.shape[0] - wh) // 2, (r.shape[1] - ww) // 2
        return r[y0:y0 + wh, x0:x0 + ww].copy()
    s = min(ww / iw, wh / ih)
    nw, nh = max(1, int(iw * s)), max(1, int(ih * s))
    out = np.zeros((wh, ww, 3), np.uint8)
    y0, x0 = (wh - nh) // 2, (ww - nw) // 2
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
    top = f"JARVIS  {S.zoom_t:.1f}x  {S.fit_mode.upper()}  {S.fps:.0f}fps" + ("  FOLLOW" if S.follow else "") + f"  AUTO:{A.level.upper()}"
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
    y = h - int(16 * sc)
    n = max(20, int(w / (sc * 19)))
    for (txt, ts), who, col in ((S.cap_agent, "JARVIS", (255, 220, 120)), (S.cap_user, "You", (255, 255, 255))):
        if txt and now - ts < 8:
            for line in reversed(wrap(f"{who}: {txt}", n)[-3:]):
                put(img, line, (int(16 * sc), y), sc * 0.75, col, 1); y -= int(lh * 0.9)
    if S.status and now < S.status_until:
        put(img, S.status, (int(16 * sc), y - int(lh * 0.3)), sc * 0.8, (120, 230, 255), 2)
    if now < S.show_help_until:
        help_ = "SPACE mic  A autonomy  C follow  F fullscreen  M fit/fill  T pin  P photo  R record  +/- zoom  arrows pan  0 reset  H help  ESC quit"
        put(img, help_, (int(16 * sc), lh * 4), sc * 0.5, (200, 200, 200), 1)
    return img

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

def handle_key(k):
    if k == -1: return
    c = chr(k & 0xFF).lower() if k < 256 else ""
    if k == 27: shutdown()
    elif c == " ": toggle_mic()
    elif c == "c": follow_me({"on": not S.follow})
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
            if S.faces:
                S.last_face_t = now
                x, y, fw, fh = S.faces[0]
                if ser: drive_servo(160 - (x + fw / 2) * 140)
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
        try:
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1: shutdown()
        except Exception: shutdown()

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
    threading.Thread(target=camera_loop, daemon=True).start()
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
