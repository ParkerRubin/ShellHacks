"""Synchronous round orchestration with bounded daemon jobs and fresh-frame gating."""

import logging
import threading
import time
from dataclasses import dataclass, field

from .bank import AffirmationBank
from .bus import FaceBus
from .cropper import FaceCropper, FaceInput
from .guard import TrackAssociator, TriggerGuard
from .mood import MoodTracker
from .validator import RemarkValidator

log = logging.getLogger(__name__)


@dataclass
class Job:
    done: threading.Event = field(default_factory=threading.Event)
    value: object = None
    error: bool = False
    completed_at: float | None = None


class EncouragementEngine:
    enabled = True

    def __init__(
        self,
        config,
        describer,
        local,
        voice,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
        bus=None,
        mood=None,
        validator=None,
    ):
        self.config, self.describer, self.local, self.voice = (
            config,
            describer,
            local,
            voice,
        )
        self.clock, self.sleep = clock, sleep
        self.bus = bus if bus is not None else FaceBus(clock)
        self.associator = TrackAssociator()
        self.guard = TriggerGuard(config, clock)
        self.cropper = FaceCropper()
        self.validator = validator or RemarkValidator(config.min_referenced)
        self.bank = AffirmationBank(self.validator)
        self.mood = mood if mood is not None else MoodTracker()
        self.stop = threading.Event()
        self.face_slots = threading.BoundedSemaphore(3)
        self.voice_slots = threading.BoundedSemaphore(1)
        self.latest = None
        self.worker = None
        self.ticket = None
        self.round_dropped = set()

    def _start_job(self, fn, slots):
        if not slots.acquire(blocking=False):
            raise RuntimeError("Positivity job capacity exhausted")
        job = Job()

        def run():
            try:
                job.value = fn()
            except Exception as exc:
                job.error = True
                log.warning("positivity_job_failed type=%s", type(exc).__name__)
            finally:
                job.completed_at = self.clock()
                slots.release()
                job.done.set()

        try:
            threading.Thread(target=run, name="positivity-job", daemon=True).start()
        except Exception:
            slots.release()
            raise
        return job

    def _pump(self):
        if self.guard.state in ("NOTICE", "ENGAGED"):
            for track_id in self.guard.round_ids:
                track = self.associator.tracks.get(track_id)
                if track is None or self.clock() - track.last_seen >= 0.5:
                    self.round_dropped.add(track_id)
        event = self.bus.take()
        if event is not None:
            if event.ts <= self.clock() and (
                self.latest is None or event.ts >= self.latest.ts
            ):
                self.latest = event
                self.associator.update(event.faces, event.ts)
        # Expire tracks even when the camera stops delivering events.
        self.associator.tracks = {
            k: t
            for k, t in self.associator.tracks.items()
            if self.clock() - t.last_seen < 5
        }
        self.guard.used.intersection_update(self.associator.tracks)
        if self.latest and self.clock() - self.latest.ts >= 5:
            self.latest = None

    def _visible(self):
        return [
            t
            for t in self.associator.tracks.values()
            if self.clock() - t.last_seen < 0.5
        ]

    def _allowed(self, track_id, ticket):
        track = self.associator.tracks.get(track_id)
        return (
            ticket.is_set()
            and track_id not in self.round_dropped
            and not self.stop.is_set()
            and not self.guard.stopped.is_set()
            and not self.guard.cancelled.is_set()
            and track is not None
            and self.clock() - track.last_seen < 0.5
        )

    def _wait_job(self, job, timeout, ticket, *, deadline=None):
        deadline = self.clock() + timeout if deadline is None else deadline
        while not job.done.is_set():
            self._pump()
            if (
                self.stop.is_set()
                or self.guard.cancelled.is_set()
                or not ticket.is_set()
            ):
                raise RuntimeError("Round cancelled")
            if self.clock() >= deadline:
                raise TimeoutError("Positivity job exceeded deadline")
            self.sleep(0.01)
        if job.completed_at is not None and job.completed_at > deadline:
            raise TimeoutError("Positivity job completed after deadline")
        if job.error:
            raise RuntimeError("Positivity job failed")
        return job.value

    def _wait_until(self, deadline, ticket):
        while self.clock() < deadline:
            self._pump()
            if (
                self.stop.is_set()
                or self.guard.cancelled.is_set()
                or not ticket.is_set()
            ):
                return False
            self.sleep(min(0.01, max(0, deadline - self.clock())))
        self._pump()
        return not self.guard.cancelled.is_set() and not self.stop.is_set()

    def _input(self, track):
        if not self.latest or self.clock() - self.latest.ts >= 0.5:
            raise ValueError("No fresh camera sample")
        return FaceInput(jpeg=self.cropper.crop_face(self.latest.frame, track.box))

    def _describe(self, face, track_id, ticket):
        if not self._allowed(track_id, ticket) or self.guard.state != "ENGAGED":
            return None
        description = self.describer.describe(face)
        verdict = self.validator.validate(description)
        if not verdict.ok:
            if not self._allowed(track_id, ticket):
                return None
            description = self.describer.describe(face, feedback=verdict.reasons)
            if not self.validator.validate(description).ok:
                return None  # Worker composes bank from local evidence, never rejected model details.
        return description

    def run_round(self, faces):
        """Run one round. Caller/worker keeps the bus fresh through every wait."""
        ticket = threading.Event()
        ticket.set()
        self.ticket = ticket
        try:
            eligible = {t.id for t in self.guard.candidates(self._visible())}
            faces = sorted(
                [t for t in faces if t.id in eligible], key=lambda t: t.box[0]
            )[: self.config.max_faces]
            if not self.guard.begin(faces):
                return
            self.round_dropped = set()
            reset = getattr(self.voice, "reset", None)
            if reset:
                reset()

            def speak_notice():
                if (
                    ticket.is_set()
                    and not self.stop.is_set()
                    and not self.guard.stopped.is_set()
                    and not self.guard.cancelled.is_set()
                ):
                    self.voice.speak(self.config.notice_text, style="notice")

            notice = self._start_job(speak_notice, self.voice_slots)
            before = {}
            for track in faces:
                face = self._input(track)
                job = self._start_job(
                    lambda face=face: self.local.describe(face), self.face_slots
                )
                before[track.id] = self._wait_job(
                    job, self.config.face_timeout_s, ticket
                )
            self._wait_job(notice, self.config.voice_timeout_s, ticket)
            self.guard.notice_finished()
            if (
                not self._wait_until(self.guard.notice_until, ticket)
                or not self.guard.engage()
            ):
                return
            # This is the first point where a face-derived input may reach an
            # external adapter. Each worker receives one independent crop/tags.
            jobs = []
            for track in faces:
                if not self._allowed(track.id, ticket):
                    continue
                face = (
                    self._input(track)
                    if self.config.privacy_mode == "crop"
                    else FaceInput.from_tags(before[track.id].observations)
                )
                job = self._start_job(
                    lambda face=face, track=track: self._describe(
                        face, track.id, ticket
                    ),
                    self.face_slots,
                )
                jobs.append((track, job, self.clock() + self.config.face_timeout_s))
            ready = []
            # Resolve all jobs before speaking; an exception makes the round silent.
            for track, job, deadline in jobs:
                description = self._wait_job(job, 0, ticket, deadline=deadline)
                if description is None:
                    description = self.bank.compose(before[track.id].observations)
                if not self.validator.validate(description).ok:
                    raise ValueError("Final remark failed validation")
                ready.append((track, description))
            spoken = []
            for track, description in ready:
                self._pump()
                if not self._allowed(track.id, ticket):
                    continue

                def speak(track=track, description=description):
                    if self._allowed(track.id, ticket):
                        self.voice.speak(description.remark, style="remark")

                job = self._start_job(speak, self.voice_slots)
                self._wait_job(job, self.config.voice_timeout_s, ticket)
                self.mood.people_engaged += 1
                spoken.append(track)
            remark_end = self.clock()
            if spoken and self._wait_until(remark_end + 2, ticket):
                for track in spoken:
                    if self._allowed(track.id, ticket):
                        # Fresh frame, same local instrument for both scores.
                        face = self._input(track)
                        job = self._start_job(
                            lambda face=face: self.local.describe(face), self.face_slots
                        )
                        after = self._wait_job(job, self.config.face_timeout_s, ticket)
                        self.mood.record(
                            track, before[track.id], after, self.clock(), remark_end
                        )
        except Exception as exc:
            log.warning("positivity_round_failed type=%s", type(exc).__name__)
            self._cancel_voice()
        finally:
            ticket.clear()
            if self.guard.cancelled.is_set():
                try:
                    self.mood.opt_outs += 1
                except Exception:
                    pass
                self._cancel_voice()
            self.guard.finish()
            self.ticket = None

    def _cancel_voice(self):
        try:
            cancel = getattr(self.voice, "cancel", None)
            if cancel:
                cancel()
        except Exception:
            pass

    def tick(self):
        try:
            self._pump()
            faces = self.guard.candidates(self._visible())
            if faces:
                self.run_round(faces)
        except Exception as exc:
            self.guard.finish()
            log.warning("positivity_tick_failed type=%s", type(exc).__name__)

    def _run(self):
        try:
            prepare = getattr(self.voice, "prepare_notice", None)
            if prepare:
                ticket = threading.Event()
                ticket.set()
                job = self._start_job(
                    lambda: prepare(self.config.notice_text), self.voice_slots
                )
                self._wait_job(job, self.config.voice_timeout_s, ticket)
        except Exception as exc:
            # No notice means no consent window. Disable engagement for this run.
            self.guard.stopped.set()
            self._cancel_voice()
            log.warning("positivity_notice_unavailable type=%s", type(exc).__name__)
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(0.02)

    def start(self):
        self.worker = threading.Thread(
            target=self._run, name="encourage-worker", daemon=True
        )
        self.worker.start()

    def on_user_transcript(self, text):
        """Returns whether the existing transcript handler should receive this line."""
        try:
            speaking = self.voice.speaking()
            self.guard.on_transcript(text, speaking)
            return not speaking
        except Exception:
            self.guard.cancelled.set()
            return True

    def close(self):
        self.stop.set()
        self.guard.stopped.set()
        self.guard.cancelled.set()
        if self.ticket:
            self.ticket.clear()
        self._cancel_voice()
        self.bus.close()
