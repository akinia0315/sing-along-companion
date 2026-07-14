import assert from "node:assert/strict";
import test from "node:test";

import { analyzePcm, decodeAuthorizedAudioFile } from "../src/original-track.mjs";

function sineWave(hz, seconds, sampleRate = 8_000) {
  const output = new Float32Array(Math.round(seconds * sampleRate));
  for (let index = 0; index < output.length; index += 1) {
    output[index] = Math.sin((2 * Math.PI * hz * index) / sampleRate) * 0.45;
  }
  return output;
}

test("authorized PCM becomes a bounded full-mix reference artifact", () => {
  const analysis = analyzePcm(sineWave(330, 2.2), { songId: "legal-demo" });
  assert.equal(analysis.song_id, "legal-demo");
  assert.equal(analysis.reference_kind, "full_mix_dominant_pitch");
  assert.equal(analysis.source, "authorized_local_audio_full_mix");
  assert.ok(analysis.frames.length >= 6);
  assert.ok(analysis.frames.every((frame) => Math.abs(frame.hz - 330) < 4));
  assert.equal("samples" in analysis, false);
  assert.equal(analysis.profile.scope, "derived_outline_not_vocal_stem");
});

test("file decoder refuses URL input so it cannot become a provider fetcher", async () => {
  await assert.rejects(
    decodeAuthorizedAudioFile("https://example.invalid/track.mp3"),
    /authorized local file/,
  );
});
