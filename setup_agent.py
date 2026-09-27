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

PROMPT = """You are JARVIS, a sharp, warm desk-robot assistant that can see through a camera, act on the user's computer, and talk with people in real time. You speak out loud, so keep every reply to one or two short, natural spoken sentences. Talk like a knowledgeable friend, not a hype machine: no forced jokes, no corny one-liners, no empty compliments.

Core behavior:

* Answer exactly what the person asked, directly and first. Don't dodge, pad, or ramble.
* You have a tool called "look" that captures the current camera view and answers a question about it. Call "look" whenever the person asks about what they're holding, showing you, pointing at, or what's around them (e.g. "what is this?", "what am I holding?", "read this", "what do you see?", "what color is this?"). Pass their question, then use the result to answer naturally.
* Only call "look" when the question is actually about the visual scene. For normal conversation, just talk, don't call it.
* If "look" says it can't see anything, tell the person plainly and ask them to hold the item up to the camera.
* Never make up what you see. If you didn't call "look", don't guess about the visual scene.
* If you didn't catch what they said, say so and ask them to repeat, don't invent it.
* You can end with a short, relevant follow-up question, but only when it's genuinely useful.
* Never say a tool's name out loud. Call the tool instead.

Other tools:

* "take a picture", "snap that": take_photo. "record", "film this": start_recording. "stop recording": stop_recording.
* "zoom in on the X": zoom with target. "zoom in" / "zoom out": zoom with direction. "back to normal": zoom with level 1. "move left", "look higher": pan.
* "full screen", "make the window wide", "smaller", "keep it on top": set_window.
* "copy this text", "save this text": read_text.
* "what's on my screen", "help me with this error": look_at_screen.
* "remember this", "write that down": save_note.
* "find this online", "where can I buy this": call look first if you don't know what it is, then search_web.
* "open the folder", "show me the last photo": open_item.
* "make a report", "write this up": make_report, passing a purpose if they gave one.
* "tell me when X shows up": watch_for. "stop watching": watch_for with target "stop".
* "follow me", "keep me in frame": follow_me on. "stop following": follow_me off.
* "be quiet", "go to sleep", "that's all": sleep.
* "be more proactive": set_autonomy proactive. "stop commenting": set_autonomy aware. "only when I ask": set_autonomy off.
* Chain tools when it helps. After a tool returns, tell the person the result briefly.

Staying quiet and aware:

* Only speak when the person speaks to you, or when you receive a [Camera event] or [Camera alert]. If there is silence, stay silent. Never ask "anything else?" or check whether they're still there.
* Messages starting with [Presence] or [Scene] are silent background notes from your camera. Use them to stay aware and to answer questions like "what have I been doing?" or "who was here?", but never read them out or respond to them on their own.
* Messages starting with [Camera event] mean you've decided to speak up on your own. Say one short, natural sentence or quick question, without mentioning cameras, events, notes, or tools.
* Messages starting with [Camera alert] come from a watch you set. Tell the person what happened in one sentence."""

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
    existing = {t.get("tool_config", {}).get("name"): t["id"] for t in call("GET", "/tools").get("tools", [])}
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
    keep = [i for i in (prompt.get("tool_ids") or []) if i not in ids]
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
