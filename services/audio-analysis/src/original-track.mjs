/**
 * Build a shareable reference contour from an audio file the operator is
 * authorized to analyze. This module has no catalog, HTTP client, account
 * support, or persistence of the input track.
 */

import { spawn } from "node:child_process";
import { mkdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";

import { analyzeAcousticOutline } from "./acoustic-profile.mjs";

export const REFERENCE_ANALYSIS_VERSION = 1;
export const DEFAULT_SAMPLE_RATE = 8_000;
export const DEFAULT_MAX_SECONDS = 12 * 60;
const MAX_FRAMES = 4_000;
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

function safeSongId(value) {
  const result = String(value || "").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 64);
  if (!result) throw new Error("songId must contain letters, numbers, _ or -");
  return result;
}

function quantile(values, ratio) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.round((sorted.length - 1) * ratio)];
}

function noteForHz(hz) {
  if (!Number.isFinite(hz) || hz <= 0) return "";
  const midi = Math.round(69 + 12 * Math.log2(hz / 440));
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

function toFloat32Array(input) {
  if (input instanceof Float32Array) return input;
  if (ArrayBuffer.isView(input)) {
    return new Float32Array(input.buffer, input.byteOffset, Math.floor(input.byteLength / 4));
  }
  if (input instanceof ArrayBuffer) return new Float32Array(input);
  if (Array.isArray(input)) return Float32Array.from(input);
  throw new TypeError("PCM must be Float32 samples, an ArrayBuffer, or an array of numbers");
}

/**
 * Convert decoded full-mix PCM into a compact reference artifact.
 *
 * The resulting `frames` are a dominant full-mix contour. They are useful for
 * aligning sung movement, but must not be described as isolated vocal notes.
 */
export function analyzePcm(input, { songId, sampleRate = DEFAULT_SAMPLE_RATE } = {}) {
  const samples = toFloat32Array(input);
  if (!Number.isFinite(sampleRate) || sampleRate < 1_000 || sampleRate > 192_000) {
    throw new RangeError("sampleRate must be between 1000 and 192000");
  }
  const id = safeSongId(songId);
  const outline = analyzeAcousticOutline(samples, sampleRate, {
    minHz: 82,
    maxHz: 920,
    minRms: 0.009,
    windowMs: 320,
    hopMs: 240,
  });
  const frames = outline.reference_pitch.frames.slice(0, MAX_FRAMES);
  const values = frames.map((frame) => frame.hz);
  const lowHz = quantile(values, 0.1);
  const highHz = quantile(values, 0.9);
  const durationMs = outline.duration_ms;
  const attemptedFrames = Math.max(1, Math.floor((samples.length / sampleRate) * (1_000 / 240)));
  return {
    analysis_version: REFERENCE_ANALYSIS_VERSION,
    song_id: id,
    source: "authorized_local_audio_full_mix",
    reference_kind: "full_mix_dominant_pitch",
    duration_ms: durationMs,
    sample_rate: sampleRate,
    frame_count: frames.length,
    voiced_ratio: Math.round((frames.length / attemptedFrames) * 1_000) / 1_000,
    low_hz: lowHz === null ? null : Math.round(lowHz * 10) / 10,
    high_hz: highHz === null ? null : Math.round(highHz * 10) / 10,
    low_note: lowHz === null ? "" : noteForHz(lowHz),
    high_note: highHz === null ? "" : noteForHz(highHz),
    frames,
    profile: {
      ...outline.acoustic_outline,
      source: "authorized_local_audio_full_mix",
      reference_kind: "full_mix_dominant_pitch",
      scope: "derived_outline_not_vocal_stem",
    },
  };
}

/** Decode one authorized local file with ffmpeg. Source bytes never hit disk. */
export async function decodeAuthorizedAudioFile(inputPath, {
  sampleRate = DEFAULT_SAMPLE_RATE,
  maxSeconds = DEFAULT_MAX_SECONDS,
} = {}) {
  const input = String(inputPath || "").trim();
  if (!input) throw new Error("inputPath is required");
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(input)) {
    throw new Error("inputPath must be an authorized local file, not a URL");
  }
  const safeSeconds = Math.max(1, Math.min(DEFAULT_MAX_SECONDS, Number(maxSeconds) || DEFAULT_MAX_SECONDS));
  const maxBytes = Math.floor(safeSeconds * sampleRate * 4);
  return new Promise((resolve, reject) => {
    const child = spawn("ffmpeg", [
      "-nostdin", "-v", "error", "-i", input,
      "-t", String(safeSeconds), "-vn", "-ac", "1", "-ar", String(sampleRate),
      "-f", "f32le", "pipe:1",
    ], { stdio: ["ignore", "pipe", "pipe"] });
    const chunks = [];
    let byteLength = 0;
    let stderr = "";
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      callback(value);
    };
    child.stdout.on("data", (chunk) => {
      byteLength += chunk.length;
      if (byteLength > maxBytes) {
        child.kill("SIGKILL");
        finish(reject, new Error("decoded audio exceeds the analysis limit"));
        return;
      }
      chunks.push(chunk);
    });
    child.stderr.on("data", (chunk) => { stderr = `${stderr}${String(chunk)}`.slice(0, 600); });
    child.once("error", () => finish(reject, new Error("ffmpeg is unavailable")));
    child.once("close", (code) => {
      if (code !== 0) {
        finish(reject, new Error(stderr ? "ffmpeg could not decode the input" : "audio decoding failed"));
        return;
      }
      const packed = Buffer.concat(chunks, byteLength - (byteLength % 4));
      if (packed.length < sampleRate * 4) {
        finish(reject, new Error("audio is too short to analyze"));
        return;
      }
      const samples = new Float32Array(packed.length / 4);
      for (let offset = 0, index = 0; offset < packed.length; offset += 4, index += 1) {
        samples[index] = packed.readFloatLE(offset);
      }
      finish(resolve, samples);
    });
  });
}

export async function analyzeAuthorizedAudioFile(inputPath, options = {}) {
  const samples = await decodeAuthorizedAudioFile(inputPath, options);
  return analyzePcm(samples, options);
}

/** Persist only the derived JSON artifact, atomically and owner-readable. */
export async function writeReferenceArtifact(outputPath, analysis) {
  const destination = path.resolve(String(outputPath || ""));
  if (!destination.endsWith(".json")) throw new Error("outputPath must end in .json");
  await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
  const temporary = `${destination}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(analysis)}\n`, { encoding: "utf8", mode: 0o600 });
  await rename(temporary, destination);
  return destination;
}
