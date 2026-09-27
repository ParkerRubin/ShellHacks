"""Memory and positivity hooks in jarvis.py, with the camera, voice and network left out."""

import importlib.util
import json
import time
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    spec = importlib.util.spec_from_file_location("jarvis_app", "jarvis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # main() is not run: no camera, threads or voice session
    module.MEMORY = Mock(enabled=True)
    module.MEMORY.presence.user_id = None
    module.POSITIVITY = Mock(enabled=True)
    module.POSITIVITY.on_user_transcript.return_value = True
    yield module
    try:
        module.SESSION.rmdir()  # importing creates an empty captures folder
    except OSError:
        pass


def test_every_tool_is_declared_for_the_agent(app):
    declared = {t["name"] for t in json.loads(Path("tools.json").read_text())}
    assert {"recall", "remember_me", "forget_me"} <= set(app.TOOLS)
    assert set(app.TOOLS) == declared


def test_transcripts_reach_memory(app):
    app.on_user("hello")
    app.on_agent("hi")
    app.MEMORY.ingestor.on_user.assert_called_once_with("hello")
    app.MEMORY.ingestor.on_agent.assert_called_once_with("hi")


def test_positivity_opt_out_keeps_transcript_out_of_memory(app):
    app.POSITIVITY.on_user_transcript.return_value = False
    app.on_user("stop the compliments")
    app.MEMORY.ingestor.on_user.assert_not_called()


def test_look_result_is_ingested(app, monkeypatch):
    monkeypatch.setattr(app, "current_view", lambda: np.zeros((10, 10, 3), np.uint8))
    monkeypatch.setattr(app, "gemini", lambda *a, **k: "A red mug")
    assert app.TOOLS["look"]({}) == "A red mug"
    app.MEMORY.ingestor.on_gemini.assert_called_once_with("A red mug")


def test_memory_tools_pass_through(app):
    app.MEMORY.retriever.recall.return_value = "You talked about servos."
    assert app.TOOLS["recall"]({"query": "servos"}) == "You talked about servos."
    app.TOOLS["remember_me"]({"confirmed": "true", "name": "Sam"})
    # The raw value goes through untouched; ConsentManager only accepts a real True.
    app.MEMORY.consent.remember.assert_called_once_with("true", "Sam")
    app.TOOLS["forget_me"]({})
    app.MEMORY.consent.forget.assert_called_once()


def test_frames_are_fed_with_pixel_boxes(app):
    frame = np.zeros((100, 200, 3), np.uint8)
    now = time.time()
    box = (0.1, 0.2, 0.3, 0.4)
    app.S.faces, app.S.face_target, app.S.last_face_t = [box], box, now
    app.feed_memory_and_positivity(frame, now)
    app.POSITIVITY.bus.publish.assert_called_once_with(frame, [(20, 20, 60, 40)])
    app.MEMORY.identifier.submit.assert_called_once_with(frame, (20, 20, 60, 40))

    # Lock held from an earlier frame: nobody was actually seen now.
    app.feed_memory_and_positivity(frame, now + 1)
    app.MEMORY.identifier.submit.assert_called_with(frame, None)


def test_feed_survives_failures(app):
    app.POSITIVITY.bus.publish.side_effect = RuntimeError("bus down")
    app.MEMORY.identifier.submit.side_effect = RuntimeError("db down")
    app.S.faces, app.S.face_target = [], None
    app.feed_memory_and_positivity(np.zeros((10, 10, 3), np.uint8), time.time())
