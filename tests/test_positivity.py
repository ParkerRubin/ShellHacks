"""Properties 1–10 with no API calls, devices, identities or real face images."""

import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from jarvis.positivity import NullPositivity, build_positivity
from jarvis.positivity.bank import TEMPLATES, AffirmationBank
from jarvis.positivity.bus import FaceBus
from jarvis.positivity.config import PositivityConfig
from jarvis.positivity.cropper import FaceCropper, FaceInput
from jarvis.positivity.describers import GeminiDescriber, LocalTagDescriber
from jarvis.positivity.engine import EncouragementEngine
from jarvis.positivity.guard import TrackAssociator, TriggerGuard
from jarvis.positivity.lexicon import ALLOWED_FEATURES, DENY_CATEGORIES
from jarvis.positivity.models import FaceDescription, Observation
from jarvis.positivity.validator import RemarkValidator
from jarvis.positivity.voice import ElevenLabsTTSDelivery

OBS = (
    Observation("smile", "A warm smile"),
    Observation("eyes", "An engaged gaze"),
    Observation("expression", "An open expression"),
)
GOOD = FaceDescription(
    OBS, "Your smile brings warmth. Your eyes look engaged.", 0.5, 0.5
)


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.hook = lambda: None
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.value

    def advance(self, value):
        with self.lock:
            self.value += value

    def sleep(self, seconds):
        self.advance(seconds)
        self.hook()
        time.sleep(
            0.00005
        )  # Yield to bounded job threads; no wall-time deadlines in logic tests.


class FakeVoice:
    def __init__(self, clock):
        self.clock = clock
        self.lines = []
        self.active = False
        self.fail = False

    def speak(self, text, *, style):
        self.active = True
        try:
            if self.fail:
                raise RuntimeError("voice unavailable")
            self.lines.append((style, text, self.clock()))
        finally:
            self.active = False

    def speaking(self):
        return self.active

    def cancel(self):
        pass


class FakeDescriber:
    def __init__(self, clock, value=GOOD):
        self.clock, self.value = clock, value
        self.calls = []
        self.fail = False

    def describe(self, face, feedback=()):
        assert isinstance(face, FaceInput)
        self.calls.append((face, self.clock(), feedback))
        if self.fail:
            raise ValueError("describer unavailable")
        return self.value


def setup_engine(count=1, mode="crop"):
    clock = FakeClock()
    voice = FakeVoice(clock)
    external = FakeDescriber(clock)
    local = FakeDescriber(clock)
    engine = EncouragementEngine(
        PositivityConfig(enabled=True, privacy_mode=mode),
        external,
        local,
        voice,
        clock=clock,
        sleep=clock.sleep,
    )
    frame = np.zeros((100, 300, 3), np.uint8)
    boxes = [(i * 95 + 5, 20, 40, 40) for i in range(count)]
    for i, (x, y, w, h) in enumerate(boxes):
        frame[y : y + h, x : x + w] = 30 + i * 60
    clock.hook = lambda: engine.bus.publish(frame, boxes)
    clock.hook()
    engine.tick()
    for _ in range(4):
        clock.advance(0.25)
        clock.hook()
        engine._pump()
    clock.advance(0.01)
    clock.hook()
    return engine, clock, voice, external, local, frame, boxes


@given(
    st.sampled_from([w for words in DENY_CATEGORIES.values() for w in words]),
    st.booleans(),
    st.booleans(),
)
def test_property1_sensitive_terms_blocked_in_remark_and_details(
    word, uppercase, in_detail
):
    word = word.upper() if uppercase else word
    description = replace(GOOD, remark=GOOD.remark + " " + word)
    if in_detail:
        description = replace(GOOD, observations=OBS + (Observation("presence", word),))
    assert not RemarkValidator().validate(description).ok


@given(st.integers(0, 2), st.sampled_from(["You are amazing.", "Your smile is warm."]))
def test_property2_breadth_and_specificity(count, text):
    assert not RemarkValidator().validate(replace(GOOD, observations=OBS[:count])).ok
    assert not RemarkValidator().validate(replace(GOOD, remark=text)).ok


@given(st.sets(st.sampled_from(sorted(ALLOWED_FEATURES)), max_size=5))
def test_property3_bank_validates_sparse_evidence_without_invention(features):
    observations = tuple(Observation(f, "A welcoming detail") for f in features)
    validator = RemarkValidator()
    bank = AffirmationBank(validator)
    for _ in range(5):
        result = bank.compose(observations)
        assert validator.validate(result).ok
        assert {o.feature for o in result.observations} <= features
        if len(features) < 3:
            assert result.generic
    assert all(len(values) >= 5 for values in TEMPLATES.values())


@given(
    st.integers(20, 500),
    st.integers(20, 500),
    st.floats(0, 0.7, allow_nan=False),
    st.floats(0, 0.7, allow_nan=False),
)
@settings(max_examples=30)
def test_property4_only_bounded_metadata_free_crops(height, width, fx, fy):
    frame = np.zeros((height, width, 3), np.uint8)
    original = frame.copy()
    crop = FaceCropper().crop_face(
        frame,
        (int(width * fx), int(height * fy), max(1, width // 4), max(1, height // 4)),
    )
    assert b"Exif\x00\x00" not in crop
    image = cv2.imdecode(np.frombuffer(crop, np.uint8), cv2.IMREAD_COLOR)
    assert max(image.shape[:2]) <= 256
    assert np.array_equal(frame, original)
    model = Mock()
    with pytest.raises(TypeError):
        GeminiDescriber(model).describe(frame)
    model.models.generate_content.assert_not_called()
    with pytest.raises(ValueError):
        FaceInput(
            jpeg=cv2.imencode(".jpg", np.zeros((300, 300, 3), np.uint8))[1].tobytes()
        )


@given(
    st.lists(
        st.floats(min_value=0.01, max_value=0.49, allow_nan=False),
        min_size=2,
        max_size=30,
    )
)
def test_property5_guard_dwell_cooldown_and_track_loss(steps):
    clock = FakeClock()
    assoc = TrackAssociator()
    guard = TriggerGuard(PositivityConfig(enabled=True), clock)
    tracks = assoc.update([(0, 0, 40, 40)], clock())
    assert guard.candidates(tracks) == []
    begun = None
    for dt in steps:
        clock.advance(dt)
        tracks = assoc.update([(1, 0, 40, 40)], clock())
        candidates = guard.candidates(tracks)
        if candidates:
            assert clock() >= 1
            assert begun is None
            begun = clock()
            guard.begin(candidates)
            guard.finish()
    clock.advance(6)
    tracks = assoc.update([(1, 0, 40, 40)], clock())
    assert tracks[0].id > 1
    assert guard.candidates(tracks) == []  # New track must dwell again.


@given(
    st.sampled_from(["no", "NO THANKS", "please stop", "don't", "leave me alone"]),
    st.floats(min_value=0.0, max_value=1.9, allow_nan=False),
)
@settings(max_examples=15, deadline=None)
def test_property6_notice_opt_out_precedes_every_egress(word, delay):
    engine, clock, voice, external, local, frame, boxes = setup_engine()
    old_hook = clock.hook

    def hook():
        old_hook()
        if (
            engine.guard.state == "NOTICE"
            and engine.guard.notice_until is not None
            and clock() >= engine.guard.notice_until - engine.config.opt_out_s + delay
        ):
            engine.on_user_transcript(word)

    clock.hook = hook
    engine.tick()
    assert external.calls == []
    assert not any(line[0] == "remark" for line in voice.lines)
    assert engine.guard.state == "OPTED_OUT"
    assert engine.mood.opt_outs == 1
    if "stop" in word:
        clock.advance(30)
        old_hook()
        engine.tick()
        assert external.calls == []


def test_notice_opt_out_even_while_notice_is_speaking():
    engine, clock, voice, external, *_ = setup_engine()
    original = voice.speak

    def speaking_notice(text, *, style):
        original(text, style=style)
        voice.active = True
        engine.on_user_transcript("no thanks")
        voice.active = False

    voice.speak = speaking_notice
    engine.tick()
    assert not external.calls
    assert all(style == "notice" for style, _, _ in voice.lines)


@given(st.integers(1, 3), st.sampled_from(["crop", "tags_only"]))
@settings(max_examples=6, deadline=None)
def test_property7_each_face_is_independent_and_ordered(count, mode):
    engine, clock, voice, external, local, frame, boxes = setup_engine(count, mode)
    engine.tick()
    assert len(external.calls) == count
    assert all(at >= 1.01 + engine.config.opt_out_s for _, at, _ in external.calls)
    remarks = [text for style, text, _ in voice.lines if style == "remark"]
    assert len(remarks) == count
    assert len(engine.mood.samples) == count
    assert len(local.calls) == 2 * count
    if mode == "crop":
        means = sorted(
            round(
                float(
                    cv2.imdecode(
                        np.frombuffer(face.jpeg, np.uint8), cv2.IMREAD_COLOR
                    ).mean()
                )
            )
            for face, _, _ in external.calls
        )
        assert len(set(means)) == count
    else:
        assert all(face.jpeg is None and face.tags for face, _, _ in external.calls)


@pytest.mark.parametrize("where", ["describer", "voice", "validator", "mood"])
def test_property8_exception_isolation(where):
    engine, clock, voice, external, local, frame, boxes = setup_engine()
    if where == "describer":
        external.fail = True
    if where == "voice":
        voice.fail = True
    if where == "validator":
        engine.validator.validate = Mock(side_effect=RuntimeError)
    if where == "mood":
        engine.mood.record = Mock(side_effect=RuntimeError)
    engine.tick()  # Never escapes into caller; cooldown allows later rounds.
    assert engine.guard.state in ("COOLDOWN", "OPTED_OUT")
    assert engine.on_user_transcript("hello") in (True, False)
    assert engine.bus.publish(frame, boxes)
    if where != "mood":
        assert not any(style == "remark" for style, _, _ in voice.lines)


@given(
    st.lists(
        st.sampled_from(
            [
                "Your smile brings warmth.",
                "Your eyes look engaged!",
                "Your presence is welcome?",
            ]
        ),
        min_size=1,
        max_size=3,
    )
)
def test_property10_voice_pacing_and_text(parts):
    text = " ".join(parts)
    sent, pauses, played = [], [], []

    def stream(**kwargs):
        sent.append(kwargs)
        return iter([b"\x00\x00"])

    voice = ElevenLabsTTSDelivery(
        SimpleNamespace(text_to_speech=SimpleNamespace(stream=stream)),
        PositivityConfig(voice_id="test"),
        player=lambda chunks, cancel: played.extend(chunks),
        sleep=pauses.append,
    )
    voice.speak(text, style="remark")
    assert " ".join(s["text"] for s in sent) == text
    assert pauses == [0.35] * (len(parts) - 1) + [0.6]
    assert not voice.speaking()
    assert len(played) == len(parts)


def test_config_defaults_disabled_no_threads(monkeypatch):
    monkeypatch.delenv("POSITIVITY_ENABLED", raising=False)
    constructor = Mock(side_effect=AssertionError("thread started"))
    monkeypatch.setattr(threading, "Thread", constructor)
    assert isinstance(build_positivity(), NullPositivity)
    assert not PositivityConfig.from_env({}).enabled
    assert not PositivityConfig.from_env(
        {"POSITIVITY_ENABLED": "false", "POSITIVITY_DWELL_S": "invalid"}
    ).enabled
    constructor.assert_not_called()


def test_bus_latest_copy_and_drops_when_locked():
    bus = FaceBus()
    frame = np.ones((5, 5, 3), np.uint8)
    assert bus.publish(frame, [(1, 1, 2, 2)])
    frame[:] = 2
    assert bus.publish(frame, [])
    frame[:] = 3
    event = bus.take()
    assert np.all(event.frame == 2) and event.faces == ()
    assert bus.take() is None
    with bus.lock:
        assert not bus.publish(frame, [])


@pytest.mark.parametrize("response", ["{", "{}", '{"observations": [], "remark": 3}'])
def test_malformed_gemini_is_safe_failure(response):
    model = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **k: SimpleNamespace(text=response)
        )
    )
    with pytest.raises((ValueError, KeyError, TypeError)):
        GeminiDescriber(model).describe(FaceInput(tags=("smile",)))


def test_gemini_tags_only_and_fixed_json_schema():
    captured = []

    def generate(model, contents, config):
        captured.append((contents, config))
        return SimpleNamespace(
            text=json.dumps(
                {
                    "observations": [vars(o) for o in OBS],
                    "remark": GOOD.remark,
                    "smile_score": 0.5,
                    "expression_score": 0.5,
                }
            )
        )

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    description = GeminiDescriber(client).describe(
        FaceInput(tags=("smile", "eyes", "expression"))
    )
    assert description.remark == GOOD.remark
    assert all(isinstance(part, str) for part in captured[0][0])
    assert captured[0][1].http_options.timeout == 2500
    assert captured[0][1].response_mime_type == "application/json"


def test_walk_away_or_stale_camera_prevents_egress():
    for empty in (True, False):
        engine, clock, voice, external, local, frame, boxes = setup_engine()
        clock.hook = (lambda: engine.bus.publish(frame, [])) if empty else lambda: None
        engine.tick()
        assert external.calls == []
        assert not any(style == "remark" for style, _, _ in voice.lines)


def test_invalid_model_remark_retried_once_then_local_bank():
    engine, clock, voice, external, *_ = setup_engine()
    external.value = replace(GOOD, remark="You look young.")
    engine.tick()
    assert len(external.calls) == 2
    assert external.calls[1][2]
    assert all("young" not in text for _, text, _ in voice.lines)
    assert any(style == "remark" for style, _, _ in voice.lines)


def test_notice_cache_in_memory_no_repeat_synthesis():
    stream = Mock(return_value=iter([b"\x00\x00"]))
    voice = ElevenLabsTTSDelivery(
        SimpleNamespace(text_to_speech=SimpleNamespace(stream=stream)),
        PositivityConfig(voice_id="test"),
        player=lambda chunks, cancel: list(chunks),
        sleep=lambda s: None,
    )
    voice.prepare_notice("Hello.")
    voice.speak("Hello.", style="notice")
    voice.speak("Hello.", style="notice")
    assert stream.call_count == 1


def test_local_blank_crop_has_only_presence():
    face = FaceInput(
        jpeg=FaceCropper().crop_face(
            np.zeros((100, 100, 3), np.uint8), (10, 10, 40, 40)
        )
    )
    result = LocalTagDescriber().describe(face)
    assert result.source == "local" and result.remark is None
    assert {o.feature for o in result.observations} == {"presence"}


def test_regression_corpus():
    corpus = json.loads(Path("tests/data/remarks_corpus.json").read_text())
    for item in corpus["cases"]:
        description = FaceDescription(
            tuple(Observation(**o) for o in item["observations"]), item["remark"]
        )
        assert RemarkValidator().validate(description).ok == item["expected"], item[
            "id"
        ]


def test_walkaway_is_absorbing_even_when_same_track_returns_during_notice():
    engine, clock, voice, external, local, frame, boxes = setup_engine()

    def hook():
        # Lost for >0.5 s, but returns before the 2 s window closes.
        engine.bus.publish(frame, [] if 1.2 < clock() < 1.9 else boxes)

    clock.hook = hook
    engine.tick()
    assert external.calls == []
    assert not any(style == "remark" for style, _, _ in voice.lines)


def test_stale_external_completion_cannot_speak_after_timeout():
    engine, clock, voice, external, local, frame, boxes = setup_engine()
    release = threading.Event()
    started = threading.Event()

    def hung(face, feedback=()):
        started.set()
        release.wait(3)
        return GOOD

    external.describe = hung
    try:
        engine.tick()
        assert started.is_set()
        assert not any(style == "remark" for style, _, _ in voice.lines)
        assert engine.ticket is None
    finally:
        release.set()
    time.sleep(0.01)
    assert not any(style == "remark" for style, _, _ in voice.lines)


def test_per_face_content_and_delivery_order():
    engine, clock, voice, external, local, frame, boxes = setup_engine(3)
    observed = []

    def describe(face, feedback=()):
        value = float(
            cv2.imdecode(np.frombuffer(face.jpeg, np.uint8), cv2.IMREAD_COLOR).mean()
        )
        observed.append(value)
        variant = "warm" if value < 30 else "welcoming" if value < 60 else "cheerful"
        return replace(
            GOOD, remark=f"Your smile feels {variant}. Your eyes look engaged."
        )

    external.describe = describe
    engine.tick()
    remarks = [text for style, text, _ in voice.lines if style == "remark"]
    assert len(observed) == 3
    assert remarks == [
        f"Your smile feels {word}. Your eyes look engaged."
        for word in ("warm", "welcoming", "cheerful")
    ]


def test_guard_global_rate_limit_whole_words_and_session_stop():
    clock = FakeClock()
    assoc = TrackAssociator()
    guard = TriggerGuard(PositivityConfig(enabled=True), clock)
    tracks = assoc.update([(0, 0, 20, 20)], clock())
    for _ in range(5):
        clock.advance(0.25)
        tracks = assoc.update([(0, 0, 20, 20)], clock())
    guard.begin(guard.candidates(tracks))
    guard.on_transcript("nobody knows a stopwatch")
    assert not guard.cancelled.is_set()
    guard.finish()
    clock.advance(6)
    tracks = assoc.update([(0, 0, 20, 20)], clock())
    for _ in range(5):
        clock.advance(0.25)
        tracks = assoc.update([(0, 0, 20, 20)], clock())
    assert guard.candidates(tracks) == []
    guard.on_transcript("stop")
    clock.advance(30)
    assert guard.candidates(tracks) == []


def test_mood_uses_same_local_instrument_and_fresh_after_frame():
    engine, clock, voice, external, local, frame, boxes = setup_engine()
    count = []

    def describe(face, feedback=()):
        count.append(clock())
        score = 0.2 if len(count) == 1 else 0.8
        return replace(
            GOOD, remark=None, smile_score=score, expression_score=score, source="local"
        )

    local.describe = describe
    engine.tick()
    sample = engine.mood.samples[0]
    assert sample.before == (0.2, 0.2)
    assert sample.after == (0.8, 0.8)
    assert sample.delta == pytest.approx((0.6, 0.6))
    assert sample.dwell_after_remark_s >= 2
    assert count[0] < external.calls[0][1] < count[1]


def test_worker_survives_tick_error_and_callback_error():
    engine, clock, voice, external, local, frame, boxes = setup_engine()
    count = []

    def take():
        count.append(1)
        if len(count) == 1:
            raise RuntimeError("bus failure")
        engine.stop.set()
        return None

    engine.bus.take = take
    engine.start()
    engine.worker.join(1)
    assert len(count) >= 2 and not engine.worker.is_alive()
    voice.speaking = Mock(side_effect=ValueError)
    assert engine.on_user_transcript("hello") is True
    assert engine.guard.cancelled.is_set()
