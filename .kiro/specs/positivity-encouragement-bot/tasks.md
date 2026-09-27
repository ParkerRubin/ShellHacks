# Implementation Plan: Positivity & Encouragement Bot

## Overview

Implements `design.md` as a new `jarvis/positivity/` package plus two small, flag-gated edits to `robot.py` (a face-event publish in `camera_loop`, and wiring for callbacks and tools). Python, thread-based, synchronous. Tasks marked `*` are optional (mostly tests). Requirement references use `requirements.md` numbering (`R6.2` = Requirement 6, criterion 2).

**MVP path** (demo-ready, in order): 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 10 → 12.

**Dependency on the MongoDB spec:** recognition-aware cooldown, returning-visitor metrics, and persisted engagement data need `IMemoryStore`, `NullMemory`, and `PresenceState` (MongoDB tasks 2.7, 3.5, 6.2, 6.4). Task 11 is written against `NullMemory` so this spec can be built and demoed first without MongoDB.

## Tasks

- [ ] 1. Spike: speaking unprompted, and baseline measurements
  - [ ] 1.1 On the demo hardware, test options A, B and C from the design's Open Technical Questions for speaking while the ElevenLabs agent session is open; measure echo (does the agent respond to the robot's own voice?), device conflicts, and time to first audio
    - Record the decision and evidence in `docs/positivity-voice-spike.md`
    - _Requirements: 3.1, 3.3, 10.4_
  - [ ] 1.2 Measure the baseline `camera_loop` frame rate and pan-command output with the current `robot.py` (no changes), and save the numbers as the regression baseline
    - _Requirements: 8.4, 10.3_
  - [ ] 1.3 Confirm which Gemini model name `robot.py` uses is valid (`check.py`), and note that `.env`'s `GEMINI_MODEL` is currently unused
    - _Requirements: 8.2_

- [ ] 2. Package scaffolding, configuration, and the face bus
  - [ ] 2.1 Create `jarvis/positivity/__init__.py`, `config.py` (`PositivityConfig.from_env()`: `POSITIVITY_ENABLED`, `_PRIVACY_MODE`, `_DWELL_S`, `_COOLDOWN_MIN`, `_MAX_FACES`, `_VOICE_ID`, `_TTS_MODEL`, `_OPT_OUT_WORDS`, `_NOTICE`), and `build_positivity()` that returns a no-op object when disabled or on any init error
    - Add the variables (no secrets) to `.env.example`
    - _Requirements: 8.1, 8.5_
  - [ ] 2.2 Implement `FaceBus` (size-1 queue, latest-wins, non-blocking `publish`, `FaceEvent` dataclass)
    - _Requirements: 4.2, 8.4_
  - [ ] 2.3 Refactor `camera_loop`: after `detectMultiScale`, call `positivity.bus.publish(frame.copy(), faces)`. Extract the pan computation into `pan_for(face, w)` **without changing its result**. No other change to tracking or serial writes
    - Gate on `POSITIVITY_ENABLED`; wrap the publish so it can never raise into the loop
    - _Requirements: 8.1, 8.2, 8.4, 10.3_
  - [ ]* 2.4 Write property test for tracking non-interference
    - **Property 9: No tracking interference**
    - **Validates: Requirements 8.1, 8.4**
  - [ ] 2.5 Checkpoint: run `robot.py` with the feature on and idle; confirm frame rate and pan commands match the task 1.2 baseline

- [ ] 3. Trigger guard and opt-out
  - [ ] 3.1 Implement `TrackAssociator` (IoU ≥ 0.3 across frames, 0.5 s loss tolerance, 5 s absence to release a track)
    - _Requirements: 4.2_
  - [ ] 3.2 Implement `TriggerGuard` state machine: IDLE → DWELL (≥ `DWELL_S`) → NOTICE → ENGAGED → COOLDOWN, with OPTED_OUT, global 20 s rate limit, per-person cooldown, and an injectable clock
    - Round formation: all stably tracked faces up to `MAX_FACES`, ordered left to right
    - _Requirements: 2.3, 4.2, 10.1_
  - [ ] 3.3 Implement opt-out detection from `callback_user_transcript` (whole-word, case-insensitive; opt-out applies to every face in the current round; "stop" disables the session) and the non-verbal opt-out (a face lost for ≥ 0.5 s during NOTICE is dropped from the round)
    - _Requirements: 4.3, 4.4, 6.5_
  - [ ]* 3.4 Write property tests for the guard
    - **Property 5: No repeat, no premature engagement**
    - **Property 6: Opt-out is absorbing and precedes any egress**
    - **Validates: Requirements 4.2, 6.1, 6.5, 10.1**

- [ ] 4. Face crop and describers
  - [ ] 4.1 Implement `FaceCropper.crop_face(frame, box) -> bytes` (20% pad, clamp, longest side ≤ 256 px, `cv2.imencode` JPEG, in memory only) and the `FaceInput` type that the describer interface accepts (never a full frame)
    - _Requirements: 6.1, 6.2_
  - [ ]* 4.2 Write property test for crop hygiene
    - **Property 4: Only crops leave the device**
    - **Validates: Requirements 6.1, 6.2**
  - [ ] 4.3 Implement `LocalTagDescriber` using OpenCV's bundled cascades (`haarcascade_smile.xml`, `haarcascade_eye.xml`, `haarcascade_eye_tree_eyeglasses.xml`) plus head tilt and framing; outputs `FaceDescription` with `smile_score`, `expression_score`, tags, and `remark=None`
    - Tune thresholds on a few volunteers under real lighting; if unreliable, degrade to presence-only tags
    - _Requirements: 1.1, 6.1, 6.2, 8.2_
  - [ ] 4.4 Implement `jarvis/positivity/prompts.py` (fixed system and user prompts, JSON response schema, allow-list and forbidden-topic text) and `GeminiDescriber` (one call per face crop, `response_mime_type="application/json"`, reuses the existing `gemini` model object, 2.5 s timeout)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 9.1, 9.2, 9.3_
  - [ ] 4.5 In `tags_only` mode, send Gemini only the text tags and ask for a warm rewrite of the bank-assembled remark; no image is sent
    - _Requirements: 6.2_
  - [ ]* 4.6 Write component test with a fake Gemini client: malformed JSON, missing fields, timeouts → describer returns a safe failure the engine can handle
    - _Requirements: 8.5_

- [ ] 5. Safety: validator, lexicon, and affirmation bank
  - [ ] 5.1 Implement `jarvis/positivity/lexicon.py`: `ALLOWED_FEATURES`, per-feature keyword sets, deny-lists per category (age, weight/body, skin/ethnicity, gender words and pronouns, health/disability), comparison and backhanded patterns
    - Data only; reviewed by at least two teammates before it is considered done
    - _Requirements: 1.3, 1.4, 1.5, 9.1, 9.2, 9.4_
  - [ ] 5.2 Implement `RemarkValidator.validate(description) -> ValidationResult` as a pure function (allow-list, ≥ 3 distinct observations, remark references ≥ `POSITIVITY_MIN_REFERENCED` of them, deny-lists, comparison patterns, length and character rules)
    - _Requirements: 1.2, 1.3, 1.4, 2.4, 2.5, 9.2_
  - [ ] 5.3 Author `AffirmationBank`: ≥ 5 hand-written templates per allowed feature, `compose(observations)`, and a separate neutral-greeting list (flagged `generic=True`)
    - Read every template aloud; check tone and cultural neutrality
    - _Requirements: 2.4, 2.5, 9.3, 9.4_
  - [ ] 5.4 Implement the retry-then-fallback policy (one stricter re-prompt including the failure reasons, then the bank)
    - _Requirements: 1.5, 8.5, 9.2_
  - [ ]* 5.5 Write property tests
    - **Property 1: Validator blocks sensitive categories**
    - **Property 2: Validator requires specificity and breadth**
    - **Property 3: Fallback bank always validates**
    - **Validates: Requirements 1.2, 1.3, 1.4, 2.4, 2.5, 9.2, 9.3, 9.4**
  - [ ] 5.6 Create the prompt-safety regression corpus `tests/data/remarks_corpus.json` (benign and adversarial remarks with expected verdicts) and a test that runs it on every commit; add any bad remark found in later testing
    - _Requirements: 9.2, 9.5_
  - [ ] 5.7 Checkpoint: run 30 live or recorded Gemini calls on volunteer crops; count validator rejections, review every accepted remark by hand, and add findings to the lexicon and corpus

- [ ] 6. Voice delivery
  - [ ] 6.1 Implement `VoiceDelivery` protocol and `ElevenLabsTTSDelivery` using the existing `client`: sentence-level synthesis, 350 ms inter-sentence gap, 600 ms trailing pause, streamed playback, a `speaking()` flag
    - Follow the delivery option chosen in task 1.1
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 10.4_
  - [ ] 6.2 Tune voice settings by ear with three teammates (stability, style, speed) and record the chosen values in config defaults; choose the low-latency model for the notice and the quality model for the remark if the latency budget allows
    - _Requirements: 3.2, 3.5_
  - [ ] 6.3 Pre-synthesize and cache the fixed notice line at startup
    - _Requirements: 10.4_
  - [ ] 6.4 Suppress user transcripts (and opt-out matching for anything but the deliberate opt-out window) while `speaking()` is true, to prevent self-talk loops
    - _Requirements: 4.1, 6.5_
  - [ ]* 6.5 Write property test for pacing
    - **Property 10: Voice pacing**
    - **Validates: Requirements 3.4**

- [ ] 7. Encouragement engine
  - [ ] 7.1 Implement `EncouragementEngine.run_round(faces)`: notice → opt-out window → (only then) parallel per-face crop, describe, validate (max 3 workers, 2.5 s per-face timeout, local fallback) → ordered delivery → after-sample
    - Order faces left to right; one describer call per face with exactly one crop
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 2.5, 4.1_
  - [ ] 7.2 Add `TrackingPolicy`: default largest face (existing behaviour); during multi-face rounds an override that pans toward the face being addressed; flag-gated and released at the end of the round
    - _Requirements: 2.3, 8.1, 8.4_
  - [ ] 7.3 Implement the `encourage-worker` thread with a catch-all around every round, logging, and guard reset
    - _Requirements: 8.5_
  - [ ]* 7.4 Write property tests
    - **Property 7: Per-face independence**
    - **Property 8: Failure isolation**
    - **Validates: Requirements 2.3, 8.5**
  - [ ]* 7.5 Write an integration test with synthetic `FaceEvent` streams, a fake describer, and a fake voice: assert the exact sequence of spoken lines, timing against the budget (using a fake clock), and behaviour on injected Gemini and TTS failures
    - _Requirements: 4.2, 8.5, 10.1, 10.2_
  - [ ] 7.6 Checkpoint: walk up to the robot; confirm the notice, the opt-out ("no thanks" cancels and no crop is sent), and a single remark; confirm a person who stays in frame is not addressed again

- [ ] 8. Mood measurement and evidence
  - [ ] 8.1 Implement `MoodTracker`: local before-sample during the notice, local after-sample 2 s after the last remark, `MoodSample` records, engagement counters (people engaged, dwell after remark, opt-outs)
    - Same instrument (local describer) for both samples
    - _Requirements: 5.1, 5.3, 5.4_
  - [ ] 8.2 Add an on-screen overlay in the existing OpenCV window (people engaged, average smile delta, opt-outs, a small "Positivity: say 'no thanks' or step away to skip" indicator, and text captions of every spoken line) and an end-of-session console summary
    - _Requirements: 5.2, 5.3, 6.5_
  - [ ] 8.3 State the limitations in the summary output and demo notes: the smile score is a proxy, posture is not measured, and the sample size is small
    - _Requirements: 5.5_
  - [ ]* 8.4 (Stretch) Spoken 1-5 check-in before and after, read from the ElevenLabs transcript callback
    - _Requirements: 5.1_

- [ ] 9. Privacy and consent surface
  - [ ] 9.1 Add a printed sign text and a spoken notice script (two lengths, `POSITIVITY_NOTICE=short|full`) to `docs/positivity-notice.md`; get teammate sign-off
    - _Requirements: 6.4, 6.5_
  - [ ] 9.2 Write `docs/positivity-privacy.md`: exactly what is sent where in each mode (matches the table in the design), what is stored (nothing by default), and how to opt out
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - [ ] 9.3 Verify by test and by network capture: in `tags_only` mode no image bytes are sent to any external host; in `crop` mode only ≤ 256 px crops go to Gemini, and only after the opt-out window
    - _Requirements: 6.1, 6.2_
  - [ ] 9.4 Confirm the code path writes no image or crop to disk (search for `imwrite`, temp files) and that logs contain no remark text tied to an identity
    - _Requirements: 6.3_

- [ ] 10. Wire-up in `robot.py`
  - [ ] 10.1 In `robot.py`, build positivity next to the other clients (`positivity = build_positivity(client, gemini)`), pass it the `FaceBus`, and extend the existing `callback_user_transcript` lambda to also call `positivity.on_user_transcript(t)`
    - Existing prints and behaviour are preserved
    - _Requirements: 8.1, 8.2, 8.3, 4.3_
  - [ ] 10.2 Verify `POSITIVITY_ENABLED=false` gives exactly the previous behaviour, including no additional threads
    - _Requirements: 8.1_
  - [ ] 10.3 Checkpoint: full run with the ElevenLabs agent session open and the servo connected; confirm the agent conversation, the `look` tool, and the servo tracking still work while the positivity feature is idle and after it fires
    - _Requirements: 8.1, 8.4_

- [ ] 11. Memory store integration (after the MongoDB spec tasks 2.7, 3.5, 6.2, 6.4)
  - [ ] 11.1 Accept a memory facade (`NullMemory` by default). Use `PresenceState` (if present) for the recognized-person cooldown
    - _Requirements: 5.4, 8.2_
  - [ ] 11.2 For recognized, consenting people only, write aggregated engagement records (visit count, mood delta) through `IMemoryStore`; nothing is written for anyone else
    - _Requirements: 5.4, 6.3_
  - [ ]* 11.3 Test that with `NullMemory`, and for unrecognized people, nothing is persisted
    - _Requirements: 6.3_

- [ ] 12. Performance, diversity review, and demo
  - [ ] 12.1 Measure frame rate with the feature on during a round and compare with the baseline (target ≥ 10 fps); run a 30-minute soak with repeated engagements and check for memory growth or slowdown
    - _Requirements: 10.3, 10.5_
  - [ ] 12.2 Stopwatch 10 engagements: dwell to notice, opt-out window close to first remark audio (target ≤ 3 s, budget 5 s), TTS start (target ≤ 1 s); record in `docs/positivity-latency.md`
    - _Requirements: 10.1, 10.2, 10.4_
  - [ ] 12.3 Review remarks with a diverse group of volunteers (at least five people, varied backgrounds), collect written feedback, and update the lexicon, prompts, and bank accordingly; if a diverse panel cannot be found before the deadline, state that limitation in the submission
    - _Requirements: 9.5_
  - [ ] 12.4 Write the demo script and Microsoft submission notes in `docs/positivity-demo.md`: the problem ("what's missing"), no-chat interaction, measured mood delta, privacy modes, opt-out demonstration
    - _Requirements: 4.5, 5.2, 5.5, 7.1, 7.2, 7.3, 7.4, 7.5_
  - [ ] 12.5 Final checkpoint: run the full test suite (`pytest -q`) and the manual checklist with the feature ON, OFF, and with Gemini or TTS deliberately failing (robot stays silent, tracking continues)
    - _Requirements: 8.1, 8.4, 8.5_

## Notes

- `requirements.md` is not modified. Wording problems (R6.2 vs. crop mode, R10.2 timing, R5.3 posture, R9.5 panel) and their proposed resolutions are in `analysis.md`.
- The lexicon and affirmation bank (tasks 5.1, 5.3) are data that people, not the model, must review. Budget teammate time for them.
- The `look()` tool in `robot.py` sends a full frame to Gemini on the voice agent's request. That is not changed by this spec.
