import os, cv2, time, threading
import google.generativeai as genai
from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation, ClientTools
from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini = genai.GenerativeModel("gemini-3.5-flash-lite")
client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
AGENT_ID = "agent_0901m3g7etm0fcn8tfnew95me755"

# ---- shared camera state ----
latest_frame = None
CAM_INDEX = 1

# serial (servo) - your existing setup
import serial
try:
    ser = serial.Serial("COM3", 115200, timeout=1); time.sleep(2)
    print("Servos connected")
except Exception as e:
    ser = None; print("No servos:", e)

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
            x,y,fw,fh = max(faces, key=lambda f: f[2]*f[3])
            cx = x + fw//2
            pan = int(160 - (cx / w) * 140)
            if ser:
                try: ser.write(f"{pan},90\n".encode())
                except Exception: pass
            cv2.rectangle(frame,(x,y),(x+fw,y+fh),(0,255,0),2)
        cv2.imshow("JARVIS (ESC quit)", frame)
        if cv2.waitKey(1) == 27: os._exit(0)

# ---- the Gemini "eyes" tool the agent calls ----
def look(parameters):
    if latest_frame is None:
        return "I can't see anything right now."
    _, buf = cv2.imencode(".jpg", latest_frame)
    try:
        r = gemini.generate_content(
            ["Briefly describe what the person is showing or asking about in this image, in one sentence.",
             {"mime_type": "image/jpeg", "data": buf.tobytes()}],
            generation_config={"max_output_tokens": 60})
        return r.text.strip()
    except Exception as e:
        return f"I had trouble seeing that: {e}"

# ---- run ----
threading.Thread(target=camera_loop, daemon=True).start()

tools = ClientTools()
tools.register("look", look)

convo = Conversation(
    client, AGENT_ID, requires_auth=True,
    audio_interface=DefaultAudioInterface(),
    client_tools=tools,
    callback_agent_response=lambda t: print("JARVIS:", t),
    callback_user_transcript=lambda t: print("You:", t),
)
convo.start_session()