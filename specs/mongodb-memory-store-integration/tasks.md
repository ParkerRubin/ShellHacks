# Implementation Plan: MongoDB Memory Store Integration

## Overview

Implements the design in `design.md` as a new `jarvis/memory/` package plus small, gated edits to `robot.py`. Python, synchronous, thread-based. Tasks marked `*` are optional (mostly tests) and can be skipped for the MVP path; everything unmarked is on the critical path for a working demo. Requirement references use `requirements.md` numbering (`R2.1` = Requirement 2, criterion 1).

**MVP path** (demo-ready, in order): 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10.

**Implementation update (2026-09-27):** The code path, local tests, demo and setup
scripts are implemented. See `docs/mongodb-implementation.md` for deviations
(anonymous topic-only storage, encrypted payload envelope, local-first outbox,
durable deletion tombstones, bounded recall worker). Unchecked live checkpoints
still require Atlas credentials, the ElevenLabs dashboard, or robot hardware.
No requirement wording has been changed.

## Tasks

- [ ] 1. Project scaffolding and configuration
  - [x] 1.1 Create `jarvis/__init__.py`, `jarvis/memory/__init__.py`, and `requirements.txt` (pymongo[srv], cryptography, jsonschema, numpy, pytest, hypothesis, mongomock)
    - Pin only what is needed; keep `elevenlabs`, `pyserial`, `google-generativeai`, `opencv-python`, `python-dotenv` as they are used today
    - _Requirements: 10.1, 10.4_
  - [x] 1.2 Rewrite `.gitignore` without the leading UTF-8 BOM; add `data/`, `*.sqlite3`, `.pytest_cache/`, `.hypothesis/`
    - Verify with `git check-ignore -v .env`
    - _Requirements: 10.4_
  - [x] 1.3 Implement `jarvis/memory/errors.py` (`MemoryStoreError`, `StoreConnectionError`, `ValidationError`, `PrivacyError`, `FallbackError`)
    - _Requirements: 9.2_
  - [x] 1.4 Implement `jarvis/memory/config.py` `MemoryConfig.from_env()` with per-environment DB names and aggregated, actionable validation errors
    - `MEMORY_ENABLED=false` short-circuits everything else
    - Missing URI gives local-only mode (warning); missing `ENCRYPTION_KEY` with persistence enabled is an error
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  - [ ]* 1.5 Write property test for configuration validation
    - **Property 15: Configuration validation**
    - **Validates: Requirements 10.3, 10.4**
  - [x] 1.6 Add `scripts/gen_key.py` (prints a fresh Fernet key and rotation instructions) and add `MONGODB_ATLAS_URI`, `MONGODB_DB`, `ENCRYPTION_KEY`, `RETENTION_DAYS`, `MEMORY_ENABLED` placeholders to a new `.env.example` (no real values)
    - _Requirements: 10.1, 10.4, 10.5_

- [ ] 2. Schemas, encryption, and privacy primitives
  - [x] 2.1 Implement `jarvis/memory/schemas.py`: JSON Schemas for `interactions`, `user_profiles`, `face_signatures`, `system_config`; `SCHEMA_VERSION = "1.0"`; `validate(collection, doc)`; `MIGRATIONS` registry and `upgrade(doc)`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [ ]* 2.2 Write property tests for schema validation and migration
    - **Property 12: Schema validation completeness**
    - **Property 13: Migration compatibility**
    - **Validates: Requirements 8.1, 8.2, 8.3**
  - [ ] 2.3 Implement `jarvis/memory/crypto.py`: `FieldCipher` (Fernet) with `encrypt_fields(doc, fields)`, `decrypt_fields(...)`, `key_id`, plaintext checksum helper
    - Status: Encryption and integrity failure handling exist; persistent `corrupt: true` marking remains in 7.4.
    - Decrypt failure raises a typed error that callers convert to `corrupt: true`
    - _Requirements: 1.4, 5.1, 9.4_
  - [x]* 2.4 Write property test for PII encryption round-trip and wrong-key failure
    - **Property 4: PII encryption**
    - **Validates: Requirements 1.4, 5.1**
  - [x] 2.5 Implement `jarvis/memory/privacy.py`: `scrub_pii(text)` (email/phone regexes), `classify_privacy(text, consent)`, `extract_context(text)` (topics, entities, sentiment via simple keyword rules)
    - _Requirements: 5.3, 4.4_
  - [ ]* 2.6 Write property test for anonymization
    - **Property 8: Anonymization preserves function**
    - **Validates: Requirements 5.3**
  - [x] 2.7 Define dataclasses in `jarvis/memory/models.py`: `InteractionRecord`, `UserProfile`, `FaceSignature`, `HealthStatus`, `DeletionReport`, `PresenceState`; and the `IMemoryStore` Protocol
    - _Requirements: 8.1, 3.3_

- [ ] 3. Local fallback store and resilient routing
  - [x] 3.1 Implement `jarvis/memory/local_store.py` `LocalStore` (SQLite, single lock): interactions, profiles, faces, `outbox`; recency and keyword retrieval; `purge_expired()`
    - Stores the same encrypted documents as JSON
    - _Requirements: 1.2, 9.1, 5.5_
  - [x] 3.2 Implement `jarvis/memory/connection.py` `ConnectionManager`: single `MongoClient` (`serverSelectionTimeoutMS=2000`), `with_retry` (3 tries, `1.5**n` backoff), health-ping daemon thread (30 s), state machine `ONLINE/DEGRADED/OFFLINE`, `health()`
    - Status: Implemented: one client/retry state machine; the store maintenance daemon owns the 30 s ping. Live connectivity unverified.
    - _Requirements: 1.1, 1.3, 9.3, 9.5_
  - [x] 3.3 Implement `jarvis/memory/mongo_store.py` `MongoStore` implementing `IMemoryStore` (upsert by client `_id`, `delete_user_data`, profile and face operations)
    - Status: Implemented as the internal encrypted-document backend; ResilientMemoryStore exposes IMemoryStore. Mock-backed tests pass; Atlas unverified.
    - _Requirements: 1.1, 2.1, 5.4_
  - [x] 3.4 Implement `jarvis/memory/store.py` `ResilientMemoryStore`: write-through with fallback and outbox append; reads by state; `outbox.replay()` on reconnect (idempotent upserts); never raises at the public boundary
    - _Requirements: 1.2, 6.5, 9.1, 9.2, 9.3_
  - [x] 3.5 Implement `NullMemory` (same surface as the real facade, all no-ops) and `build_memory()` factory that never raises
    - _Requirements: 6.1, 6.5_
  - [ ]* 3.6 Write property tests
    - **Property 1: Connection failure degrades gracefully**
    - **Property 16: Outbox idempotence**
    - **Property 14: Error logging completeness**
    - **Validates: Requirements 1.2, 6.5, 9.1, 9.2, 9.3**
  - [ ]* 3.7 Write property test for data round-trip integrity across Mongo (mongomock) and `LocalStore`
    - **Property 2: Round-trip integrity**
    - **Validates: Requirements 2.1, 2.2, 2.4, 8.4**
  - [ ] 3.8 Checkpoint: run `pytest`; run `python robot.py` with `MEMORY_ENABLED=false` and confirm behaviour is identical to today
    - Status: Mocked robot hooks and unit tests pass; actual disabled-mode hardware run remains unverified.

- [ ] 4. Write path: ingestor
  - [x] 4.1 Implement `jarvis/memory/embeddings.py`: `Embedder` interface and `GeminiEmbedder` (`genai.embed_content`, 3 s timeout); confirm the model name and dimension against `genai.list_models()` and record them in `.env.example`
    - Extend `check.py`-style listing to filter `embedContent`
    - _Requirements: 4.2, 8.5_
  - [x] 4.2 Implement `jarvis/memory/ingestor.py` `MemoryIngestor`: bounded queue (200, drop-oldest with warning), worker thread; pipeline assemble → validate → scrub → classify → embed (or `embedding_pending`) → encrypt → store; `on_user`, `on_agent`, `on_gemini`, `enqueue`
    - Never blocks or raises to the caller
    - Anonymous records when no consent (`user_id = null`, no face link)
    - _Requirements: 2.1, 2.2, 2.3, 5.2, 5.3, 7.2, 8.3_
  - [x] 4.3 Background embedding backfill for `embedding_pending` records
    - _Requirements: 4.2, 9.3_
  - [x] 4.4 Wire the ingestor into `robot.py`: wrap `callback_agent_response` / `callback_user_transcript`; optionally publish the `look` result via `on_gemini`
    - Edits are additive; the existing prints stay
    - _Requirements: 2.1, 6.1, 6.2, 6.3_
  - [ ]* 4.5 Write property test for face-conversation association and consent gating
    - **Property 3: Face-conversation association**
    - **Validates: Requirements 2.3, 3.2, 5.2**
  - [x]* 4.6 Write integration test: fake ElevenLabs callback sequence produces the expected `InteractionRecord`s; measure `enqueue` latency
    - _Requirements: 2.1, 7.2_
  - [ ] 4.7 Checkpoint: talk to JARVIS with `MONGODB_ATLAS_URI` set; confirm documents appear in Atlas with encrypted text fields
    - Status: Live Atlas insertion verification requires the configured demo cluster.

- [ ] 5. Read path: retriever and `recall` tool
  - [x] 5.1 Implement `jarvis/memory/retriever.py` `MemoryRetriever.recall(query, user_id)`: 500 ms budget through `ThreadPoolExecutor` + `future.result(timeout)`; recency path first (works offline)
    - Status: Implemented with a bounded single daemon worker and 480 ms caller timeout, not ThreadPoolExecutor.
    - _Requirements: 4.1, 7.1_
  - [ ] 5.2 Add ranking function `rank(candidates, now)` = `0.7*similarity + 0.3*exp(-age_days/14)` and the final privacy filter (drops `sensitive` without consent; never returns another user's records)
    - Status: Ranking and final privacy filtering exist inside retrieval; extraction into standalone pure functions is not implemented.
    - Keep both pure, with no I/O
    - _Requirements: 4.2, 4.4, 5.2_
  - [ ]* 5.3 Write property tests
    - **Property 7: Privacy-aware filtering**
    - **Property 17: Bounded latency**
    - **Validates: Requirements 4.4, 5.2, 6.5, 7.1**
  - [x] 5.4 Implement `scripts/provision.py` (idempotent): create collections with `$jsonSchema` validators, indexes (user/time, TTL on `expires_at`, `face_signatures.user_id`, `user_profiles.updated_at`), and print the Vector Search and Atlas Search index definitions; create them via `pymongo` `create_search_index` where the cluster supports it
    - Atlas M0 supports search indexes; if creation via the driver fails, document the manual UI steps in the script output
    - _Requirements: 7.4, 10.5, 5.5_
  - [x] 5.5 Add semantic path (`$vectorSearch` with `user_id`/`privacy_level` pre-filter) and lexical path (`$search` over `context.topics`/`context.entities`), with fallback order semantic → lexical → recency
    - _Requirements: 4.2, 7.1, 7.3_
  - [ ] 5.6 Register the `recall` client tool in `robot.py` next to `look`, and update the ElevenLabs agent's system prompt in the dashboard to describe when to call it
    - Status: Python tool and prompt file exist; the ElevenLabs dashboard update remains manual.
    - The prompt change is an external manual step. Record the exact prompt text in `docs/elevenlabs-agent-prompt.md`
    - _Requirements: 4.3, 6.2_
  - [ ]* 5.7 Write Atlas integration tests (`-m atlas`, skipped without `MONGODB_ATLAS_URI_TEST`): vector and text queries return the expected seeded records under 500 ms; TTL index and `$jsonSchema` rejection work
    - Status: Opt-in test covers validators/TTL/replay/deletion; live vector/text correctness and latency tests remain outstanding.
    - _Requirements: 4.1, 4.2, 7.1, 7.3, 8.3_
  - [ ] 5.8 Checkpoint: in a live session, refer to something said earlier and confirm JARVIS uses it; confirm a 500 ms timeout produces normal conversation, not silence
    - Status: Live voice recall and timeout behavior require ElevenLabs/audio hardware.

- [ ] 6. User recognition, consent, and deletion
  - [x] 6.1 Implement `jarvis/memory/faces.py`: `FaceSignatureProvider` protocol, `OpenCVSFaceProvider` (ONNX `FaceRecognizerSF`), `scripts/fetch_models.py` to download the model once; optional `DlibProvider` behind a try-import
    - Status: SFace/YuNet provider, model download and load check exist; optional dlib is not implemented.
    - _Requirements: 3.1_
  - [x] 6.2 Implement `FaceIdentifier` thread and `PresenceState`: throttled to one run per 2 s or on new face; cosine match against the cache of consented users; require 2 consecutive agreeing matches; set `may_greet_by_name` only at `FACE_GREET_THRESHOLD`; unknown gives `user_id=None`; `submit()` is non-blocking and drops when busy
    - Status: Two-match guard and non-blocking submit are tested with synthetic vectors; real face accuracy remains unverified.
    - _Requirements: 3.1, 3.3, 6.4, 7.2_
  - [ ] 6.3 Add one non-blocking line to `camera_loop` in `robot.py` that submits the largest face crop; verify servo tracking is unaffected (frame rate and pan behaviour)
    - Status: Camera hook exists; hardware fps and pan verification remain manual.
    - _Requirements: 6.4_
  - [x] 6.4 Implement `memory.consent` with `remember(confirmed)` and `forget()` and register `remember_me` / `forget_me` client tools; consent flags (`store_personal_data`, `store_face_data`, `use_for_personalization`) set explicitly; nothing persisted about the person before `confirmed=True`
    - Update the ElevenLabs agent prompt text (`docs/elevenlabs-agent-prompt.md`) with the consent question and tool usage
    - _Requirements: 3.2, 5.2, 5.4_
  - [x] 6.5 Implement personalization: on a recognized user, provide profile facts (name, style, topics, `avoid_topics`) to the agent via `recall` output at session start; respect `use_for_personalization`
    - _Requirements: 3.3, 3.4, 3.5_
  - [x] 6.6 Implement complete deletion across Mongo, `LocalStore`, and the outbox, returning `DeletionReport`; clear the face cache and `PresenceState`
    - _Requirements: 5.4_
  - [ ]* 6.7 Write property tests
    - **Property 5: Signature stability**
    - **Property 6: Profile retrieval**
    - **Property 9: Complete deletion**
    - **Validates: Requirements 3.1, 3.3, 5.4**
  - [ ] 6.8 Checkpoint: register yourself by voice, leave, return, and confirm you are greeted as known; say "forget me" and confirm the next visit treats you as a stranger
    - Status: Real-person enrollment, return recognition and deletion verification remain manual.

- [ ] 7. Retention, concurrency, and resilience hardening
  - [x] 7.1 Add `expires_at` to every interaction (`now + RETENTION_DAYS`), hourly `LocalStore.purge_expired()`, and a daily purge of profiles and face signatures inactive for `PROFILE_RETENTION_DAYS` (reuses the `delete_user_data` path)
    - _Requirements: 5.5_
  - [ ]* 7.2 Write property tests
    - **Property 10: Retention**
    - **Property 11: Concurrency safety**
    - **Validates: Requirements 5.5, 7.5**
  - [ ] 7.3 Add periodic health log line (60 s) and the failure-rate / prolonged-OFFLINE `ERROR` alert
    - Status: Periodic health/prolonged-offline logs exist; rolling failure-rate alert is not implemented.
    - _Requirements: 9.5_
  - [ ] 7.4 Add checksum verification on read and `corrupt: true` handling with fallback copy use
    - Status: Integrity verification and fallback recovery are tested; persistent corrupt marking is not implemented.
    - _Requirements: 9.4, 2.4_
  - [x]* 7.5 Performance check: seed 10,000 interactions, measure `recall` p95 and `enqueue` latency
    - Status: Disposable 10,000-record local recall benchmark and enqueue latency test pass; Atlas latency is unverified.
    - _Requirements: 7.1, 7.2, 7.3_

- [ ] 8. Outage resilience end to end
  - [ ] 8.1 Simulate an outage (bad URI at runtime or network off): confirm conversation continues, writes land in `LocalStore`/outbox, servo tracking is unaffected
    - Status: Outage unit/race tests pass; live voice/servo outage check remains manual.
    - _Requirements: 6.4, 6.5, 9.1_
  - [ ] 8.2 Restore the network and confirm the outbox drains with no duplicates in Atlas
    - Status: Mocked replay is idempotent; reconnection against Atlas remains unverified.
    - _Requirements: 9.1, 9.3_

- [ ] 9. Atlas prize features and demo
  - [ ] 9.1 Build an Atlas Charts dashboard (interactions per day, top topics, returning visitors, fallback events) on the demo database and save a screenshot to `docs/`
    - Status: Atlas Charts and a screenshot require manual cluster setup.
    - _Requirements: 7.4_
  - [x] 9.2 Write `scripts/demo_memory.py`: seeds sample data, shows a semantic query, a lexical query, and a deletion report
    - _Requirements: 7.1, 5.4_
  - [x] 9.3 Write the sponsor submission notes in `docs/mongodb-prize.md`, mapping each Atlas feature used to where it appears in the code
    - _Requirements: 10.5_
  - [ ]* 9.4 (Stretch) Replace app-level Fernet with MongoDB client-side field-level encryption
    - _Requirements: 1.4, 5.1_

- [ ] 10. Final checkpoint
  - [ ] 10.1 Run the full test suite (`pytest -q`, then `pytest -m atlas` with a test DB)
    - Status: Local suite passes; Atlas suite skips without MONGODB_ATLAS_URI_TEST.
  - [ ] 10.2 Run the manual checklist: ElevenLabs voice unchanged, Gemini `look` unchanged, servo tracking unchanged, all with memory ON, OFFLINE, and `MEMORY_ENABLED=false`
    - Status: Mocked callbacks pass; actual ElevenLabs, Gemini and servo regression checks remain manual.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - [x] 10.3 Update `README.md` (currently empty) with setup, `.env` variables, and the demo commands

## Notes

- The `requirements.md` files are not modified. Open questions and proposed wording changes are in `analysis.md`.
- Face signatures and any other biometric data are only stored after explicit voice consent (task 6.4). Until then the robot behaves as a stateless assistant with topic-only anonymous records.
- `positivity-encouragement-bot` depends on tasks 2.7, 3.4, 3.5, 6.2, and 6.4 (`IMemoryStore`, `NullMemory`, `PresenceState`, consent). Finish those first if both specs are being built in parallel.
