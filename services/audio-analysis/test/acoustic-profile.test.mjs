import assert from "node:assert/strict";
import test from "node:test";

import { analyzeAcousticOutline, detectDominantPitch } from "../src/acoustic-profile.mjs";

function sineWave(hz, seconds, sampleRate = 16_000) {
  const output = new Float32Array(Math.round(seconds * sampleRate));
  for (let index = 0; index < output.length; index += 1) {
    output[index] = Math.sin((2 * Math.PI * hz * index) / sampleRate) * 0.45;
  }
  return output;
}

test("detectDominantPitch finds a simple authorized PCM tone", () => {
  const result = detectDominantPitch(sineWave(440, 0.6), 16_000);
  assert.ok(result.hz);
  assert.ok(Math.abs(result.hz - 440) < 3, `expected ~440Hz, got ${result.hz}`);
  assert.ok(result.confidence > 0.8);
});

test("acoustic outline returns derived frames, never raw samples", () => {
  const result = analyzeAcousticOutline(sineWave(220, 1.2), 16_000);
  assert.equal(result.reference_pitch.kind, "derived_dominant_pitch");
  assert.equal(result.reference_pitch.scope, "full_mix_outline_not_vocal_stem");
  assert.ok(result.reference_pitch.frames.length >= 4);
  assert.ok(result.reference_pitch.frames.every((frame) => Math.abs(frame.hz - 220) < 3));
  assert.equal(JSON.stringify(result).includes("Float32Array"), false);
  assert.equal(Object.hasOwn(result, "samples"), false);
});
