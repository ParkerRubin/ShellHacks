# MongoDB Atlas demo

JARVIS remembers consented interactions while its camera and voice threads keep
working during database outages. The local mirror encrypts the same private
payload as Atlas, and the outbox reconciles records and deletions on reconnect.

| Atlas feature | Code | Demo |
| --- | --- | --- |
| Persistent documents | `jarvis/memory/mongo_store.py` | Show encrypted `private` payloads and non-personal tags |
| Vector Search | `MongoStore.search`, `scripts/provision.py` | Run topic-level semantic recall with the verified Gemini embedding model |
| Atlas Search | `MongoStore.search` | Disable embeddings and run lexical topic recall |
| TTL index | `scripts/provision.py` | Show `expires_at`, date type, and `expireAfterSeconds: 0` |
| JSON Schema | `schemas.py`, `scripts/provision.py` | Show a rejected malformed interaction |
| Offline replay | `local_store.py`, `store.py` | Disconnect, talk, reconnect, confirm UUID records appear once |
| Deletion | `consent.py`, `store.py` | Forget while offline; show immediate local removal and eventual Atlas deletion |

Run `python -m scripts.demo_memory --atlas` after provisioning and waiting for search
indexes to become ready. Atlas Search is eventually consistent, so newly seeded
records may not immediately appear; allow index catch-up before judging results.
The demo cleans up its own synthetic profile/history and retains a deletion
outbox entry if Atlas cannot be reached.

Create Atlas Charts manually against the demo database:

- Interactions per day: count grouped by `timestamp` date.
- Top topics: unwind/group `context.topics` and count.
- Returning visitors: count sessions per non-null `user_id`.

No Charts dashboard or screenshot has been created yet. Fallback events currently
appear in local health logs, not a metrics collection, so do not claim a fallback
chart is implemented. Do not expose decrypted transcripts, face vectors, names,
connection strings, or encryption keys in judging screenshots.

Recall is limited to the fixed roughly two-dozen-word topic vocabulary. Embeddings
contain those tags only, not conversation text; the demo does not demonstrate
general semantic memory or recall of arbitrary facts.
