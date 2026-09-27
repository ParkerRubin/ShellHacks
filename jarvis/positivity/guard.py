"""All tracking updates belong to the worker; callbacks only set cancellation events."""

import re
import threading
import time
from dataclasses import dataclass


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    intersection = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(
        0, min(ay + ah, by + bh) - max(ay, by)
    )
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


@dataclass
class Track:
    id: int
    box: tuple[int, int, int, int]
    since: float
    last_seen: float
    person_key: str | None = None


class TrackAssociator:
    def __init__(self):
        self.tracks = {}
        self.next_id = 0

    def update(self, boxes, ts):
        self.tracks = {k: v for k, v in self.tracks.items() if ts - v.last_seen < 5.0}
        remaining = set(self.tracks)
        visible = []
        for box in sorted(boxes, key=lambda b: b[0]):
            if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
                continue
            match = max(
                remaining, key=lambda k: iou(box, self.tracks[k].box), default=None
            )
            if match is not None and iou(box, self.tracks[match].box) >= 0.3:
                track = self.tracks[match]
                if ts - track.last_seen >= 0.5:
                    track.since = ts
                track.box, track.last_seen = tuple(box), ts
                remaining.remove(match)
            else:
                self.next_id += 1
                track = Track(self.next_id, tuple(box), ts, ts)
                self.tracks[track.id] = track
            visible.append(track)
        return visible


class TriggerGuard:
    def __init__(self, config, clock=time.monotonic):
        self.config, self.clock = config, clock
        self.state = "IDLE"
        self.cancelled = threading.Event()
        self.stopped = threading.Event()
        self.used = set()
        self.person_last = {}
        self.last_round = float("-inf")
        self.round_ids = ()
        self.notice_until = None
        self.pattern = re.compile(
            r"(?<!\w)(?:"
            + "|".join(re.escape(w) for w in config.opt_out_words)
            + r")(?!\w)",
            re.I,
        )

    def candidates(self, tracks):
        if self.stopped.is_set() or self.state in ("NOTICE", "ENGAGED"):
            return []
        now = self.clock()
        stable = [
            t
            for t in tracks
            if now - t.last_seen < 0.5
            and now - t.since >= self.config.dwell_s
            and t.id not in self.used
            and (
                not t.person_key
                or now - self.person_last.get(t.person_key, float("-inf"))
                >= self.config.cooldown_min * 60
            )
        ]
        self.state = "DWELL" if tracks else "IDLE"
        if now - self.last_round < self.config.rate_limit_s:
            self.state = "COOLDOWN"
            return []
        return sorted(stable, key=lambda t: t.box[0])[: self.config.max_faces]

    def begin(self, tracks):
        if self.stopped.is_set() or not tracks:
            return False
        self.cancelled.clear()
        self.state, self.notice_until = "NOTICE", None
        self.round_ids = tuple(t.id for t in tracks)
        self.last_round = self.clock()
        self.used.update(self.round_ids)
        for t in tracks:
            if t.person_key:
                self.person_last[t.person_key] = self.clock()
        return True

    def notice_finished(self):
        self.notice_until = self.clock() + self.config.opt_out_s

    def engage(self):
        if (
            self.cancelled.is_set()
            or self.stopped.is_set()
            or self.notice_until is None
            or self.clock() < self.notice_until
        ):
            return False
        self.state = "ENGAGED"
        return True

    def on_transcript(self, text, speaking=False):
        # Privacy wins over echo suppression: an opt-out during NOTICE is
        # always honored, even during playback. The hardware spike must assess
        # conservative cancellations caused by hearing our own notice.
        if speaking and self.state != "NOTICE":
            if re.search(r"\bstop\b", str(text), re.I):
                self.stopped.set()
                self.cancelled.set()
            return
        text = str(text)[:2000].lower().replace("’", "'")
        if re.search(r"\bstop\b", text):
            self.stopped.set()
            self.cancelled.set()
        elif self.state in ("NOTICE", "ENGAGED") and self.pattern.search(text):
            self.cancelled.set()

    def finish(self):
        self.state = "OPTED_OUT" if self.cancelled.is_set() else "COOLDOWN"
        self.round_ids = ()
