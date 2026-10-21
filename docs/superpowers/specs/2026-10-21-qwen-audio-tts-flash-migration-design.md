# Qwen Audio 3.1 TTS Flash Migration Design

## Goal

Replace the classic Qwen TTS runtime with `qwen-audio-3.1-tts-flash`, restore admin audition, and recreate the existing LS and NN cloned voices for the new model without losing the old provider voice IDs before the migration succeeds.

## Current State

- The production `tts_configs.model` is still `qwen3-tts-vc-realtime-2026-01-15`; the provider has retired it and returns `Model not exist`.
- The configuration display name is still `qwen3-tts-vc-realtime`.
- LS and NN reference legacy `qwen-tts-vc-*` voice IDs. Those IDs are model-specific; querying them returns `ResourceNotExist`, so they cannot be reused with any current model.
- The generic Qwen HTTP strategy calls the multimodal generation endpoint with the legacy request shape.
- The new model requires the workspace-scoped `SpeechSynthesizer` endpoint and returns a temporary audio URL for non-streaming synthesis.

## Design

### TTS strategy selection

Add a dedicated Qwen Audio TTS strategy selected for model IDs beginning with `qwen-audio-` and containing `-tts-`. Existing Qwen realtime, CosyVoice, Volcengine, and generic HTTP behavior remains unchanged.

The dedicated strategy will:

1. Resolve the API key through the existing `resolved_key` fallback.
2. Resolve the HTTP endpoint from `QWEN_AUDIO_TTS_API_URL` when set, otherwise assemble the Beijing workspace-scoped endpoint from `DASHSCOPE_WORKSPACE`. Deployment will set both values explicitly from the existing production workspace endpoint rather than guessing a workspace ID.
3. POST to `/api/v1/services/audio/tts/SpeechSynthesizer` with `model` and `input: {text, voice, format: "wav", sample_rate: 24000}`. The provider rejects flat top-level `text`/`voice` fields with `Please ensure input text is valid`.
4. Accept inline audio data when present, or download the provider's temporary audio URL with the same bounded timeout.
5. Return WAV bytes as base64 to the existing audition API.
6. Surface the provider request ID, error code, and message while redacting credentials.

Missing workspace configuration will produce a clear configuration error instead of sending a request to an incompatible legacy endpoint.

### Voice recreation and migration

Use the original recording for each voice to create new voices with `target_model=qwen-audio-3.1-tts-flash`. Enrollment resolves the credential from the selected TTS configuration's linked API key, falling back to the bootstrap `DASHSCOPE_API_KEY` only when the configuration has no key; a stale bootstrap key must not block re-cloning. A newly returned voice ID must begin with the new model family and must pass a short synthesis check before it replaces any database binding. The local machine currently has one candidate recording, `/Users/zhangfuzhen/Desktop/Audio 2026-01-30 16.56.54.m4a`; it will not be assigned to LS or NN until its identity is confirmed. A voice without a confirmed source recording remains unchanged.

For each voice:

1. Create the new provider voice.
2. Synthesize a short validation phrase through the new strategy.
3. In one database transaction, update the classic TTS binding and the voice pool's classic provider voice ID.
4. Keep the previous provider voice ID in the deployment notes until both production auditions pass; do not delete the old provider voice during this change.

The realtime binding is not rewritten because it belongs to a separate realtime configuration and runtime path.

### Configuration naming

After the functional migration succeeds, rename the TTS configuration display name to `qwen-audio-3.1-tts-flash` so the admin UI no longer shows the old model family. The model ID remains the source of runtime strategy selection.

### Error handling

- Provider HTTP errors include status, provider code, message, and request ID.
- Missing or malformed audio URL responses fail explicitly.
- Audio downloads reject non-audio error responses and apply size and time bounds.
- Failed cloning or failed validation leaves the existing database bindings untouched.

## Testing

Automated tests will be written before implementation and cover:

- strategy selection for `qwen-audio-3.1-tts-flash`;
- correct workspace endpoint and request body;
- temporary audio URL download and base64 response;
- inline audio fallback;
- provider error propagation;
- missing workspace configuration;
- preservation of existing Qwen realtime behavior.

Production verification will then cover:

1. API health and container status;
2. LS admin audition;
3. NN admin audition;
4. one pipeline Agent call using the migrated TTS model;
5. confirmation that failed calls do not alter stored voice bindings.

## Deployment and Rollback

Commit and push code first, then deploy the API container independently to avoid unnecessary memory pressure. Recreate voices only after the new API is healthy. Database changes will be backed up before voice migration.

Rollback consists of restoring the database backup or restoring the saved legacy provider voice IDs and previous TTS model, followed by redeploying the prior API revision. Old provider voices will not be deleted during this migration.

## Out of Scope

- Replacing the end-to-end realtime model.
- Redesigning the admin UI.
- Deleting legacy provider voices.
- Changing Agent runtime selection semantics.
