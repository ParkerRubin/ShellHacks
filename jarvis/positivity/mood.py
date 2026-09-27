"""RAM-only, same-instrument expression proxies; no clinical or posture inference."""

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class MoodSample:
    track_id: int
    before: tuple[float, float]
    after: tuple[float, float]
    delta: tuple[float, float]
    duration_in_frame_s: float
    dwell_after_remark_s: float
    ts: float


class MoodTracker:
    def __init__(self):
        self.samples = deque(maxlen=500)
        self.people_engaged = 0
        self.opt_outs = 0

    def record(self, track, before, after, ts, remark_end):
        first = (before.smile_score, before.expression_score)
        last = (after.smile_score, after.expression_score)
        sample = MoodSample(
            track.id,
            first,
            last,
            tuple(b - a for a, b in zip(first, last)),
            max(0, ts - track.since),
            max(0, ts - remark_end),
            ts,
        )
        self.samples.append(sample)
        return sample

    def summary(self):
        return {
            "people_engaged": self.people_engaged,
            "opt_outs": self.opt_outs,
            "samples": len(self.samples),
            "average_smile_delta": sum(s.delta[0] for s in self.samples)
            / max(1, len(self.samples)),
            "limitation": "Local expression proxy only; posture and clinical mood are not measured.",
        }
