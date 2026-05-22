# call_me Design Spec

## Overview

A voice AI calling app with voice cloning. Users speak to an AI assistant that responds with a cloned voice. Real phone numbers (SIP) can be bound so external callers reach the AI.

**End state of this spec cycle:** a working MVP deployable via `docker compose up -d` on a single server, with a Flutter mobile app for iOS and Android.

## Goals

- **Deploy with one command** — Docker Compose pulls up everything
- **Use with no friction** — open the Flutter app, tap call, talk
- **Voice cloning** — user uploads a short audio clip, AI responds in that voice
- **SIP binding** — bind a real phone number so external callers reach the AI

## Non-goals (MVP)

- User accounts / login / registration
- Contact lists and call history
- Multi-user concurrent calls
- Push notifications

## Architecture

Two-service design, orchestrated by Docker Compose. No shared state between services — the api generates tokens, the agent registers with LiveKit Cloud and is dispatched to rooms automatically.

```
  ┌──────────────┐          ┌──────────────┐
  │  api (FastAPI)│          │ agent (Worker)│
  │              │          │              │
  │ - voice enroll│         │ - STT+LLM+TTS │
  │ - token gen  │          │ - voice AI    │
  │ - SIP mgmt   │          │   pipeline    │
  └──────┬───────┘          └──────┬───────┘
         │                         │
         ▼                         ▼
   DashScope API             LiveKit Cloud
   (Voice Enrollment)        (WebRTC / SIP / Agent Dispatch)
```

- **api** — FastAPI, handles voice enrollment (uploads audio to DashScope), generates LiveKit access tokens, manages SIP trunk bindings. Stateless.
- **agent** — LiveKit Agent Worker, runs the voice AI pipeline (STT → LLM → TTS). Registers with LiveKit Cloud on startup; LiveKit dispatches it to rooms when calls come in. Uses user's cloned voice_id for TTS.

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Mobile app | Flutter | Single codebase for iOS + Android; LiveKit has Flutter components |
| Backend API | Python / FastAPI | Same ecosystem as agent-starter-python; reuse DashScope integration |
| Agent | Python / livekit-agents | Proven pipeline from reference project |
| Deployment | Docker Compose | One-command deploy on any Linux server |
| External | LiveKit Cloud + DashScope | No self-hosted WebRTC or GPU infra needed |

## Flutter App Screens

### Screen 1: Home

- App logo / branding
- Current voice name display
- "Start Call" button (large, primary action)
- Sub-buttons: "Voice Management", "Settings"
- First-launch: prompts user to record/enroll a voice sample

### Screen 2: Call

- Minimal UI: waveform animation while AI speaks
- Call duration timer
- Hangup button (red, prominent)
- Mute toggle

### Screen 3: Voice Management

- List of enrolled voices
- "Add new voice" — pick audio file from device, upload to API
- Set default voice
- Delete voice

### Screen 4: Settings / SIP

- Phone number input for SIP binding
- Bind / unbind button
- Display current SIP trunk status
- Server URL configuration

## API Endpoints

All endpoints are unauthenticated. The device identifies itself via a device_id (UUID generated on first launch).

```
POST  /api/voice/enroll      multipart/form-data {audio_file} → {voice_id, voice_name}
GET   /api/voice/list        ?device_id=xxx → [{voice_id, voice_name, created_at}]
DELETE /api/voice/{id}       ?device_id=xxx → 204

POST  /api/call/token        {device_id, voice_id} → {token, room_url}

POST  /api/sip/bind          {device_id, phone_number} → {trunk_id, status}
GET   /api/sip/status        ?device_id=xxx → {bound_number, trunk_id, status}
```

## Voice Cloning Flow

1. User selects audio file in Flutter app (wav/mp3/m4a, 30s–5min)
2. App uploads to `POST /api/voice/enroll`
3. API forwards to DashScope `qwen-voice-enrollment` endpoint
4. DashScope returns a `voice_id` string
5. API returns `voice_id` to app
6. App stores `voice_id` in local SharedPreferences
7. During calls, app sends `voice_id` to `POST /api/call/token`, agent uses it for TTS

## Call Flow

1. User taps "Start Call" in Flutter app
2. App calls `POST /api/call/token` with `device_id` and `voice_id`
3. API generates a LiveKit access token with room join grant
4. App connects to LiveKit room using the token
5. LiveKit Cloud dispatches the agent worker to the room
6. Agent receives the call, configured with user's cloned voice for TTS
7. STT → LLM → TTS pipeline runs for the conversation
8. User hangs up → app disconnects from room → agent session ends

## SIP Flow

1. User enters phone number in Settings
2. App calls `POST /api/sip/bind`
3. API calls LiveKit Cloud SIP API to create/update a SIP trunk
4. LiveKit routes inbound calls from that number to the agent
5. External caller → SIP → LiveKit → agent answers with cloned voice

## Data Storage

- **Flutter app (SharedPreferences):** voice_id, voice_name, device_id (auto-generated UUID), server_url
- **Backend:** stateless, no persistence needed for MVP. Voice enrollment returns voice_id to app immediately; no server-side storage required.

## Deployment

Single `docker-compose.yml` with two services:

```yaml
services:
  api:
    build: ./api
    ports: ["8000:8000"]
    env_file: .env

  agent:
    build: ./agent
    env_file: .env
```

User provides a `.env` file with:

```
DASHSCOPE_API_KEY=sk-xxx
LIVEKIT_URL=wss://xxx.livekit.cloud
LIVEKIT_API_KEY=APIxxx
LIVEKIT_API_SECRET=xxx
QWEN_TTS_MODEL=qwen3-tts-vc-realtime-2026-01-15
```

Then `docker compose up -d` and it's running.

## Project Structure

```
call_me/
├── api/                    # FastAPI backend
│   ├── Dockerfile
│   ├── main.py            # App entrypoint, route registration
│   ├── voice.py           # Voice enrollment endpoints
│   ├── call.py            # Token generation, call management
│   ├── sip.py             # SIP binding endpoints
│   └── requirements.txt
├── agent/                  # LiveKit Agent Worker
│   ├── Dockerfile
│   ├── agent.py           # Voice AI pipeline (STT + LLM + TTS)
│   ├── qwen_tts.py        # Qwen TTS adapter (from reference project)
│   ├── qwen_asr.py        # Qwen ASR adapter (from reference project)
│   └── requirements.txt
├── app/                    # Flutter mobile app
│   └── (flutter project)
├── docker-compose.yml
├── .env.example
└── docs/
    └── superpowers/specs/2026-05-22-call-me-design.md
```
