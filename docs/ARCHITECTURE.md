# Architecture

```text
Browser microphone
  │
  ├─ local mode ───────────────→ local autocorrelation F0 graph
  │
  └─ explicit share ───────────→ POST sparse F0 batches
                                      │
                                      ▼
                         short-lived SingingSession
                                      │
                        optional same-timeline contour
                                      │
                                      ▼
                         hidden receipt → conversation gateway
                                      │
                                      ▼
                         visible reply in main chat timeline
```

```text
Authorized local audio file
  │
  ├─ ffmpeg decode (transient process memory; no source-file upload)
  ▼
Original-track analyzer
  │
  ├─ sparse full-mix dominant-F0 frames
  └─ compact acoustic outline
  ▼
ignored local reference JSON ──→ ReferenceContourRepository ──→ same-timeline comparison
```

The original-track analyzer is deliberately a local CLI, not an HTTP endpoint.
It has no music catalog, account integration, or URL fetcher. The reference is
a dominant contour from a complete mix, therefore comparison is limited to
aligned movement and an optional neutral key offset — never a vocal-stem or
pitch-accuracy score.

## Room context injection

`ListeningContextBuilder` reads the current room snapshot and returns only the
fields requested for a turn: playback state, active/next timed line, a compact
acoustic outline, and recent room notes. `ConversationService` decides whether
a user message actually asks about listening; a completed pitch receipt always
requests the full bounded snapshot.

The context is serialized as JSON inside an explicitly untrusted data block.
This is an integration contract, not a substitute for prompt-injection defenses
in a model provider.

## Replaceable adapters

- `ReferenceContourRepository`: loads derived reference frames for a song.
- `ConversationGateway`: sends a regular main-timeline turn to your chat
  system. The demo implementation never calls a network model.
- Audio analysis is a separate package so a music provider never needs to live
  in the browser or the chat service.
