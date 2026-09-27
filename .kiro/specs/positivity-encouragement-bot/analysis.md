# Requirements Analysis: Positivity & Encouragement Bot

Scope: `requirements.md` (10 requirements, 50 acceptance criteria) reviewed against the current codebase (`robot.py`, `firmware.ino`), `CLAUDE.MD`, the sibling `mongodb-memory-store-integration` spec, and the design in `design.md`.

`requirements.md` has **not** been modified. Suggested rewordings are in section 5 for approval.

## 1. Verdict

The concept is strong and fits the challenge. The requirements are buildable, but **three of them cannot all be true at once as written**, and the design has to pick a side for each:

1. **R1.1 vs R6.1/R6.2 (the central conflict).** Face features must be analysed by Gemini (a cloud API), yet R6.1 says raw facial data is not transmitted externally and R6.2 says Gemini receives "only anonymized feature descriptions, not identifiable images". The current Face_Tracker (Haar cascade in `robot.py`) produces only a bounding box, so nothing local can yet say "warm smile".
   → The design offers two modes. `crop` (default) sends one small face-only crop, only after the person has had a chance to opt out, and discloses this. `tags_only` satisfies R6.2 literally: local OpenCV cascades produce text tags, and no image is sent. The requirement text should be reworded to match (section 5).
2. **R4.2 (auto-initiate on face) vs R6.5 (information and opt-out) and R6.3.** Speaking about someone's face the instant it appears leaves no chance to decline. → A short spoken notice and opt-out window comes first, which the design places before any face data leaves the device.
3. **R10.2 (remark within 5 s of detection) vs the notice/opt-out window.** These cannot both hold in `crop` mode. → Measure R10.2 from the end of the opt-out window (about 3 s at the budget, inside 5 s), and say so in the requirement.

Other significant gaps: nothing defines re-trigger behaviour (R4.2 would fire every frame), the mood metric (R5.1), or any non-verbal or non-hearing path through the experience.

## 2. Ambiguities and Gaps

| # | Req | Issue | Proposed resolution | Resolved in |
|---|---|---|---|---|
| A1 | 1.1 | "Analyze distinctive facial features": the current tracker only returns a bounding box | New `FaceDescriber` interface: `GeminiDescriber` (crop) and `LocalTagDescriber` (OpenCV cascades) | design: FaceDescriber; tasks 4.3, 4.4 |
| A2 | 1.2 | "At least three specific positive observations": are all three spoken? | Generate ≥ 3 observations; the spoken remark must reference ≥ 2 (`POSITIVITY_MIN_REFERENCED`), within 1-3 sentences. **Open question O2** | design: RemarkValidator; task 5.2 |
| A3 | 1.3 | "Confident posture" cannot be seen in a face crop | Replace by `presence` (calm, energy, confidence conveyed by the face). Posture is not claimed | design: FaceDescriber |
| A4 | 1.4 | "Potentially sensitive characteristics" is an open list | Enumerated deny-list categories: age, weight/body, skin/ethnicity, gender and pronouns, health/disability, attractiveness ranking, comparisons | design: RemarkValidator; task 5.1 |
| A5 | 1.5, 9.1 | "Culturally sensitive" and "prompted/trained to recognize diverse beauty standards": nobody can train Gemini here | Achieved by prompt constraints and the validator, and by keeping remarks on expression and presence, not attractiveness. State that plainly | design: FaceDescriber, RemarkValidator |
| A6 | 2.3 | "Separate remarks for each face": order, timing, and how the listener knows which one is theirs | One analysis per face, max 3, spoken left to right, robot pans toward each | design: Engine, TrackingPolicy; tasks 7.1, 7.2 |
| A7 | 2.4, 2.5 | "Avoid generic" and "genuine, warm tone" are subjective | Generic is testable: the validator requires references to observed features. Warmth is a human judgement: reviewed by volunteers | design: RemarkValidator; tasks 5.7, 12.3 |
| A8 | 3 | The ElevenLabs agent in `robot.py` is reactive. Nothing in the code can speak unprompted, and the mic and speaker are already held by `DefaultAudioInterface` | One-day spike to choose among options A, B, C | design: Open Technical Questions; task 1.1 |
| A9 | 3.2-3.5 | "Warm", "natural cadence", "avoid monotone": subjective and delegated to a third-party service | Concrete ElevenLabs settings (stability, style, speed), sentence-level pauses, tuned by ear and recorded | design: VoiceDelivery; tasks 6.1, 6.2 |
| A10 | 4.2 | Re-trigger rules are absent (per-frame firing) | Dwell, per-person cooldown, global rate limit, and absent-then-return rules | design: TriggerGuard; task 3.2 |
| A11 | 4.1, 4.3 | "Without text input" and "SHALL NOT depend on keyboard": the existing OpenCV window still uses ESC to quit | Clarify that core functionality excludes developer controls such as ESC | section 5 |
| A12 | 5.1 | "Measurable mood improvement" through a "before/after assessment" has no defined instrument | Proxy: local smile and expression scores, same instrument before and after; optional spoken 1-5 check-in (stretch). State it is a proxy | design: MoodTracker; tasks 8.1, 8.3, 8.4 |
| A13 | 5.3 | Posture cannot be observed from a face crop | Drop posture; keep smile and expression | design: MoodTracker |
| A14 | 5.4 | "Return interactions" requires identifying people, which is a biometric operation | Only through the MongoDB spec's consented recognition. Otherwise report only counts of people engaged | design: MoodTracker; task 11 |
| A15 | 5.5, 7.1 | "Align with the Microsoft challenge" and "confidence building as an accessibility need" are claims, not testable criteria. The actual challenge rubric is not in this repo (`CLAUDE.MD` paraphrases it) | Verify the official wording; write the submission narrative against it. **Open question O1** | task 12.4 |
| A16 | 6.3 | "Personally identifiable information": is a face crop PII? | Treated as sensitive: never stored, sent only after the opt-out window, and only in `crop` mode | design: Privacy Summary |
| A17 | 6.4 | "Relevant privacy regulations" unspecified. Biometric-privacy rules vary by jurisdiction, and a public event may include minors while R1.4 forbids estimating age | Minimise instead of interpret: no storage, no identification, no age inference, visible notice, opt-out. The team should check local rules before the demo. **Open question O4** | design: Privacy Summary; tasks 9.1-9.4 |
| A18 | 6.5 | "Opt-out mechanisms" undefined | Spoken opt-out words, walking away, spoken "stop" for the session, printed sign, captions. Feature kill switch | design: TriggerGuard, Notice; tasks 3.3, 9.1 |
| A19 | 7.4 | "Demonstrable within challenge timeframes" is a schedule constraint, not a testable criterion | MVP path defined in tasks | tasks overview |
| A20 | 8.2 | "Reuse existing Face_Tracker and Gemini_Analyzer components": in `robot.py` these are inline (`camera_loop`, `look`), not components | Small extraction: the pan calculation and a `FaceBus` publish; reuse the existing `gemini` model object | design: FaceBus; tasks 2.3, 4.4 |
| A21 | 10.1 | "Begin facial analysis within 2 seconds" | Local analysis starts within 1.0-2.0 s of detection; external analysis only after opt-out window | design: Latency Budget |
| A22 | 10.3 | "Under high load" is undefined | Measure fps with the feature on vs. baseline; the camera thread only publishes to a queue | tasks 1.2, 2.5, 12.1 |
| A23 | 10.5 | "Without degradation over 30-minute sessions" | 30-minute soak test with repeated engagements | task 12.1 |

## 3. Conflicts

### Within this spec
| # | Conflict | Resolution |
|---|---|---|
| K1 | R1.1 (Gemini analyses the face) vs R6.1/R6.2 (nothing identifiable leaves the device) | Two privacy modes; `crop` disclosed, `tags_only` literal. Reword R6.1/R6.2 (section 5) |
| K2 | R4.2 (auto-initiate) vs R6.5 (inform and allow opt-out) | Notice and opt-out window first; nothing leaves the device before it closes |
| K3 | R10.2 (5 s to remark) vs notice and opt-out window | Measure from the end of the opt-out window; ≈ 7.5 s from detection in `crop` mode, ≈ 5 s in `tags_only` |
| K4 | R1.2 (≥ 3 observations) vs R10.2 (5 s) | One Gemini call per face returns all observations and the remark together (about 2 s) |
| K5 | R2.3 (per-face remarks) vs R10.2 | R10.2 applies to the first remark. Analyses run in parallel; speech is sequential |
| K6 | R5.3 (posture) vs face-only crops needed for R6 | Posture not measured; stated as a limitation |
| K7 | R4.3/R4.4 (voice and presence only) vs the need to opt out | Opt-out is voice or walking away; both are non-keyboard |
| K8 | R5.4 (return interactions) vs R6.3 (no PII without consent) | Only via consented recognition in the MongoDB spec |

### Cross-spec (`mongodb-memory-store-integration`)
| # | Conflict | Resolution |
|---|---|---|
| X1 | This spec's R5.4 duplicates the MongoDB spec's R3 (recognition) | Positivity consumes `PresenceState` and `IMemoryStore`; it does not build its own store |
| X2 | MongoDB R5.2 (consent before storing personal data) governs anything this feature could persist | Nothing is persisted by default; aggregated data only for recognized, consenting people |
| X3 | The existing `look()` tool sends a **full camera frame** to Gemini when the voice agent asks | Outside this feature's scope, but it undermines a blanket "raw frames stay local" claim. The documentation says "the positivity feature sends only crops"; decide separately whether `look()` should crop or disclose. **Open question O3** |
| X4 | Both features subscribe to newly detected faces | Each subscriber is non-blocking. Neither may slow `camera_loop` |

## 4. Testability

Legend: **PBT** property-based test, **UT** unit/example, **IT** integration with fakes, **M** manual (hardware, humans, or judgement).

| Req | Criteria | Method | Notes |
|---|---|---|---|
| 1 | 1.1 | IT | Fake describer receives a crop for each engaged face |
| | 1.2 | PBT (P2) | Validator |
| | 1.3, 1.4 | PBT (P1, P2) | Deny/allow-lists |
| | 1.5 | PBT (P1), M | Diverse volunteer review |
| 2 | 2.1, 2.2 | IT | |
| | 2.3 | PBT (P7) | |
| | 2.4 | PBT (P2, P3) | |
| | 2.5 | M | Human tone review |
| 3 | 3.1 | IT | Fake voice receives the remark |
| | 3.2, 3.3, 3.5 | M | Listen and rate |
| | 3.4 | PBT (P10) | Pacing structure only; the emotional effect is manual |
| 4 | 4.1, 4.3, 4.4 | M, IT | Full run with no keyboard or mouse input |
| | 4.2 | PBT (P5), IT | |
| | 4.5 | M | Demo |
| 5 | 5.1 | UT, M | Score arithmetic is testable; real-world improvement is not |
| | 5.2, 5.5 | M | Judged by the demo narrative |
| | 5.3 | UT | Overlay shows deltas |
| | 5.4 | UT | Counters |
| 6 | 6.1, 6.2 | PBT (P4, P6), IT, M | Plus a network capture (task 9.3) |
| | 6.3 | UT, code search | `imwrite`, temp files, logs |
| | 6.4 | M | Team review |
| | 6.5 | PBT (P6), M | |
| 7 | 7.1-7.5 | M | Sponsor checklist |
| 8 | 8.1, 8.4 | PBT (P9), M | Compare pan output and fps with the baseline |
| | 8.2, 8.3 | M | Code review |
| | 8.5 | PBT (P8) | |
| 9 | 9.1-9.4 | PBT (P1, P3), M | |
| | 9.5 | M | Diverse volunteer session. May not be achievable before the deadline; state the limitation |
| 10 | 10.1, 10.2, 10.4 | IT (fake clock), M (stopwatch) | |
| | 10.3, 10.5 | M | fps measurement and soak test |

## 5. Suggested Edits to `requirements.md` (not applied)

1. **1.1 / 1.3**: replace "confident posture" with "confident expression"; note the analysis is of the face region.
2. **1.2**: append "The spoken remark SHALL reference at least two of these observations."
3. **4.2**: "WHEN the Face_Tracker detects a face that remains in view for at least one second, THE System SHALL start the encouragement sequence, beginning with a spoken notice and an opportunity to decline."
4. **4 (new criterion)**: "THE System SHALL NOT address the same person more than once within a configured cooldown."
5. **4.3**: "…core functionality, excluding developer controls."
6. **5.1**: "…demonstrate a change in a measurable expression score (smile and expression) between before and after samples."
7. **5.3**: remove "posture improvement".
8. **6.1 / 6.2**: replace both with: "THE Face_Tracker SHALL process video frames locally. WHERE an external service is used to describe a face, THE System SHALL send at most a small face-only crop, only after the person has had the opportunity to decline, SHALL NOT store it, and SHALL disclose this. A strict mode that sends only text feature descriptions and no image SHALL be available."
9. **6.5**: "…SHALL provide opt-out by spoken refusal and by walking away, and SHALL display or speak this at the start of every interaction."
10. **R7.1**: reword the claim as "addresses a missing form of unsolicited, low-friction emotional support" (see O1).
11. **9.1**: "trained/prompted" becomes "prompted and validated".
12. **10.2**: "…within 5 seconds of the end of the opt-out window."
13. **New criterion**: "THE System SHALL show every spoken line as on-screen text."

## 6. Open Questions for the Team

| # | Question | Recommended default |
|---|---|---|
| O1 | What is the exact wording and judging rubric of the Microsoft "What's Missing?" challenge? Is confidence-building persuasive as "something difficult, inaccessible, or missing"? | Build the submission narrative on "no one offers unsolicited kindness at scale; the robot does" and the measured deltas, and check it against the official wording |
| O2 | Should the robot speak three separate compliments (a literal reading of R1.2)? | Speak 2-3 sentences covering ≥ 2 observations. Configurable |
| O3 | Should the existing `look()` tool also crop or disclose? | Leave it; document that `look()` sends a full frame on the user's request. Revisit if it turns up in a privacy review |
| O4 | What do local rules and the event's rules require for a public camera-based demo? | Notice sign, opt-out, no storage; ask the organisers |
| O5 | Will the noisy hackathon hall make spoken opt-out unreliable? | Yes, likely. Walking away is a second opt-out; captions and the sign cover the rest. Consider a near-field microphone |
| O6 | Who reviews the deny-list and affirmation bank? | At least two teammates plus one outside reviewer |

## 7. Traceability Matrix

| Req | Design sections | Tasks | Properties |
|---|---|---|---|
| 1 Facial analysis | FaceCropper, FaceDescriber, RemarkValidator | 4.3, 4.4, 4.5, 5.1, 5.2 | P1, P2 |
| 2 Remark generation | Engine, RemarkValidator, AffirmationBank | 5.2, 5.3, 5.4, 7.1, 7.2 | P2, P3, P7 |
| 3 Voice | VoiceDelivery, Captions | 1.1, 6.1-6.4 | P10 |
| 4 Non-chatbot | FaceBus, TriggerGuard, Notice | 2.2, 2.3, 3.1-3.3, 7.1, 10.1 | P5, P6 |
| 5 Real-world task | MoodTracker | 8.1-8.4, 11.2, 12.4 | none (manual) |
| 6 Privacy | FaceCropper, Privacy Summary, TriggerGuard, Notice | 4.1, 4.2, 4.5, 9.1-9.4, 3.3 | P4, P6 |
| 7 Sponsor alignment | Sponsor Alignment, Dependencies | 12.4 | none (manual) |
| 8 Integration | FaceBus, camera hook, TrackingPolicy, Error Handling | 2.1-2.5, 7.2, 7.3, 10.1-10.3 | P8, P9 |
| 9 Cultural sensitivity | Lexicon, RemarkValidator, AffirmationBank | 5.1, 5.3, 5.6, 5.7, 12.3 | P1, P3 |
| 10 Performance | Latency Budget, Threading Model | 1.2, 2.5, 6.3, 12.1, 12.2 | P5 |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Noisy hall defeats spoken opt-out | High | High | Walk-away opt-out, printed sign, captions, near-field mic |
| Gemini "observes" something that is not there (hallucinated glasses, smile) | Medium | Medium | Constrained feature list, hedged phrasing in the prompt, human review; limit `style` claims |
| An appearance compliment lands badly for some people | Medium | High | Focus on expression and presence, not attractiveness; no comparisons; opt-out; no follow-up questions |
| Unprompted TTS collides with the live ElevenLabs session (echo, device conflict) | High | High | Spike (task 1.1) before any other voice work |
| Local cascades are unreliable under venue lighting | Medium | Medium | `tags_only` degrades to presence-only tags; `crop` mode does not depend on them for remarks |
| Judges read `look()` sending full frames as a privacy hole | Medium | Medium | Document it; O3 |
| Feature slows the servo path | Low | High | Non-blocking bus; tasks 2.5 and 12.1 measure fps |
| Quota or latency spikes on Gemini/ElevenLabs during the demo | Medium | Medium | Local fallback and bank; cached notice line; keep the demo robust when silent |
