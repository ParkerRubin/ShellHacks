# JARVIS Robot - ShellHacks Project
# Claude Agent Initialization File

## PROJECT OVERVIEW
JARVIS is an interactive robot assistant with:
- Computer vision (OpenCV) for face tracking
- Google Gemini API for image analysis and NLP
- ElevenLabs for voice synthesis and conversational AI
- Arduino/servo hardware for physical movement
- Face tracking that moves camera/head to follow faces

## SPONSOR CHALLENGE ANALYSIS

### Already Qualified (Free to stack):
1. **MLH – Best Use of ElevenLabs** ✅ 
   - Already using ElevenLabs for voice synthesis
   - Prize: wireless earbuds

2. **MLH – Best Use of Gemini API** ✅
   - Already using Gemini for image analysis and conversation
   - Prize: MLH swag kits

### Best Fits for "Real-world Impact":
3. **Microsoft – "What's Missing?"** ⭐ STRONG FIT
   - Problem: Your robot helps with accessibility (visual assistance)
   - Not just a chatbot - robot has a job (face tracking, assistance)
   - Demo shows someone completing real tasks
   - Prize: Microsoft swag + "Intro to Physical AI" session

4. **State Farm – Auto Insurance Challenge** ⚠️ POTENTIAL FIT
   - Could pivot to focus on safety/risk reduction
   - Robot could monitor home/study environment for risks
   - Prize: backpacks and personal safes

5. **Waymo – Mobility Challenge** ⚠️ WEAK FIT
   - Transportation hack using public data
   - Less relevant to current robot capabilities
   - Prize: TBA

### New Target (Current Spec Focus):
6. **MLH – Best Use of MongoDB Atlas** 🎯 NEW TARGET
   - Adding MongoDB for data storage and memory
   - Prize: M5Stack IoT Kit
   - Spec created: mongodb-memory-store-integration

### Weak Fits (Don't Force):
- Assurant – "Take Control of AI" (AI privacy/spending awareness)
- Blackstone – Investor Experience (finance product)
- INIT – Building Together (student collaboration tools)
- Sperry Tech – GridLock (utility-grid GIS tool - full pivot)

## CURRENT SPEC STATUS
Feature: mongodb-memory-store-integration
Spec Type: Feature (Requirements-First workflow)
Requirements: Complete ✅
Design: Complete ✅ (.kiro/specs/mongodb-memory-store-integration/design.md)
Tasks: Complete ✅ (tasks.md)
Requirements analysis: Complete ✅ (analysis.md; requirements.md not yet edited, proposed rewordings pending team approval)

## REQUIREMENTS SUMMARY
1. MongoDB Atlas Connection Management
2. Conversation Memory Storage
3. User Recognition and Personalization
4. Contextual Memory Retrieval
5. Data Privacy and Security
6. Integration with Existing Systems
7. Performance and Scalability
8. Data Serialization and Schema
9. Error Handling and Resilience
10. Configuration and Deployment

## NEXT STEPS
1. ~~Create design.md for MongoDB integration~~ ✅
2. ~~Generate tasks.md implementation plan~~ ✅
3. Team review of each spec's analysis.md open questions, then approve or reject the proposed requirements.md rewordings
4. Implement MongoDB Atlas integration (tasks.md; MVP path is listed at the top of the file)
5. Add memory capabilities to JARVIS
6. Implement the positivity feature (its tasks.md starts with a voice spike, task 1)
7. Test sponsor challenge compliance
8. Prepare demo for Microsoft "What's Missing?" challenge

## KEY INTEGRATION POINTS
- MongoDB connection must not break existing ElevenLabs/Gemini integration
- Memory store should enhance, not replace, existing conversational AI
- Data privacy is critical for personalization features
- Fallback mechanisms needed for offline operation

## SPONSOR PRIORITY
1. MongoDB Atlas (new target - M5Stack IoT Kit)
2. Microsoft "What's Missing?" (strong real-world impact)
3. ElevenLabs (already qualified)
4. Gemini API (already qualified)
5. State Farm (potential pivot if time permits)



## NEW: MICROSOFT POSITIVITY FEATURE
Feature: positivity-encouragement-bot
Spec Type: Feature (Requirements-First workflow)
Requirements: Complete ✅
Design: Complete ✅ (.kiro/specs/positivity-encouragement-bot/design.md)
Tasks: Complete ✅ (tasks.md)
Requirements analysis: Complete ✅ (analysis.md; requirements.md not yet edited)

**Key Concept:** Flip 'roast bot' into 'compliment bot' that analyzes facial features and gives uplifting, confidence-building remarks.

**Microsoft Challenge Fit:** ✅ Perfect - Not a chatbot, robot has a job (analyze + encourage), shows real task completion (confidence building).

**Implementation Approaches:**
1. Pure AI (Gemini generates personalized compliments)
2. Hybrid (Community messages + AI enhancement)
3. Curated database (Positive affirmations mapped to features)

**Privacy Note:** No hacker identities released without consent. Focus on uplifting, culturally sensitive messages only.

**Chosen approach (design.md):** Hybrid. Gemini proposes a structured remark, a deterministic validator (allow-list, deny-lists, specificity) checks it, and a curated affirmation bank is the fallback. A short spoken notice plus opt-out (spoken "no thanks" or walking away) comes before anything face-derived leaves the device.

**Cross-spec decisions:**
- Positivity is stateless by default. It persists nothing unless a person consents through the MongoDB spec's voice-consent flow (`remember_me` / `forget_me`), and it consumes `IMemoryStore` / `PresenceState` rather than building its own store.
- Two privacy modes: `crop` (default; one small face-only crop to Gemini after the opt-out window) and `tags_only` (no image leaves the device). See positivity analysis.md for the conflict this resolves (R1.1 vs R6.1/R6.2).
- Known open item: the existing `look()` tool in jarvis.py sends a full frame to Gemini on the voice agent's request; this is outside the positivity feature.
- Both designs assume the thread-based, synchronous structure of jarvis.py (no asyncio; originally written against the old robot.py) and add only flag-gated, non-blocking hooks to camera_loop and the ElevenLabs callbacks.
