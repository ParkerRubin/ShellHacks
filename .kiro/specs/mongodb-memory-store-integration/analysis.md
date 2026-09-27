# Requirements Analysis: MongoDB Memory Store Integration

Scope: `requirements.md` (10 requirements, 47 acceptance criteria) reviewed against the current codebase (`robot.py`, `firmware.ino`), `CLAUDE.MD`, the sibling `positivity-encouragement-bot` spec, and the design in `design.md`.

`requirements.md` has **not** been modified. Suggested rewordings are in section 5 for approval.

## 1. Verdict

The requirements are complete enough to build from. They are clear on *what* (memory, recognition, privacy, resilience) but leave several *how much / when* terms undefined, and a few criteria collide with each other or with the actual architecture. None of the issues block implementation. Each has a proposed resolution that the design already adopts.

Highest-impact items:
1. **R2 vs R5.2**: "store every exchange" conflicts with "ask consent before storing personal data". Resolved by anonymous-by-default storage.
2. **R4.2 vs R1.2/R6.5**: semantic ranking needs Atlas Vector Search, so it cannot work in the offline fallback. Resolved by defining fallback retrieval as recency + keyword.
3. **R3 has no enrollment story**: nothing says how a new person is registered, consents, or is disambiguated from a false match.
4. **R2.2 assumes Gemini is in every exchange.** It is not; the ElevenLabs agent handles the conversation and Gemini runs only in the `look` tool.
5. **Face biometrics** (R3.1, R3.2) are the most sensitive data in the system, and R5 is thin on them.

## 2. Ambiguities and Gaps

| # | Req | Issue | Proposed resolution | Resolved in |
|---|---|---|---|---|
| A1 | 1.1 | "Secure connection" is undefined | TLS via `mongodb+srv://`, credentials from env, Atlas IP allowlist limited to the demo machine | design: Security Notes |
| A2 | 1.2, 9.1 | "Local fallback storage" has no defined capability or reconciliation | SQLite fallback with recency + keyword retrieval; writes are queued in an outbox and synced back idempotently on reconnect | design: Stores; tasks 3.1, 3.4 |
| A3 | 1.4 vs 5.1 | Both require encryption, with different triggers ("where credentials are configured" vs. "all PII") | One rule: whenever persistence is enabled, PII fields are always encrypted. There is no plaintext mode, and startup fails without a key | design: Config; tasks 1.4, 2.3 |
| A4 | 2.1 | "Conversation exchange completes" is undefined | An exchange is one user transcript paired with the next agent response | design: Ingestor step 1 |
| A5 | 2.2 | "Gemini analysis results" and "voice transcriptions" assume a Gemini step in every turn | Gemini analysis is attached only when the `look` tool fired in that turn. Transcripts come from the ElevenLabs callbacks | design: Ingestor; tasks 4.2, 4.4 |
| A6 | 3.1 | A "unique" facial signature cannot be guaranteed. Embeddings are matched by similarity, with false accepts and rejects | Reword to "a facial signature sufficient to re-identify the same person". Add a threshold and a 2-consecutive-match guard | design: Face Recognition; task 6.2 |
| A7 | 3 | No enrollment flow, no handling of unknown people, no rule for multiple faces | Enroll only after spoken consent (`remember_me`). Unknown gives anonymous. Identify the largest face only | design: Consent; tasks 6.2, 6.4 |
| A8 | 3.4, 3.5 | How does the ElevenLabs agent "use" profile data? Its behaviour is set in the ElevenLabs dashboard, not in this repo | `recall` client tool returns profile facts and memories. The agent prompt must be updated externally (tracked as a task) | design: Consent; tasks 5.6, 6.4, 6.5 |
| A9 | 4.2 | "Semantic similarity" needs an Atlas Vector Search index and an embedding call. Neither exists offline or on a missing index | Ranking order is semantic → lexical → recency. Offline gets recency + keyword only | design: Retriever; task 5.5 |
| A10 | 4.4 | "Sensitive personal data" is undefined | Three levels (`public`, `personal`, `sensitive`) assigned by keyword rules. When uncertain, classify up. Sensitive records are not embedded and are never retrieved without `use_for_personalization` | design: Ingestor, Retriever; tasks 2.5, 5.2 |
| A11 | 5.1 | Encrypting message bodies blocks server-side text search | Bodies are encrypted. The searchable surface is `context.topics` / `context.entities`, drawn from a fixed non-personal vocabulary (no person names) | design: Retriever path B |
| A12 | 5.2 | "Where consent is required" is undefined | Required for: linking anything to an identity, storing face signatures, and personalization. Not required for anonymized, PII-scrubbed transcripts | design: Ingestor, Consent |
| A13 | 5.4 | "A mechanism" to delete is undefined | Voice command `forget_me` plus an admin script. Deletion covers Atlas, the local store, and the outbox, and returns a report | design: Deletion; task 6.6 |
| A14 | 5.5 | "Configured" retention, and no rule for profiles or face signatures | Interactions: TTL from `RETENTION_DAYS` (default 90). Profiles and faces: purge after `PROFILE_RETENTION_DAYS` of inactivity (default 180). **Open question for the team** (see section 6) | design: Deletion and Retention; task 7.1 |
| A15 | 7.1, 7.3 | "Typical query patterns" and "acceptable performance" are unmeasurable | Define: one query, top-5, ≤10,000 records, Atlas M0 from the demo network, 500 ms p95. If the network makes it unattainable, degrade to the lexical/recency path instead of missing the budget | design: Retriever; task 7.5 |
| A16 | 8.5 | "Serialize images" conflicts with privacy: nothing in the design needs stored images | Images are never stored. Only encrypted embeddings. Suggest deleting "images" from the criterion | design: Face Recognition |
| A17 | 9.4 | "Data corruption is detected": detection method undefined | Plaintext checksum stored beside ciphertext, verified on read. Corrupt docs are skipped, logged, and recovered from the fallback copy if present | design: Error Handling; task 7.4 |
| A18 | 9.5 | "Alert" has no audience or channel | ERROR-level log and a 60 s health line. No external paging in scope | design: Error Handling; task 7.3 |
| A19 | 10.5 | "Setup scripts for cluster provisioning" is ambiguous: cluster creation needs Atlas admin credentials | Scope the script to collections, validators, and indexes. Cluster creation is a documented manual step | design: Indexes; task 5.4 |
| A20 | 7.1 | Typo: "SHALl" | Fix | section 5 |

## 3. Conflicts

### Within this spec
| # | Conflict | Resolution |
|---|---|---|
| C1 | R2.1 (store every exchange) vs R5.2 (consent before storing personal data) | Anonymous-by-default: store scrubbed transcripts without identity. Identity links require consent. Earlier anonymous records are never retro-linked |
| C2 | R5.1 (encrypt PII) vs R4.2 (semantic search) | Embeddings derive from plaintext and can leak meaning. Sensitive records are not embedded. This risk is called out for the security notes and the optional client-side field-level encryption stretch (task 9.4) |
| C3 | R3.2 (store face signatures) vs R5 (privacy) | Face signatures are biometric identifiers. They are stored only with `store_face_data` consent, encrypted, with no images. Because this is a public event, recommend a visible notice near the robot |
| C4 | R1.2/R6.5 (works offline) vs R4.2 (semantic ranking) | See A9 |

### Cross-spec (`positivity-encouragement-bot`)
| # | Conflict | Resolution |
|---|---|---|
| X1 | Positivity R6.3 ("no PII without explicit consent") | Aligned with M-R5.2. Positivity is stateless by default and persists only through this store's consent flow |
| X2 | Positivity R5.4 (return interactions) duplicates M-R3 (recognition) | Positivity consumes `IMemoryStore` and `PresenceState`. It does not build its own store |
| X3 | Positivity R6.1/6.2 (frames stay local) vs the existing `look()` (sends the full frame to Gemini) | Not a defect of this spec. Face recognition here is fully local, and only crops reach `FaceRecognizerSF`. The `look()` behavior is addressed in the positivity analysis |
| X4 | Both specs want to react to a newly detected face | One `camera_loop` hook per subscriber. Neither may block the loop (M-R6.4) |

## 4. Testability

Legend: **PBT** property-based test, **UT** unit/example, **IT** Atlas integration, **M** manual (hardware or live demo).

| Req | Criteria | Method | Notes |
|---|---|---|---|
| 1 | 1.1 | IT | Needs a live Atlas connection |
| | 1.2 | PBT (P1) | Inject failure modes |
| | 1.3 | UT | Fake clock for ping cadence and state transitions |
| | 1.4 | PBT (P4) | |
| 2 | 2.1, 2.2 | PBT (P2), UT | Fake ElevenLabs callbacks |
| | 2.3 | PBT (P3) | |
| | 2.4 | PBT (P2, P16) | |
| 3 | 3.1 | PBT (P5) | On synthetic embeddings. Accuracy on real faces is a manual check |
| | 3.2 | PBT (P3) | |
| | 3.3 | PBT (P6) | |
| | 3.4, 3.5 | M | Behaviour of the ElevenLabs agent after prompt update |
| 4 | 4.1 | UT, IT | |
| | 4.2 | PBT (ranking function), IT | Vector path needs Atlas |
| | 4.3 | M | Live conversation |
| | 4.4 | PBT (P7) | |
| 5 | 5.1 | PBT (P4) | |
| | 5.2 | PBT (P3, P7), M | Voice consent flow is manual |
| | 5.3 | PBT (P8) | |
| | 5.4 | PBT (P9) | |
| | 5.5 | PBT (P10), IT | TTL index on Atlas |
| 6 | 6.1–6.3 | M, UT | Compare behaviour with `MEMORY_ENABLED=false` |
| | 6.4 | M | Measure servo/frame rate with memory offline and online |
| | 6.5 | PBT (P1, P17) | |
| 7 | 7.1 | PBT (P17), IT | Latency on Atlas is measured, not property-tested |
| | 7.2 | UT | Assert `enqueue` returns in under 5 ms |
| | 7.3 | IT | 10,000-record seed |
| | 7.4 | IT | Index existence |
| | 7.5 | PBT (P11) | |
| 8 | 8.1, 8.3 | PBT (P12), IT | |
| | 8.2 | PBT (P13) | |
| | 8.4 | PBT (P2) | |
| | 8.5 | UT | Embedding serialization round-trip |
| 9 | 9.1 | PBT (P1), M | |
| | 9.2 | PBT (P14) | |
| | 9.3 | UT, PBT (P16) | Backoff timing with a fake clock |
| | 9.4 | UT | Corrupt a stored blob |
| | 9.5 | UT | Assert alert log on threshold |
| 10 | 10.1, 10.3, 10.4 | PBT (P15), UT | |
| | 10.2 | UT | |
| | 10.5 | IT | Idempotent provisioning script |

## 5. Suggested Edits to `requirements.md` (not applied)

1. **1.1**: "…establish a secure connection (TLS) to MongoDB Atlas using credentials from configuration."
2. **1.2**: append "Locally stored data SHALL be synchronized to MongoDB Atlas when the connection is restored, without duplicating records."
3. **1.4**: replace with "WHEN persistence is enabled, THE Memory_Store SHALL encrypt all PII fields and SHALL refuse to start without an encryption key."
4. **2.2**: "…timestamp, conversation context, voice transcriptions, and, WHERE the vision tool was used in the exchange, Gemini analysis results."
5. **3.1**: "…SHALL generate a facial signature that allows the same person to be re-identified."
6. **3 (new criterion)**: "THE JARVIS_System SHALL register a new User_Profile and store a facial signature only after the person gives explicit spoken consent."
7. **4.2**: append "WHEN semantic ranking is unavailable, THE Memory_Retriever SHALL fall back to keyword and recency ranking."
8. **5.2**: "…SHALL request explicit permission before linking data to an identity, storing facial signatures, or using stored data for personalization."
9. **5.5**: add "and SHALL purge inactive User_Profiles and facial signatures after a configured inactivity period."
10. **7.1 / 7.3**: define "typical" as "a single query returning at most five results from a store of up to 10,000 records"; fix "SHALl".
11. **8.5**: remove "images"; state that facial images are never stored.
12. **10.5**: "…setup scripts that create the required collections, validators, and indexes. Cluster creation is out of scope."

## 6. Open Questions for the Team

1. **Profile retention** (A14): is 180 days of inactivity acceptable for profiles and face signatures, or should everything follow the 90-day interaction TTL?
2. **Consent wording**: who approves the spoken consent script? A public hackathon booth may warrant a printed sign in addition.
3. **Atlas access**: is there an Atlas M0 cluster, and can Search/Vector Search indexes be created on it? The design assumes yes. If not, the semantic path is demoed on a local Atlas deployment or skipped.
4. **Embedding model**: confirm the current Gemini embedding model name and dimension with `genai.list_models()` before creating the Vector Search index. The index dimension must match.
5. **Demo machine**: `robot.py` uses `COM3` (Windows). Confirm the OS so the face-recognition provider is chosen correctly (OpenCV SFace works on both).

## 7. Traceability Matrix

| Req | Design sections | Tasks | Properties |
|---|---|---|---|
| 1 Connection | Configuration, Connection Manager, Stores | 1.4, 1.6, 2.3, 3.2, 3.3, 3.4 | P1, P4 |
| 2 Storage | Ingestor, Data Models | 3.7, 4.1, 4.2, 4.4 | P2, P3 |
| 3 Recognition | Face Recognition, Consent | 2.7, 6.1, 6.2, 6.4, 6.5 | P3, P5, P6 |
| 4 Retrieval | Retriever | 2.5, 4.1, 5.1, 5.2, 5.5, 5.6 | P7, P17 |
| 5 Privacy | Ingestor (scrub, classify, encrypt), Consent, Deletion and Retention | 2.3, 2.5, 4.2, 5.4, 6.4, 6.6, 7.1 | P4, P7, P8, P9, P10 |
| 6 Integration | Threading Model, `robot.py` integration, `NullMemory` | 3.5, 4.4, 5.6, 6.2, 6.3, 8.1, 10.2 | P1, P17 |
| 7 Performance | Retriever, Threading Model, Indexes | 4.2, 5.1, 5.4, 5.5, 7.5 | P11, P17 |
| 8 Schema | Data Models, Schema Validation and Migration | 2.1, 2.2, 4.1, 4.2 | P2, P12, P13 |
| 9 Resilience | Connection Manager, Stores, Error Handling | 3.2, 3.4, 7.3, 7.4, 8.1, 8.2 | P1, P14, P16 |
| 10 Configuration | Configuration, Indexes, Dependencies | 1.1, 1.4, 1.6, 5.4, 9.3 | P15 |

Note: the earlier draft design claimed "all 44 acceptance criteria". The actual count is **47** (4+4+5+4+5+5+5+5+5+5).

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Venue Wi-Fi makes the 500 ms budget unreachable (embedding call + Atlas round trip) | High | Medium | Timeouts with lexical/recency degrade path; pre-warm the embedder; demo on a hotspot |
| ElevenLabs agent ignores `recall` because the dashboard prompt was not updated | Medium | High | Explicit task 5.6 with the prompt text checked into `docs/` |
| Face false-match greets the wrong person by name | Medium | High | Threshold + 2-consecutive-match guard; never greet by name below a higher confidence bar |
| Atlas M0 search-index limits | Low-Medium | Medium | Provisioning script prints manual steps; recency and lexical paths still demo |
| Biometric consent in a public setting | Medium | High | Voice consent, visible notice, `forget_me`, no images stored, encrypted embeddings |
| Extra load on the camera thread hurts servo tracking | Low | High | `submit()` is non-blocking and drops when busy; task 6.3 measures frame rate |
