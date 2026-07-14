# Sing Along Companion

A privacy-first reference implementation for three connected music features:

- local microphone pitch tracing for a sing-along;
- a compact, non-scoring comparison against an optional reference contour;
- a bridge that lets the listening room contribute bounded lyric and playback
  context to an existing main chat timeline.

It is intentionally provider-neutral. This repository contains no music
catalog, account cookies, recordings, lyrics, user profiles, keys, screenshots,
or chat history. The included browser demo uses synthetic data only.

## What is included

```text
apps/web                 React demo: room, local F0 graph, and chat timeline
services/api             FastAPI: room state, lyric context, pitch hand-off
services/audio-analysis  Dependency-free Node acoustic-outline helpers
docs                     Architecture and privacy boundaries
```

The web app has two deliberately different modes:

| Mode | What leaves the microphone | Retention |
| --- | --- | --- |
| Local pitch view | Nothing | Browser memory only |
| Share pitch trace | Sparse F0 points only; no audio or transcript | Short in-memory receipt window |

The separate `Chat voice upload` feature from the original private product is
not part of this repository. If you add audio upload later, treat it as a new
consent and privacy surface rather than silently reusing the pitch-share flow.

## Run locally

Requirements: Python 3.10+, Node 20+, and npm.

```bash
python3 -m venv .venv
.venv/bin/pip install -r services/api/requirements.txt
.venv/bin/uvicorn app.main:app --app-dir services/api --reload --port 8000
```

In a second terminal:

```bash
cd apps/web
npm install
npm run dev
```

Open the URL printed by Vite. The API serves a synthetic song, synthetic timed
lines, and a synthetic reference contour so that no external music provider is
required.

## Main-chat integration

The API exposes a small integration seam instead of embedding a specific LLM
or persona:

- `POST /api/chat/messages` conditionally adds a bounded listening snapshot;
- finishing a pitch-share writes a hidden receipt input and a visible assistant
  reply to the same conversation timeline;
- `DemoConversationGateway` is deterministic and exists only to make the data
  flow runnable. Replace it with your own authenticated conversation adapter.

`docs/ARCHITECTURE.md` describes the contract and the trust boundaries.

## Audio and music integrations

`services/audio-analysis` accepts locally authorized PCM and returns only a
derived contour/profile. It does not ship a catalog connector, streaming
credentials, copyrighted audio, or lyric data.

Before connecting any music service, verify its terms and content rights. Do
not commit provider cookies, stream URLs, lyric caches, recordings, or derived
data tied to an account.

## Test

```bash
.venv/bin/python -m pytest services/api/tests
cd services/audio-analysis && npm test
cd apps/web && npm run build
```

## License

MIT. See [LICENSE](LICENSE).
