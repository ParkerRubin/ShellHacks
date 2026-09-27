"""Exercise the real robot script with camera/audio/network/serial adapters replaced."""

import runpy
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("enabled", [False, True])
def test_robot_tools_callbacks_and_look_hook(monkeypatch, enabled):
    import jarvis.memory

    memory = Mock(enabled=enabled)
    memory.presence.user_id = None
    monkeypatch.setattr(jarvis.memory, "build_memory", lambda: memory)
    monkeypatch.setattr("atexit.register", lambda *a: None)
    monkeypatch.setattr("threading.Thread", Mock())
    vision = Mock()
    vision.generate_content.return_value.text = "A robot"
    genai = SimpleNamespace(configure=Mock(), GenerativeModel=lambda model: vision)
    google = ModuleType("google")
    google.generativeai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.generativeai", genai)
    monkeypatch.setitem(
        sys.modules,
        "cv2",
        SimpleNamespace(
            IMWRITE_JPEG_QUALITY=1,
            imencode=lambda *a: (True, SimpleNamespace(tobytes=lambda: b"jpeg")),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "serial",
        SimpleNamespace(Serial=Mock(side_effect=OSError("no hardware"))),
    )
    monkeypatch.setitem(sys.modules, "elevenlabs", SimpleNamespace(ElevenLabs=Mock()))
    monkeypatch.setitem(
        sys.modules,
        "elevenlabs.conversational_ai",
        ModuleType("elevenlabs.conversational_ai"),
    )
    registered = {}
    conversation = Mock()
    constructor = Mock(return_value=conversation)
    monkeypatch.setitem(
        sys.modules,
        "elevenlabs.conversational_ai.conversation",
        SimpleNamespace(
            Conversation=constructor,
            ClientTools=lambda: SimpleNamespace(
                register=lambda name, fn: registered.update({name: fn})
            ),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "elevenlabs.conversational_ai.default_audio_interface",
        SimpleNamespace(DefaultAudioInterface=Mock()),
    )
    runtime = runpy.run_path("robot.py")
    assert set(registered) == (
        {"look", "recall", "remember_me", "forget_me"} if enabled else {"look"}
    )
    callbacks = constructor.call_args.kwargs
    callbacks["callback_user_transcript"]("hello")
    callbacks["callback_agent_response"]("hi")
    memory.ingestor.on_user.assert_called_once_with("hello")
    memory.ingestor.on_agent.assert_called_once_with("hi")
    conversation.start_session.assert_called_once()
    assert runtime["look"]({}) == "I can't see anything right now."
    runtime["look"].__globals__["latest_frame"] = object()
    assert runtime["look"]({}) == "A robot"
    memory.ingestor.on_gemini.assert_called_once_with("A robot")
