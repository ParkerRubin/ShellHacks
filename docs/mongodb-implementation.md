# MongoDB implementation notes

The original README was empty; `robot.py`, `check.py`, and `firmware.ino` were the
entire runtime. The MongoDB design is implemented as synchronous components with
daemon workers. The positivity feature is left for its own implementation, with
shared `PresenceState`, `IMemoryStore`, and the memory facade available to it.

## Decisions applied

- SQLite is an encrypted **write-through mirror**, not only an outage destination.
  A transaction writes each record and outbox revision together. Atlas synchronization
  runs outside the local lock. Replacing an outbox item creates a new sequence
  number, so acknowledging an older upload cannot erase a newer revision.
- Deletion persists a local UUID tombstone, removes pending uploads and private
  documents, and queues a remote delete. Replay serializes remote writes/deletes.
  Late ingestor work and profile hydration respect tombstones. This fixes the
  draft's missing offline-deletion reconciliation behavior.
- One authenticated encrypted `private` payload replaces scattered encrypted
  fields. Gemini summaries and profile preferences are encrypted too. The integrity
  checksum is inside ciphertext, avoiding a public hash of low-entropy private text.
- Anonymous storage retains fixed-vocabulary topics only. Regex scrubbing remains
  a utility but cannot safely anonymize arbitrary speech. This intentionally limits
  the draft's “store every exchange” requirement before consent.
- Both stored and query embeddings use topic tags only. This reduces semantic
  fidelity but avoids transmitting saved personal text to an embedding API.
- Recall uses a bounded, single daemon worker rather than an executor with an
  unbounded submission queue. It waits at most 480 ms; a hung worker causes
  subsequent requests to return empty immediately until it finishes.
- Recognition uses YuNet landmark detection plus SFace alignment. A Haar rectangle
  alone is not sufficient for `FaceRecognizerSF.alignCrop`. Model files are optional;
  failure disables enrollment without disabling conversation memory.
- Startup configuration errors disable memory loudly, consistent with the design's
  `build_memory()` never-raises boundary. No plaintext persistence mode exists.
- Model listing and a real 768-dimension probe succeeded for `gemini-embedding-001`
  with the configured Gemini key. The API adapter uses the current `google-genai`
  SDK; the existing vision code is unchanged.

## Validation and remaining external work

Automated coverage includes encryption/property tests, callback consent snapshots,
identity boundaries, full-history lexical matching, outage replay, remote-upsert
and deletion races, stale outbox acknowledgments, corruption fallback, retention,
concurrent writes, strict confirmation booleans, face match guards, non-blocking
camera submission, model-backfill failure, and recall timeouts. A disposable
local demo and 10,000-record benchmark are provided.

Live Atlas tests are opt-in; no Atlas URI or encryption key was available in the
workspace. Atlas search pipelines and index provisioning need verification against
the actual cluster. The ElevenLabs dashboard prompt/tool changes, camera/servo
and audio regressions, real face accuracy, and Charts dashboard have not been
performed. No image-based recognition accuracy is claimed from synthetic vectors.

The migration registry deliberately rejects unknown versions; there is no historical
schema to migrate yet. `scripts.migrate` validates/replays local upgrades. Optional
dlib, client-side MongoDB field encryption, rolling operation failure-rate alerts,
and automatic Charts configuration are not implemented. Health logs include state,
outbox depth, and prolonged-offline errors.

Search/embedding reference APIs:
[PyMongo indexes](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/indexes/),
[Gemini embeddings](https://ai.google.dev/gemini-api/docs/embeddings),
[OpenCV alignment and recognition](https://docs.opencv.org/4.12.0/d0/dd4/tutorial_dnn_face.html).

## Implementation-session results

- `python -m pytest -q`: **26 passed, 1 skipped** (Atlas URI absent).
- Local demo and enabled/disabled/bad-key smoke checks passed.
- 10,000-record local benchmark: approximately **1.7 ms p95** for its seeded
  topic queries; this is not an Atlas latency measurement.
- Gemini model listing and a live 768-dimension embedding probe passed.
- Downloaded YuNet/SFace models loaded successfully; a blank frame returned no
  signature. Real-person matching accuracy remains untested.
- Python compilation, Ruff's basic error/import checks, and `git diff --check`
  passed. Secrets, local databases, virtual environment and models are gitignored.
