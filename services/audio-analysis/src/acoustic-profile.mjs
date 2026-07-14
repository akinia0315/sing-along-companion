/**
 * Provider-neutral acoustic analysis for already-authorized PCM samples.
 *
 * This package intentionally accepts decoded samples rather than URLs, account
 * cookies, or provider clients. Callers decide how they obtain audio and should
 * discard it after deriving the returned compact result.
 */

const DEFAULT_MIN_HZ = 65;
const DEFAULT_MAX_HZ = 900;
const DEFAULT_MIN_RMS = 0.008;

function asSamples(input) {
  if (input instanceof Float32Array) return input;
  if (Array.isArray(input)) return Float32Array.from(input);
  throw new TypeError("samples must be a Float32Array or an array of numbers");
}

function clamp(value, lower, upper) {
  return Math.min(upper, Math.max(lower, value));
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.floor(sorted.length / 2)];
}

function mean(values) {
  return values.length ? values.reduce((total, value) => total + value, 0) / values.length : 0;
}

function semitone(hz) {
  return 69 + 12 * Math.log2(hz / 440);
}

export function rootMeanSquare(input) {
  const samples = asSamples(input);
  if (!samples.length) return 0;
  let total = 0;
  for (const value of samples) total += value * value;
  return Math.sqrt(total / samples.length);
}

export function zeroCrossingRate(input) {
  const samples = asSamples(input);
  if (samples.length < 2) return 0;
  let crossings = 0;
  for (let index = 1; index < samples.length; index += 1) {
    if ((samples[index - 1] >= 0) !== (samples[index] >= 0)) crossings += 1;
  }
  return crossings / (samples.length - 1);
}

/**
 * Estimate one dominant F0 using normalized autocorrelation.
 *
 * The output is intentionally modest: it is useful for a reference contour,
 * but it is not vocal separation, musical transcription, or a pitch score.
 */
export function detectDominantPitch(input, sampleRate, options = {}) {
  const samples = asSamples(input);
  const minHz = Number(options.minHz ?? DEFAULT_MIN_HZ);
  const maxHz = Number(options.maxHz ?? DEFAULT_MAX_HZ);
  const minimumRms = Number(options.minRms ?? DEFAULT_MIN_RMS);
  if (!Number.isFinite(sampleRate) || sampleRate <= 0 || minHz <= 0 || maxHz <= minHz) {
    throw new RangeError("sampleRate and pitch range must be valid");
  }
  if (samples.length < Math.ceil(sampleRate / minHz) * 2 || rootMeanSquare(samples) < minimumRms) {
    return { hz: null, confidence: 0 };
  }

  const minLag = Math.max(1, Math.floor(sampleRate / maxHz));
  const maxLag = Math.min(Math.floor(sampleRate / minHz), samples.length - 2);
  let bestLag = 0;
  let bestCorrelation = -1;
  const correlations = new Map();

  for (let lag = minLag; lag <= maxLag; lag += 1) {
    let product = 0;
    let leftEnergy = 0;
    let rightEnergy = 0;
    for (let index = 0; index + lag < samples.length; index += 1) {
      const left = samples[index];
      const right = samples[index + lag];
      product += left * right;
      leftEnergy += left * left;
      rightEnergy += right * right;
    }
    const denominator = Math.sqrt(leftEnergy * rightEnergy);
    const correlation = denominator > 0 ? product / denominator : 0;
    correlations.set(lag, correlation);
    if (correlation > bestCorrelation) {
      bestCorrelation = correlation;
      bestLag = lag;
    }
  }

  if (!bestLag || bestCorrelation < 0.45) return { hz: null, confidence: 0 };
  // Periodic signals also correlate at 2×, 3×, … their period. Prefer the
  // earliest local peak that is effectively as strong as the best one, which
  // makes a simple tone resolve to its fundamental instead of a sub-harmonic.
  const nearBest = [];
  for (let lag = minLag + 1; lag < maxLag; lag += 1) {
    const current = correlations.get(lag) ?? -1;
    if (
      current >= bestCorrelation - 0.03
      && current >= (correlations.get(lag - 1) ?? -1)
      && current >= (correlations.get(lag + 1) ?? -1)
    ) {
      nearBest.push(lag);
    }
  }
  if (nearBest.length) bestLag = nearBest[0];
  const before = correlations.get(bestLag - 1) ?? bestCorrelation;
  const center = correlations.get(bestLag) ?? bestCorrelation;
  const after = correlations.get(bestLag + 1) ?? bestCorrelation;
  const curvature = before - 2 * center + after;
  const offset = Math.abs(curvature) > 1e-9 ? clamp(0.5 * (before - after) / curvature, -0.5, 0.5) : 0;
  const hz = sampleRate / (bestLag + offset);
  return {
    hz: Number.isFinite(hz) && hz >= minHz && hz <= maxHz ? hz : null,
    confidence: clamp(bestCorrelation, 0, 1),
  };
}

function movementLabel(values) {
  if (values.length < 3) return "unknown";
  const third = Math.max(1, Math.floor(values.length / 3));
  const start = median(values.slice(0, third));
  const end = median(values.slice(-third));
  if (start === null || end === null) return "unknown";
  if (end - start > 1.2) return "rising";
  if (start - end > 1.2) return "falling";
  return "steady";
}

function positionLabel(values) {
  if (!values.length) return "unknown";
  const max = Math.max(...values);
  const index = values.indexOf(max) / Math.max(1, values.length - 1);
  if (index < 0.34) return "opening";
  if (index > 0.66) return "closing";
  return "middle";
}

function timbreLabel(zcr) {
  if (zcr < 0.045) return "smooth";
  if (zcr > 0.16) return "bright_or_noisy";
  return "balanced";
}

function energySegments(frames, durationMs, segmentCount = 8) {
  const safeCount = Math.max(1, Math.min(segmentCount, 16));
  const maxEnergy = Math.max(1e-9, ...frames.map((frame) => frame.rms));
  return Array.from({ length: safeCount }, (_, index) => {
    const startMs = Math.round((durationMs * index) / safeCount);
    const endMs = Math.round((durationMs * (index + 1)) / safeCount);
    const inSegment = frames.filter((frame) => frame.t_ms >= startMs && frame.t_ms < endMs);
    const level = Math.round(clamp((mean(inSegment.map((frame) => frame.rms)) / maxEnergy) * 100, 0, 100));
    return { start_ms: startMs, end_ms: endMs, level };
  });
}

/**
 * Derive compact pitch frames and a generic acoustic outline from PCM.
 * No input samples are copied into the returned object.
 */
export function analyzeAcousticOutline(input, sampleRate, options = {}) {
  const samples = asSamples(input);
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) throw new RangeError("sampleRate must be positive");
  const windowMs = clamp(Number(options.windowMs ?? 360), 80, 2_000);
  const hopMs = clamp(Number(options.hopMs ?? 160), 50, windowMs);
  const frameSize = Math.max(32, Math.round((sampleRate * windowMs) / 1_000));
  const hopSize = Math.max(1, Math.round((sampleRate * hopMs) / 1_000));
  const durationMs = Math.round((samples.length / sampleRate) * 1_000);
  const frames = [];

  for (let start = 0; start < samples.length; start += hopSize) {
    const end = Math.min(samples.length, start + frameSize);
    const chunk = samples.slice(start, end);
    if (chunk.length < Math.min(frameSize, Math.round(sampleRate * 0.09))) break;
    const pitch = detectDominantPitch(chunk, sampleRate, options);
    frames.push({
      t_ms: Math.round(((start + chunk.length / 2) / sampleRate) * 1_000),
      rms: rootMeanSquare(chunk),
      zcr: zeroCrossingRate(chunk),
      hz: pitch.hz,
      confidence: pitch.confidence,
    });
  }

  const voiced = frames.filter((frame) => frame.hz !== null && frame.confidence >= 0.45);
  const midi = voiced.map((frame) => semitone(frame.hz));
  const energies = frames.map((frame) => frame.rms);
  const energyMovement = movementLabel(energies.map((value) => value * 100));
  const pitchRange = midi.length > 1 ? Math.max(...midi) - Math.min(...midi) : 0;
  const profile = {
    source: "authorized_pcm",
    energy: {
      segments: energySegments(frames, durationMs),
      start: energies.length ? (energies[0] < mean(energies) ? "low" : "medium") : "unknown",
      end: energies.length ? (energies.at(-1) < mean(energies) ? "low" : "medium") : "unknown",
      peak: positionLabel(energies),
      movement: energyMovement,
      dynamics: Math.max(...energies, 0) - Math.min(...energies, 0) > 0.05 ? "wide" : "moderate",
    },
    motion: { label: movementLabel(midi) },
    timbre: { label: timbreLabel(mean(frames.map((frame) => frame.zcr))) },
    melody: {
      presence: voiced.length >= 3 ? "present" : "limited",
      range_semitones: Math.round(pitchRange * 10) / 10,
      movement: movementLabel(midi),
      peak: positionLabel(midi),
    },
  };

  return {
    version: "0.1",
    duration_ms: durationMs,
    reference_pitch: {
      kind: "derived_dominant_pitch",
      scope: "full_mix_outline_not_vocal_stem",
      frames: voiced.map((frame) => ({
        t_ms: frame.t_ms,
        hz: Math.round(frame.hz * 10) / 10,
        confidence: Math.round(frame.confidence * 100) / 100,
      })),
    },
    acoustic_outline: profile,
  };
}
