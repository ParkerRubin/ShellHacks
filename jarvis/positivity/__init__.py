"""Optional positivity: disabled by default; no imports with runtime side effects."""

import logging
import os


class NullPositivity:
    enabled = False

    def __init__(self):
        self.bus = self

    def publish(self, *args):
        return False

    def on_user_transcript(self, text):
        return True

    def close(self):
        pass


def build_positivity(
    client=None,
    gemini=None,
    model="gemini-3.5-flash",
    *,
    config=None,
    voice=None,
    describer=None,
    local=None,
    clock=None,
    sleep=None,
):
    if config is None and os.getenv("POSITIVITY_ENABLED", "false").lower() == "false":
        return NullPositivity()
    try:
        from .config import PositivityConfig

        config = config or PositivityConfig.from_env()
        if not config.enabled:
            return NullPositivity()
        from .describers import GeminiDescriber, LocalTagDescriber
        from .engine import EncouragementEngine
        from .voice import ElevenLabsTTSDelivery

        voice = voice if voice is not None else ElevenLabsTTSDelivery(client, config)
        describer = (
            describer
            if describer is not None
            else GeminiDescriber(gemini, model, config.face_timeout_s)
        )
        local = local if local is not None else LocalTagDescriber()
        options = {}
        if clock is not None:
            options["clock"] = clock
        if sleep is not None:
            options["sleep"] = sleep
        engine = EncouragementEngine(config, describer, local, voice, **options)
        engine.start()
        return engine
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "positivity_disabled type=%s", type(exc).__name__
        )
        return NullPositivity()
