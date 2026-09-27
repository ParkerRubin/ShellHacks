import os, cv2, time, threading
import warnings; warnings.filterwarnings("ignore")
import google.generativeai as genai
from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation, ClientTools
from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface

load_dotenv()
from jarvis.memory import build_memory
from jarvis.runtime import close_and_exit
from jarvis.tracking import pan_for
from jarvis.positivity import build_positivity
import atexit
memory = build_memory()
atexit.register(memory.close)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
vision = genai.GenerativeModel("gemini-3.5-flash")
client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
positivity = build_positivity(client, vision)
atexit.register(positivity.close)
AGENT_ID = "agent_0901m3g7etm0fcn8tfnew95me755"

latest_frame = None
CAM_INDEX = 1

import serial
try:
    ser = serial.Serial("COM3", 115200, timeout=1); time.sleep(2)
    print("Servos connected")
except Exception as e:
    ser = None; print("No servos:", e)

smoothed_pan = 90; last_sent = 90
def drive_servo(target, force=False):
    global smoothed_pan, last_sent
    smoothed_pan = target if force else smoothed_pan * 0.8 + target * 0.2
    val = int(smoothed_pan)
    if ser and (force or abs(val - last_sent) >= 2):
        try: ser.write(f"{val},90\n".encode())
        except Exception: pass
        last_sent = val

locked_center = None
lost_streak = 0
LOST_RESET_FRAMES = 15  # ~0.5s of nothing before we allow snapping to a new face
MAX_JUMP_FRAC = 0.35    # a "closest" candidate further than this (x frame diagonal) from
                        # the lock is probably a false detection, not the same person moving

def pick_face(faces, diag):
    """Stay locked on the previously-tracked face instead of re-picking the
    biggest one every frame, so a person walking into the background (or a
    stray false-positive when the real face briefly drops out) doesn't steal
    the camera."""
    global locked_center, lost_streak
    face = None
    if len(faces):
        if locked_center is None:
            face = max(faces, key=lambda f: f[2] * f[3])
        else:
            lx, ly = locked_center
            candidate = min(faces, key=lambda f: (f[0] + f[2] / 2 - lx) ** 2 + (f[1] + f[3] / 2 - ly) ** 2)
            cx, cy = candidate[0] + candidate[2] / 2, candidate[1] + candidate[3] / 2
            if ((cx - lx) ** 2 + (cy - ly) ** 2) ** 0.5 <= MAX_JUMP_FRAC * diag:
                face = candidate
    if face is None:
        lost_streak += 1
        if lost_streak > LOST_RESET_FRAMES:
            locked_center = None
        return None
    lost_streak = 0
    x, y, fw, fh = face
    locked_center = (x + fw / 2, y + fh / 2)
    return face

manual_pan = 90
last_manual_ts = 0.0
MANUAL_STEP = 8
MANUAL_HOLD_S = 1.5  # after a manual key, auto-tracking backs off briefly

def manual_active(now):
    return (now - last_manual_ts) < MANUAL_HOLD_S

def camera_loop():
    global latest_frame, manual_pan, last_manual_ts
    cam = cv2.VideoCapture(CAM_INDEX)
    face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    while True:
        ok, frame = cam.read()
        if not ok: break
        latest_frame = frame.copy()
        h, w = frame.shape[:2]
        faces = face.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.2, 5, minSize=(80,80))
        if positivity.enabled:
            try:
                positivity.bus.publish(frame, faces)
            except Exception:
                pass
        target = pick_face(faces, (w * w + h * h) ** 0.5)
        if target is not None:
            memory.identifier.submit(frame, target)
            if not manual_active(time.time()):
                drive_servo(pan_for(target, w))
            x, y, fw, fh = target
            cv2.rectangle(frame, (x, y), (x+fw, y+fh), (0,255,0), 2)
        else:
            memory.identifier.submit(frame, None)
        cv2.putText(frame, "A/D pan  C center  ESC quit", (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.imshow("JARVIS (ESC quit)", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('a'), ord('A')):
            manual_pan = max(20, manual_pan - MANUAL_STEP)
            last_manual_ts = time.time()
            drive_servo(manual_pan, force=True)
        elif key in (ord('d'), ord('D')):
            manual_pan = min(160, manual_pan + MANUAL_STEP)
            last_manual_ts = time.time()
            drive_servo(manual_pan, force=True)
        elif key in (ord('c'), ord('C')):
            manual_pan = 90
            last_manual_ts = time.time()
            drive_servo(manual_pan, force=True)
        elif key == 27:
            close_and_exit(lambda: (positivity.close(), memory.close()))

def look(parameters):
    print(">>> LOOK TOOL FIRED")
    if latest_frame is None:
        return "I can't see anything right now."
    _, buf = cv2.imencode(".jpg", latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    try:
        r = vision.generate_content(
            ["Name the object being held up to the camera, specifically, with brand/text if visible. "
             "If nothing clear, say so.",
             {"mime_type": "image/jpeg", "data": buf.tobytes()}],
            generation_config={"max_output_tokens": 300})   # 300 so thinking tokens don't starve output
        try:
            text = r.text.strip()
            memory.ingestor.on_gemini(text)
            return text
        except Exception: return "I couldn't make that out clearly."
    except Exception as e:
        return f"I had trouble seeing that: {e}"

threading.Thread(target=camera_loop, daemon=True).start()

client_tools = ClientTools()
client_tools.register("look", look)
if memory.enabled:
    client_tools.register("recall", lambda p: memory.retriever.recall(p.get("query", ""), memory.presence.user_id))
    client_tools.register("remember_me", lambda p: memory.consent.remember(p.get("confirmed", False), p.get("name")))
    client_tools.register("forget_me", lambda p: memory.consent.forget())

def on_user_transcript(text):
    deliver = True
    if positivity.enabled:
        try:
            deliver = positivity.on_user_transcript(text)
        except Exception:
            pass
    if deliver:
        print("You:", text)
        memory.ingestor.on_user(text)

convo = Conversation(
    client, AGENT_ID, requires_auth=True,
    audio_interface=DefaultAudioInterface(),
    client_tools=client_tools,     # <-- this was missing
    callback_agent_response=lambda t: (print("JARVIS:", t), memory.ingestor.on_agent(t)),
    callback_user_transcript=on_user_transcript,
)
convo.start_session()
