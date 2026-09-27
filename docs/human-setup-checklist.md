# Human setup checklist: MongoDB memory

The MongoDB memory code is implemented and tested against mocks. Three things
need a person with the right accounts and hardware; an agent cannot do them.
Work through them in order, and tick each box as you go.

Related docs: [README](../README.md) · [ElevenLabs tool definitions](elevenlabs-agent-prompt.md) · [implementation notes](mongodb-implementation.md) · [sponsor notes](mongodb-prize.md)

## 1. Atlas cluster and configuration

**Why a person is needed:** creating a cluster needs your Atlas account, and the encryption key must be generated and stored by you.

- [ ] Create an Atlas cluster (a free M0 works) and a database user with access to one database.
- [ ] In Atlas **Network Access**, add the demo machine's IP address. Avoid `0.0.0.0/0`.
- [ ] Copy the `mongodb+srv://...` connection string.
- [ ] Generate the encryption key **once**:
  ```bash
  python scripts/gen_key.py
  ```
- [ ] Save the key somewhere secure outside Git (a password manager). If you lose it or replace it, existing encrypted data becomes unreadable.
- [ ] In `.env` (not `.env.example`), set:
  - `MEMORY_ENABLED=true`
  - `MONGODB_ATLAS_URI=<your connection string>`
  - `MONGODB_DB=jarvis_dev` (or `jarvis_demo` for the booth)
  - `ENCRYPTION_KEY=<the generated key>`
- [ ] Confirm the embedding model works for your Gemini account:
  ```bash
  python -m scripts.check_embeddings
  ```
  If the model or dimension differs from `EMBEDDING_MODEL` / `EMBEDDING_DIM` in `.env`, update them before provisioning. Do not change them later on an existing vector index.
- [ ] Provision collections, validators, indexes and search indexes:
  ```bash
  python -m scripts.provision
  ```
- [ ] Wait until `interactions_vec` and `interactions_text` show **READY** in Atlas (Search & Vector Search tab). If the script says it could not create them, create them in the Atlas UI using the JSON it printed.
- [ ] Verify against the real cluster:
  ```bash
  python -m scripts.demo_memory --atlas
  ```
  Then, optionally, run the live test against a **separate** test URI (it creates and drops its own `jarvis_test_*` database):
  ```bash
  MONGODB_ATLAS_URI_TEST="<test uri>" python -m pytest -m atlas -q
  ```
- [ ] Note any failures. In particular, watch for `$search` / `$vectorSearch` errors and recall latency. These paths have never run against real Atlas.

**Done when:** provisioning succeeds, both search indexes are READY, and `demo_memory --atlas` completes.

## 2. ElevenLabs dashboard

**Why a person is needed:** registering tools in `jarvis.py` does not change the hosted agent. Run `python setup_agent.py --set-prompt` (it registers everything in `tools.json`, including the memory tools, and their prompt), or describe them in the dashboard by hand.

- [ ] Open the existing agent (`ELEVENLABS_AGENT_ID` in `.env`, or the default in `jarvis.py`) in the ElevenLabs dashboard.
- [ ] Add three **client tools**, exactly as defined in [elevenlabs-agent-prompt.md](elevenlabs-agent-prompt.md):
  - `recall`: `query` (string, required)
  - `remember_me`: `confirmed` (boolean, required), `name` (string, optional)
  - `forget_me`: no parameters
- [ ] If the dashboard offers a "wait for response" option for client tools, turn it on for all three, since the agent needs the return value to answer.
- [ ] Paste the memory paragraph from that doc into the agent's **system prompt**. Do not remove the existing `look` tool or the current voice settings.
- [ ] Review the consent wording in the prompt with your team. It is what a person hears before their face signature is saved.
- [ ] Save and publish the agent.
- [ ] Run `python jarvis.py` and confirm the terminal shows no tool-registration errors. Say something like "do you remember what we talked about?" and check that the console shows the `recall` tool firing, and that an empty result does not derail the conversation.

**Done when:** the agent calls `recall`, `remember_me` and `forget_me` correctly in a live conversation.

## 3. Real-person checks on the demo machine

**Why a person is needed:** face accuracy, audio, and servo behaviour can only be judged on the actual camera, microphone, speakers and Arduino. Nothing has been measured on real faces yet.

Set up: same machine and lighting as the demo, servo connected, `CAM_INDEX` and `SERVO_PORT` set in `.env`.

Run the checks in three modes: memory **on** (Atlas configured), **offline** (turn off Wi-Fi after a successful run, or set a bad `MONGODB_ATLAS_URI`), and **off** (`MEMORY_ENABLED=false`). Steps 3a-3e need memory, so skip them for **off**, which registers no memory tools. Step 3f applies to all three modes.

### 3a. Enroll
- [ ] Stand in front of the camera alone, one face visible.
- [ ] Ask JARVIS to remember you. Confirm it asks for explicit permission, and only saves after you clearly say yes.
- [ ] Confirm it reports success. Give a name if it asks.
- [ ] Check the console for memory errors, and (with Atlas) that documents appear in the `jarvis_*` database with **no readable transcripts** (only a `private` ciphertext field).

### 3b. Leave and return
- [ ] Walk out of frame for at least a few seconds, then come back.
- [ ] Confirm JARVIS recognizes you (recall returns your profile) and does not call you by name until recognition is confident.
- [ ] Have a second person stand in front of the camera. Confirm they are **not** greeted by your name or given your history.

### 3c. Recall
- [ ] Mention a topic you discussed earlier (for example "python" or "robotics"), then ask what you talked about before.
- [ ] Confirm JARVIS uses the memory when it exists and stays helpful, without inventing anything, when it doesn't.
- [ ] Note that recall is topic-level (a small fixed vocabulary), so it will not remember arbitrary details.

### 3d. Forget
- [ ] Say "forget me". Confirm JARVIS reports the result accurately (including "remote deletion queued" if Atlas is unreachable).
- [ ] Return to the camera. Confirm you are treated as a stranger with no saved history.
- [ ] With Atlas, confirm the profile, face signature and interactions for that user are gone from the database.

### 3e. Outage behaviour (offline mode)
- [ ] Turn the network off mid-conversation. Confirm conversation, `look` and servo tracking carry on normally.
- [ ] Have a few exchanges, then turn the network back on. Wait a minute and confirm the exchanges appear in Atlas once, with no duplicates.

### 3f. Servo and frame rate
- [ ] Watch the camera window and servo with memory **off**, then **on**, then **offline**. The pan movement and frame rate should feel the same in all three. If it looks slower with memory on, note the numbers (frames per second before and after).
- [ ] Confirm the ESC key still quits promptly.
- [ ] Confirm voice conversation, the `look` tool and servo pan still work as before in all three modes.

**Done when:** every box passes in every mode that supports it, and any failures are written down (what happened, which mode, what you saw in the console).

## Report back

Add a short note here or in an issue when finished, so the next round of work has facts to build on:

| Item | Result | Notes (fps, latency, errors) |
| --- | --- | --- |
| Atlas provisioning | | |
| Search indexes READY | | |
| ElevenLabs tools firing | | |
| Enroll and recognize | | |
| Second person not misidentified | | |
| Recall | | |
| Forget | | |
| Outage and replay | | |
| Servo / fps unchanged | | |

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Memory tools missing / agent never calls them | Dashboard tools or prompt not saved and published (section 2) |
| "memory_disabled" in the console | `ENCRYPTION_KEY` missing or invalid, or `MEMORY_ENABLED` not `true` |
| Enrollment says face recognition is unavailable | Models not downloaded: run `python -m scripts.fetch_models` |
| Enrollment fails with a face clearly visible | Face detector may need more margin around the face. Note it in the report |
| Atlas connection fails | IP not on the Network Access list, wrong URI, or venue Wi-Fi blocking port 27017 (try a phone hotspot) |
| Old data unreadable after a restart | The `ENCRYPTION_KEY` changed |
