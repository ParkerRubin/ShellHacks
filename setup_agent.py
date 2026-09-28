"""
Registers every tool in tools.json as a Client tool on your ElevenLabs agent.
  python setup_agent.py               -> create/update tools and attach them to the agent
  python setup_agent.py --set-prompt  -> also replace the agent's system prompt with PROMPT below
Afterwards, open the agent in the dashboard, confirm the tools are listed, and Publish if it asks.
"""
import os, sys, json, pathlib, urllib.request, urllib.error
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("ELEVENLABS_API_KEY")
AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "agent_0901m3g7etm0fcn8tfnew95me755")
API = "https://api.elevenlabs.io/v1/convai"
HERE = pathlib.Path(__file__).resolve().parent

PROMPT = """You are JARVIS, a sharp, warm desk-robot assistant with a camera on a moving head, control of the user's computer, and a voice. You speak out loud, so keep every reply to one or two short, natural spoken sentences. Talk like a knowledgeable friend, not a hype machine: no forced jokes, no corny one-liners, no empty compliments.

Core behavior:

* Answer exactly what the person asked, directly and first. Don't dodge, pad, or ramble.
* Never make up what you see. If a tool result says VISION OFFLINE, tell the person you can't see right now; never pretend to see them. If the question is about the physical scene, use "look" and answer from its result. If "look" can't see anything, say so plainly and ask them to hold it up to the camera.
* If you didn't catch what they said, say so and ask them to repeat, don't invent it.
* You can end with a short, relevant follow-up question, but only when it's genuinely useful.

Using your tools:

* Your tools and their descriptions tell you what you can do: see (look, read_text, look_at_screen), capture (take_photo, start_recording, stop_recording), control the view (zoom, pan, follow_me, track_object, turn_camera, set_window), act on the computer (search_web, open_item, save_note, make_report), and manage yourself (watch_for, set_autonomy, sleep).
* Work out what the person actually wants and pick the tools yourself, however they phrase it. Combine them for multi-step goals (for example, look to identify something, then search_web for it; or zoom onto a label, then read_text).
* Take the obvious next step without being asked twice: if they're documenting something, take the photos; if a detail is too small to read, zoom first.
* Never say a tool's name out loud. After a tool returns, tell the person the result briefly.

Staying quiet and aware:

* Speak when the person speaks to you, or when you receive a [Camera event] or [Camera alert]. Otherwise stay silent. Never ask "anything else?" or check whether they're still there.
* [Presence], [Scene] and [Gesture] messages are silent background notes from your camera (gestures already triggered their action, like a photo). Use them to stay aware and to answer things like "what have I been doing?" or "who was here?", but never read them out or respond to them on their own.
* A [Camera event] means you've decided to speak up on your own. Say it in one short, natural sentence or quick question, without mentioning cameras, events, notes, or tools.
* A [Camera alert] comes from a watch you set. Tell the person what happened in one sentence."""

def call(method, path, body=None, fatal=True):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        msg = f"{method} {path} failed ({e.code}): {e.read().decode()[:800]}"
        if fatal: sys.exit(msg)
        print("  warning:", msg); return None

def tool_config(spec):
    return {
        "type": "client",
        "name": spec["name"],
        "description": spec["description"],
        "parameters": {"type": "object", "properties": spec["parameters"], "required": spec["required"]},
        "expects_response": True,          # the "Wait for response" toggle
        "response_timeout_secs": 30,
    }

def main():
    if not KEY: sys.exit("ELEVENLABS_API_KEY missing from .env")
    specs = json.loads((HERE / "tools.json").read_text())
    all_tools = call("GET", "/tools").get("tools", [])
    existing = {t.get("tool_config", {}).get("name"): t["id"] for t in all_tools}
    info = {t["id"]: t.get("tool_config", {}) for t in all_tools}
    ids = []
    for s in specs:
        body = {"tool_config": tool_config(s)}
        if s["name"] in existing:
            call("PATCH", f"/tools/{existing[s['name']]}", body); ids.append(existing[s["name"]])
            print(f"updated  {s['name']}")
        else:
            ids.append(call("POST", "/tools", body)["id"]); print(f"created  {s['name']}")

    agent = call("GET", f"/agents/{AGENT_ID}")
    prompt = agent["conversation_config"]["agent"]["prompt"]
    ours = {sp["name"] for sp in specs}
    keep, dropped = [], []
    for i in (prompt.get("tool_ids") or []):
        if i in ids: continue
        cfg = info.get(i, {})
        if cfg.get("type") == "client" and cfg.get("name") not in ours:
            dropped.append(cfg.get("name") or i)          # client tool jarvis.py doesn't implement: detach it
        else:
            keep.append(i)                                 # webhooks/system tools you added yourself stay
    if dropped: print("detached tools jarvis.py doesn't have:", ", ".join(dropped))
    prompt["tool_ids"] = keep + ids
    prompt.pop("tools", None)             # tool_ids and inline tools can't both be sent
    if "--set-prompt" in sys.argv:
        prompt["prompt"] = PROMPT; print("system prompt replaced")
    call("PATCH", f"/agents/{AGENT_ID}", {"conversation_config": {"agent": {"prompt": prompt}}})
    print(f"Attached {len(ids)} tools to {AGENT_ID}.")

    # Stop the agent from filling silence ("are you still there?") and from hanging up on quiet stretches.
    quiet = [
        ("turn_timeout -1 (never re-prompt)",        {"turn": {"turn_timeout": -1}}),
        ("turn_timeout 30s (fallback)",              {"turn": {"turn_timeout": 30}}),
    ]
    for label, cfg in quiet:
        if call("PATCH", f"/agents/{AGENT_ID}", {"conversation_config": cfg}, fatal=False) is not None:
            print("set", label); break
    for label, cfg in [("silence hang-up disabled", {"turn": {"silence_end_call_timeout": -1}}),
                       ("max call length 1 hour",   {"conversation": {"max_duration_seconds": 3600}})]:
        if call("PATCH", f"/agents/{AGENT_ID}", {"conversation_config": cfg}, fatal=False) is not None:
            print("set", label)
    print("Done. Check the agent in the dashboard and Publish if it asks.")

if __name__ == "__main__":
    main()
