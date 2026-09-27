"""Exercise the real robot script with camera/audio/network/serial adapters replaced."""

import runpy
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("positivity_enabled", [False, True])
def test_robot_tools_callbacks_and_look_hook(monkeypatch, enabled, positivity_enabled):
    import jarvis.memory
    import jarvis.positivity
    import jarvis.positivity.describers  # Load adapters before cv2 is mocked.
    from jarvis.positivity.config import PositivityConfig
    from jarvis.positivity.models import FaceDescription

    monkeypatch.setenv("POSITIVITY_ENABLED", str(positivity_enabled).lower())
    real_builder = jarvis.positivity.build_positivity
    fake_voice = SimpleNamespace(speak=lambda *a, **k: None, speaking=lambda: False)
    fake_describer = SimpleNamespace(describe=lambda *a, **k: FaceDescription(()))

    def builder(client, model):
        return real_builder(
            client,
            model,
            config=PositivityConfig.from_env(),
            voice=fake_voice,
            describer=fake_describer,
            local=fake_describer,
        )

    monkeypatch.setattr(jarvis.positivity, "build_positivity", builder)

    memory = Mock(enabled=enabled)
    memory.presence.user_id = None
    monkeypatch.setattr(jarvis.memory, "build_memory", lambda: memory)
    monkeypatch.setattr("atexit.register", lambda *a: None)
    threads = Mock()
    monkeypatch.setattr("threading.Thread", threads)
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
    assert runtime["positivity"].enabled is positivity_enabled
    assert threads.call_count == (2 if positivity_enabled else 1)
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

    # Run the real camera loop once and check baseline pan, even if publishing fails.
    import numpy as np

    camera_frame = np.zeros((100, 200, 3), dtype=np.uint8)
    camera = SimpleNamespace(
        read=Mock(side_effect=[(True, camera_frame), (False, None)])
    )
    cv = SimpleNamespace(
        VideoCapture=lambda index: camera,
        CascadeClassifier=lambda path: SimpleNamespace(
            detectMultiScale=lambda *a, **k: [(20, 10, 40, 40)]
        ),
        data=SimpleNamespace(haarcascades=""),
        COLOR_BGR2GRAY=1,
        cvtColor=lambda frame, mode: frame,
        rectangle=lambda *a: None,
        imshow=lambda *a: None,
        waitKey=lambda n: 0,
    )
    globals_ = runtime["camera_loop"].__globals__
    globals_["cv2"] = cv
    pan = []
    globals_["drive_servo"] = pan.append
    if positivity_enabled:
        runtime["positivity"].bus.publish = Mock(
            side_effect=RuntimeError("publisher failure")
        )
    runtime["camera_loop"]()
    assert pan == [160 - ((20 + 40 // 2) / 200) * 140]
    runtime["positivity"].close()
