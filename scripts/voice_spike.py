"""Human-run A/B/C audio spike. Uses real services/devices only when explicitly run.

No face data is used. Results are operator observations, not automated validation.
"""

import argparse
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from jarvis.positivity.config import PositivityConfig
from jarvis.positivity.voice import ElevenLabsTTSDelivery, play_pcm

TEXT = "Hello. This is the robot voice playback test."


def run_option(option, client, config, make_conversation, prompt=input):
    started = None
    first_response = threading.Event()
    events = {"agent_responses": 0, "user_transcripts": 0}
    first_audio = []

    def agent_response(_text):
        events["agent_responses"] += 1
        first_response.set()

    def user_transcript(_text):
        # Count only; never save live transcripts to the results file.
        events["user_transcripts"] += 1

    conversation = make_conversation(agent_response, user_transcript)
    delivery = None
    outcome = "completed"
    try:
        conversation.start_session()
        prompt(
            f"Option {option}: wait until the agent is quiet, then press Enter to play the test. "
        )
        events.update(agent_responses=0, user_transcripts=0)
        first_response.clear()

        def player(chunks, cancelled):
            def measured():
                for chunk in chunks:
                    if not first_audio:
                        first_audio.append(time.perf_counter() - started)
                    yield chunk

            play_pcm(measured(), cancelled)

        delivery = ElevenLabsTTSDelivery(client, config, player=player)
        started = time.perf_counter()
        if option == "A":
            delivery.speak(TEXT, style="remark")
        elif option == "B":
            sender = getattr(conversation, "send_user_message", None)
            if sender is None:
                outcome = "unsupported: SDK has no send_user_message"
            else:
                sender("Please say exactly this test line: " + TEXT)
                if not first_response.wait(20):
                    outcome = "no agent response within 20 s"
        elif option == "C":
            conversation.end_session()
            delivery.speak(TEXT, style="remark")
            conversation = make_conversation(agent_response, user_transcript)
            conversation.start_session()
        prompt("Listen for unwanted agent replies/device conflicts, then press Enter. ")
    except Exception as exc:
        outcome = "failed: " + type(exc).__name__
    finally:
        if delivery:
            delivery.cancel()
        try:
            conversation.end_session()
        except Exception:
            outcome += "; conversation cleanup failed"
    echo = prompt("Echo/self-talk observed? (yes/no/unknown): ")
    conflict = prompt("Device conflict observed? (yes/no/unknown): ")
    latency = prompt(
        "Audible onset latency in seconds, if measured; otherwise unknown: "
    )
    notes = prompt("Operator notes (no names, transcripts, keys or credentials): ")
    return {
        "option": option,
        "outcome": outcome,
        "echo": echo,
        "conflict": conflict,
        "audible_latency": latency,
        "first_pcm": f"{first_audio[0]:.3f}s" if first_audio else "not measured",
        "notes": notes,
        **events,
    }


def save_results(path, results):
    def clean(value):
        return str(value).replace("\n", " ").replace("|", "/")

    stamp = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as output:
        output.write(f"\n## Human-run observations: {stamp}\n\n")
        output.write(
            "| Option | Outcome | Echo | Device conflict | Audible onset (operator) | First PCM chunk | Agent responses | Transcript count | Notes |\n"
        )
        output.write("| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
        for result in results:
            output.write(
                "| "
                + " | ".join(
                    clean(result[k])
                    for k in [
                        "option",
                        "outcome",
                        "echo",
                        "conflict",
                        "audible_latency",
                        "first_pcm",
                        "agent_responses",
                        "user_transcripts",
                        "notes",
                    ]
                )
                + " |\n"
            )
        output.write(
            "\nFirst PCM chunk timing is API arrival, not measured speaker onset. A/B/C results require human interpretation.\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--option", choices=["A", "B", "C", "all"], default="all")
    parser.add_argument(
        "--results", type=Path, default=Path("docs/positivity-voice-spike.md")
    )
    args = parser.parse_args()
    load_dotenv()
    from elevenlabs import ElevenLabs
    from elevenlabs.conversational_ai.conversation import Conversation
    from elevenlabs.conversational_ai.default_audio_interface import (
        DefaultAudioInterface,
    )

    voice_id = os.getenv("POSITIVITY_VOICE_ID")
    agent_id = os.getenv("ELEVENLABS_AGENT_ID")
    if not voice_id or not agent_id or not os.getenv("ELEVENLABS_API_KEY"):
        parser.error(
            "Set POSITIVITY_VOICE_ID, ELEVENLABS_AGENT_ID and ELEVENLABS_API_KEY in the environment"
        )
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    config = PositivityConfig(
        voice_id=voice_id,
        tts_model=os.getenv("POSITIVITY_TTS_MODEL", "eleven_flash_v2_5"),
    )

    def make(agent_response, user_transcript):
        return Conversation(
            client,
            agent_id,
            requires_auth=True,
            audio_interface=DefaultAudioInterface(),
            callback_agent_response=agent_response,
            callback_user_transcript=user_transcript,
        )

    options = ["A", "B", "C"] if args.option == "all" else [args.option]
    for option in options:
        result = run_option(option, client, config, make)
        save_results(args.results, [result])
    print(
        f"Saved operator observations to {args.results}; no delivery option is automatically approved."
    )


if __name__ == "__main__":
    main()
