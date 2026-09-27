"""Test the human harness without opening a microphone or calling a service."""

from types import SimpleNamespace

import pytest

from jarvis.positivity.config import PositivityConfig
from scripts import voice_spike


@pytest.mark.parametrize("option", ["A", "B", "C"])
def test_spike_options_record_only_operator_observations(monkeypatch, tmp_path, option):
    sessions = []

    class Conversation:
        def __init__(self, agent, user):
            self.agent = agent
            self.started = self.ended = 0

        def start_session(self):
            self.started += 1

        def end_session(self):
            self.ended += 1

        def send_user_message(self, text):
            self.agent("test response")

    def make(agent, user):
        session = Conversation(agent, user)
        sessions.append(session)
        return session

    monkeypatch.setattr(
        voice_spike,
        "ElevenLabsTTSDelivery",
        lambda *a, **k: SimpleNamespace(
            speak=lambda *a, **k: None, cancel=lambda: None
        ),
    )
    result = voice_spike.run_option(
        option, None, PositivityConfig(), make, prompt=lambda text: "unknown"
    )
    assert result["outcome"] == "completed"
    assert len(sessions) == (2 if option == "C" else 1)
    assert all(s.started == 1 and s.ended == 1 for s in sessions)
    path = tmp_path / "results.md"
    voice_spike.save_results(path, [result])
    text = path.read_text()
    assert "Human-run observations" in text
    assert "test response" not in text
