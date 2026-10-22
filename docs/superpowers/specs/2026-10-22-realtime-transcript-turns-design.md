# Realtime call transcript turn grouping

## Problem

The Qwen realtime provider emits `response.audio_transcript.delta` for small subtitle fragments and `response.audio_transcript.done` for the complete subtitle. `run_realtime_call` currently stores every event containing `transcript` as a separate call-log turn, and the admin view renders each stored turn as its own card. A single Agent utterance therefore appears as many one- or two-character records and may also duplicate the final text.

## Decision

One Agent response is one displayed record, even if it contains several punctuated sentences. Keep user utterances separate. This is a call-history change only; do not change audio playback or interruption.

For new realtime calls, maintain an in-memory transcript turn per provider `response_id` (falling back to `item_id`, then the active response). Append deltas without stripping meaningful whitespace. On `response.audio_transcript.done`, replace the assembled text with the authoritative complete subtitle. Update the existing record in place, preserving its original position and first-fragment timestamp. For user speech, store only the completed transcription. On interruption or disconnect, an unfinished Agent turn retains the accumulated partial text. Never append both the deltas and the final subtitle as separate records.

For existing call logs, preserve stored JSON and combine adjacent short same-speaker fragments for display only. A short time gap marks a likely streaming fragment sequence; a completed subtitle matching multiple accumulated fragments replaces them rather than duplicating text. This is a best-effort presentation fallback because old JSON lacks provider response IDs and event types: separate rapid short responses can be joined, and a single delta followed by a short final subtitle can still repeat text. Prefer preserving text over silently deleting an ambiguous repeated fragment. Already-normalized long turns and alternating speakers stay distinct.

## Verification

Add Worker regression tests for delta + done, partial/interrupted output, user completion, and distinct response IDs. Add admin utility tests for legacy grouping, duplicate-final suppression, and unchanged normalized/alternating turns. Run the relevant Python and Node tests and the admin build. No production deployment is in scope for this request.
