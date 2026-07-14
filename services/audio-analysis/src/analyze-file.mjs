#!/usr/bin/env node

import path from "node:path";

import {
  DEFAULT_MAX_SECONDS,
  analyzeAuthorizedAudioFile,
  writeReferenceArtifact,
} from "./original-track.mjs";

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

function help() {
  console.log(`Usage:
  node src/analyze-file.mjs --input /authorized/song.mp3 --song-id demo-signal [--output ./data/reference-contours/demo-signal.json] [--max-seconds 720]

The input must be a local audio file you are authorized to analyze. The command
uses ffmpeg, writes only derived JSON, and never uploads or bundles the audio.`);
}

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  help();
  process.exit(0);
}

const input = argument("--input");
const songId = argument("--song-id");
if (!input || !songId) {
  help();
  process.exit(2);
}

const output = argument("--output") || path.join("data", "reference-contours", `${songId}.json`);
const maxSeconds = Math.max(1, Math.min(DEFAULT_MAX_SECONDS, Number(argument("--max-seconds")) || DEFAULT_MAX_SECONDS));

try {
  const analysis = await analyzeAuthorizedAudioFile(input, { songId, maxSeconds });
  const destination = await writeReferenceArtifact(output, analysis);
  console.log(JSON.stringify({
    output: destination,
    song_id: analysis.song_id,
    duration_ms: analysis.duration_ms,
    frame_count: analysis.frame_count,
    reference_kind: analysis.reference_kind,
  }));
} catch (error) {
  console.error(error instanceof Error ? error.message : "analysis failed");
  process.exit(1);
}
