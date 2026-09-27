# Voice spike — NOT RUN / UNVERIFIED

Option A is implemented provisionally because it was requested. There is no
hardware evidence yet for echo, device coexistence, speech onset, voice warmth,
or the live agent's behavior. No successful result has been fabricated.

On the actual demo machine, install the requirements and the ElevenLabs audio
extra (`pip install 'elevenlabs[pyaudio]'`). Supply `ELEVENLABS_API_KEY`,
`ELEVENLABS_AGENT_ID`, and `POSITIVITY_VOICE_ID` through the environment or your
ignored `.env`; choose the same voice as the hosted agent. Run:

```bash
python -m scripts.voice_spike --option all
```

The script opens the real conversation, tests a fixed non-personal sentence,
asks the operator for observations, and appends results to this file. It saves
counts, timing and the operator's notes, never the captured transcript text.
First PCM arrival is measured for A/C; actual speaker onset needs an operator's
stopwatch or recording. Do not include private names or credentials in notes.

- **A:** separate streaming PCM playback while the conversation is open. Check
  speaker contention and unwanted agent responses. Local transcript suppression
  cannot mute audio already received by the hosted agent.
- **B:** call the SDK's `send_user_message` facility and observe the reply. If the
  installed SDK lacks it, report unsupported. A contextual update is not assumed
  to produce speech, so this script does not silently substitute one.
- **C:** end the session, play TTS, then start a fresh conversation. Check startup
  latency, device handoff and loss of conversational context.

Then use the actual positivity notice and test “no thanks” both during playback
and during the following two seconds, plus “stop” and walking away. The MVP
accepts opt-out during NOTICE even while speaking. Echoing the notice's own
opt-out words may conservatively cancel a round; it must never permit egress.

Record the selected option only after listening, testing with the microphone and
speaker arrangement used at the booth, and reviewing all three outcomes. Tuning
with three teammates and the hardware FPS/30-minute soak remain separate checks.

References: [ElevenLabs streaming TTS](https://elevenlabs.io/docs/api-reference/text-to-speech/stream)
and [client-to-server events](https://elevenlabs.io/docs/eleven-agents/customization/events/client-to-server-events).
