# Positivity hardware-free MVP

Implemented the requested code subset of tasks 2–5, 6.1/6.3, 7.1/7.3, 8.1 and 10.
The feature is **off by default**. Neither requirements.md file was edited.
No Gemini, ElevenLabs, Atlas or camera/audio hardware was used for validation of
this feature. Tests use synthetic frames, fake describers/voice, and a fake clock.

## Runtime

`FaceBus` keeps one latest copied frame and boxes; its publisher takes no waiting
lock. `TrackAssociator` uses IoU >= 0.3, a 0.5 s loss tolerance and 5 s track expiry.
`TriggerGuard` requires dwell, issues one notice per track, waits **two seconds
following notice completion**, and enforces a 20 s global rate limit. Tracks
remaining in view cannot be re-engaged. The known-person cooldown hook accepts an
optional person key, but memory recognition wiring is deliberately out of scope.

The `encourage-worker` pumps camera events throughout notice playback and waits,
so walking away and stale camera input block egress. A lost track stays excluded
for the entire round even if it returns before the window closes. Spoken opt-out
cancels every face in a round; `stop` disables subsequent rounds until restart.
The guard rechecks eligibility immediately before each external description,
retry and spoken remark. Only `FaceInput` (bounded JPEG or fixed local feature
tags) reaches the external adapter. Crops are copied, padded 20%, clamped, resized
to at most 256 px and encoded in RAM. Nothing in this package writes files.

Local before-samples may run during the static notice. Gemini receives one crop
per face, or tags plus a bank draft in tags-only mode, **only after the window**.
Results are validated, retried once for rejected wording, then replaced with a
bank composition from local evidence if rejected again. Normal per-face calls
run concurrently; speech is delivered left-to-right. After-samples use fresh
frames and the same local describer, two seconds after the last remark.

`MoodTracker` retains at most 500 RAM samples plus counters. Smile/expression
scores are crude local proxies, not evidence of improved clinical mood. No posture
measurement, identity association, or persistence is implemented.

## Explicit deviations and unresolved design conflicts

- The user's requested `POSITIVITY_ENABLED=false` default overrides the draft's
  `true`. Disabled construction creates no clients or threads, including no
  notice synthesis. The camera pan formula is unchanged in both modes. Task 7.2
  (pan override) is intentionally omitted.
- Option A is provisional and **UNVERIFIED**. `POSITIVITY_VOICE_ID` must be set
  explicitly to the hosted agent voice; no dashboard lookup is performed. TTS
  uses separate `sounddevice` PCM playback, sentence gaps of 350 ms and a 600 ms
  trailing pause. The static notice is pre-synthesized on a bounded background
  job and held in RAM. Actual model access/audio latency must be checked by a human.
  Both the notice and the default remark model are `eleven_flash_v2_5`, ElevenLabs'
  lowest-cost tier, per the team's decision to keep cost down for now.
- The design says both 1.5 s and 2 s for opt-out. This implementation consistently
  uses the more conservative **2 s after the notice ends**.
- Bounded daemon jobs/semaphores replace `ThreadPoolExecutor`. At most three
  face jobs and one voice job can be in flight. A stuck call keeps its slot;
  subsequent rounds fail closed instead of creating an unbounded queue or
  waiting on executor shutdown. Camera/callbacks never join these jobs.
- The user's “any exception means silence” instruction takes precedence over
  the draft's timeout/API-error fallback. Exceptions/timeouts abort the round's
  remaining speech. Already spoken notice/remarks cannot be retracted. Invalid
  *content* (a validation rejection, not an exception) gets the specified retry
  then local bank. A failed notice means no engagement for that run.
- NOTICE opt-outs are honored even while the robot speaks, prioritizing Property
  6 over the draft's echo-suppression rule. The fixed notice's own opt-out words
  may therefore conservatively cancel a round if echoed. Other playback-window
  transcripts are excluded from the normal print/memory callback; `stop` remains
  effective. This cannot stop the hosted ElevenLabs agent from hearing audio
  sent by its own microphone interface. The hardware spike must resolve that.
- Property 2 requires three distinct observations, while Property 3 asks that
  the bank validate for *any* subset, including one feature. Sparse evidence is
  never padded with invented observations: the bank emits an exact allowlisted
  neutral greeting marked `generic=True`. Only these hardcoded draft strings can
  bypass specificity; arbitrary model output cannot set that flag. Other valid
  bank output references observed features normally.
- The eyeglasses cascade detects eyes, not reliably the presence of glasses.
  It supports eye detection here; it does not generate a glasses/style claim.
  Local tilt/framing inform expression/presence. Volunteer threshold tuning and
  evidence of local cascade accuracy remain outstanding.
- `lexicon.py`, `bank.py` and the regression corpus are explicitly **drafts for
  human review**. Passing a finite deny-list does not guarantee cultural safety.
- OpenCV is constrained to `>=4.8,<5`: the installed 5.0 build lacked
  `CascadeClassifier`, breaking the existing Haar robot path. The 4.x build's
  bundled cascades are exercised by a blank synthetic crop test.
- This subset does not add the overlay/captions, printed-sign workflow, memory
  metrics, sponsor demo, or human-review work in tasks 8.2/9/11/12. Their boxes
  remain unchecked. A short notice is configurable; use the full notice until
  the separate printed privacy surface is reviewed.

## Verification and what a human still needs to do

The suite covers Properties 1–10 where applicable with Hypothesis and component
checks: denied terms and specificity, sparse bank behavior, crop hygiene, dwell
and rate limits, absorbing opt-out/walk-away, per-face isolation/order, exception
and late-completion isolation, unchanged pan math and sentence pacing. Robot-hook
tests exercise all memory/positivity on/off combinations and a failing publisher.
The same-instrument mood test confirms fresh after-samples and delta arithmetic.
Memory exceptions are not injected into positivity because this subset has no
memory dependency or persistence calls.

Before enabling this for people:

1. Run `python -m scripts.voice_spike --option all` on the actual audio setup,
   record echo, speaker conflicts and audible latency in
   `docs/positivity-voice-spike.md`, then select/tune the delivery option.
2. Have teammates review the lexicon, every bank template and the regression
   corpus; then perform the requested diverse-panel review and live/recorded
   accepted-remark review. These are not replaced by unit tests.
3. Configure the memory tools/prompt in the ElevenLabs dashboard separately.
4. Check camera FPS, unchanged servo movement, real-person face recognition,
   all opt-out routes, 10-engagement latency, and the 30-minute soak on hardware.
5. Complete the deferred disclosure/captions/sign surface before a public demo.

Atlas cluster creation, URI/key configuration and `scripts.provision`, as well as
enroll/leave/return/forget with memory online/offline/off, remain operator tasks.

## Recorded automated results

- Full `python -m pytest -q`: **66 passed, 1 skipped** (live Atlas not configured).
- Standalone `tests/test_robot_hooks.py`: **4 passed** (memory off/on crossed
  with positivity off/on); tests also exercise a failing publisher and the
  actual camera loop's unchanged pan output.
- `rg -n 'imwrite|tempfile|NamedTemporaryFile|TemporaryDirectory|mkstemp'
  jarvis/positivity`: **no matches**.
- `scripts.voice_spike --help` works without audio/service initialization; fake
  A/B/C harness tests pass. No actual spike has been run.
- Task files live in `.kiro/specs/` (the duplicate `specs/` copy was removed); neither requirements.md
  was changed. The draft regression corpus is explicitly unignored in Git.
