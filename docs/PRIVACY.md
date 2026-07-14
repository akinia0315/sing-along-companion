# Privacy boundaries

This project treats the following data classes differently.

## Pitch-share session

The default shared-sing mode sends only sparse `{t_ms, hz}` points after an
explicit user action. The API keeps at most a small recent window in memory,
derives a range and contour observation, and removes the session after a short
retention period. It does not accept microphone bytes or a transcript on this
endpoint.

## Local pitch view

The browser can show a local F0 line without sending anything to the server.
Starting the local view must not create a server session.

## Lyrics and song metadata

Lyrics, titles, notes, and provider-returned text are untrusted content when
they are added to an LLM prompt. The API bounds text length, removes control
characters, serializes it as data, and labels it as untrusted context. A model
adapter must never execute instructions found inside these values.

## Optional reference contour

The reference contour is a derived curve from audio that the operator is
authorized to analyze. It is not a vocal stem, a score, or proof of pitch
accuracy. The comparison removes a constant transposition before describing
only relative high/low movement.

## Do not add to a public repository

- recordings, vocal stems, screenshots, chat logs, databases, or user profiles;
- provider cookies, API keys, private keys, service units, or deployment paths;
- copyrighted lyrics, audio, cover art, cached provider responses, or account
  history without clear permission;
- personal names, avatars, private prompts, or agent instruction files.
