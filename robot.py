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
import atexit
memory = build_memory()
atexit.register(memory.close)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
vision = genai.GenerativeModel("gemini-3.5-flash")
client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
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
def drive_servo(target):
    global smoothed_pan, last_sent
    smoothed_pan = smoothed_pan * 0.8 + target * 0.2
    val = int(smoothed_pan)
    if ser and abs(val - last_sent) >= 2:
        try: ser.write(f"{val},90\n".encode())
        except Exception: pass
        last_sent = val

def camera_loop():
    global latest_frame
    cam = cv2.VideoCapture(CAM_INDEX)
    face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    while True:
        ok, frame = cam.read()
        if not ok: break
        latest_frame = frame.copy()
        h, w = frame.shape[:2]
        faces = face.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.2, 5, minSize=(80,80))
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2]*f[3])
            memory.identifier.submit(frame, (x, y, fw, fh))
            drive_servo(160 - ((x + fw//2) / w) * 140)
            cv2.rectangle(frame, (x, y), (x+fw, y+fh), (0,255,0), 2)
        else:
            memory.identifier.submit(frame, None)
        cv2.imshow("JARVIS (ESC quit)", frame)
        if cv2.waitKey(1) == 27:
            close_and_exit(memory.close)

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

convo = Conversation(
    client, AGENT_ID, requires_auth=True,
    audio_interface=DefaultAudioInterface(),
    client_tools=client_tools,     # <-- this was missing
    callback_agent_response=lambda t: (print("JARVIS:", t), memory.ingestor.on_agent(t)),
    callback_user_transcript=lambda t: (print("You:", t), memory.ingestor.on_user(t)),
)
convo.start_session()
