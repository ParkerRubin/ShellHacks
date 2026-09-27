"""Option A: separate PCM playback. UNVERIFIED until the human hardware spike.

Callback suppression cannot prevent the server-side agent from hearing speaker
output; echo/device conflict assessment is mandatory before public use.
"""

import re
import threading
import time
from typing import Protocol


class VoiceDelivery(Protocol):
    def speak(self, text: str, *, style: str) -> None: ...
    def speaking(self) -> bool: ...


def sentences(text):
    return tuple(
        s.strip() for s in re.findall(r"[^.!?]+(?:[.!?]+|$)", text) if s.strip()
    )


def play_pcm(chunks, cancelled):
    import sounddevice as sd

    with sd.RawOutputStream(samplerate=24000, channels=1, dtype="int16") as stream:
        pending = b""
        for chunk in chunks:
            if cancelled.is_set():
                return
            pending += chunk
            size = len(pending) // 2 * 2
            if size:
                stream.write(pending[:size])
                pending = pending[size:]


class ElevenLabsTTSDelivery:
    verified_on_hardware = False

    def __init__(self, client, config, player=play_pcm, sleep=time.sleep):
        if not config.voice_id:
            raise ValueError(
                "POSITIVITY_VOICE_ID must be set to the agent voice for option A"
            )
        self.client, self.config, self.player, self.sleep = (
            client,
            config,
            player,
            sleep,
        )
        self._speaking = threading.Event()
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.notice_cache = {}

    def _stream(self, text, style):
        return self.client.text_to_speech.stream(
            voice_id=self.config.voice_id,
            model_id="eleven_flash_v2_5"
            if style == "notice"
            else self.config.tts_model,
            output_format="pcm_24000",
            text=text,
            voice_settings={
                "stability": 0.4,
                "similarity_boost": 0.75,
                "style": 0.4,
                "speed": 0.95,
            },
            request_options={"timeout_in_seconds": 10, "max_retries": 0},
        )

    def prepare_notice(self, text):
        # Called on the worker at startup, never on the camera/callback thread.
        for sentence in sentences(text):
            data = bytearray()
            for chunk in self._stream(sentence, "notice"):
                if self.cancelled.is_set():
                    return
                data.extend(chunk)
                if len(data) > 24000 * 2 * 30:
                    raise ValueError("Notice audio exceeds cache budget")
            self.notice_cache[sentence] = bytes(data)

    def speak(self, text, *, style):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("Voice is busy")
        self._speaking.set()
        try:
            parts = sentences(text)
            for index, sentence in enumerate(parts):
                if self.cancelled.is_set():
                    return
                if style == "notice" and sentence in self.notice_cache:
                    chunks = iter((self.notice_cache[sentence],))
                else:
                    chunks = self._stream(sentence, style)
                self.player(chunks, self.cancelled)
                if index + 1 < len(parts) and not self.cancelled.is_set():
                    self.sleep(0.350)
            if style == "remark" and not self.cancelled.is_set():
                self.sleep(0.600)
        finally:
            self._speaking.clear()
            self.lock.release()

    def reset(self):
        if self.speaking():
            raise RuntimeError("Previous playback is still active")
        self.cancelled.clear()

    def speaking(self):
        return self._speaking.is_set()

    def cancel(self):
        self.cancelled.set()
