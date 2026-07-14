const MIN_HZ = 65;
const MAX_HZ = 900;

export function rms(buffer) {
  if (!buffer?.length) return 0;
  let total = 0;
  for (const value of buffer) total += value * value;
  return Math.sqrt(total / buffer.length);
}

/** A small browser-only F0 estimator based on normalized autocorrelation. */
export function detectPitch(buffer, sampleRate) {
  if (!buffer?.length || !sampleRate || rms(buffer) < 0.012) return { hz: null, confidence: 0 };
  const minLag = Math.max(1, Math.floor(sampleRate / MAX_HZ));
  const maxLag = Math.min(Math.floor(sampleRate / MIN_HZ), buffer.length - 2);
  let bestLag = 0;
  let bestCorrelation = -1;
  const correlations = new Map();

  for (let lag = minLag; lag <= maxLag; lag += 1) {
    let product = 0;
    let firstEnergy = 0;
    let shiftedEnergy = 0;
    for (let index = 0; index + lag < buffer.length; index += 1) {
      const first = buffer[index];
      const shifted = buffer[index + lag];
      product += first * shifted;
      firstEnergy += first * first;
      shiftedEnergy += shifted * shifted;
    }
    const divisor = Math.sqrt(firstEnergy * shiftedEnergy);
    const correlation = divisor ? product / divisor : 0;
    correlations.set(lag, correlation);
    if (correlation > bestCorrelation) {
      bestCorrelation = correlation;
      bestLag = lag;
    }
  }

  if (!bestLag || bestCorrelation < 0.52) return { hz: null, confidence: 0 };
  // Avoid selecting a later multiple of the fundamental period.
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
  const offset = Math.abs(curvature) > 1e-9 ? Math.max(-0.5, Math.min(0.5, 0.5 * (before - after) / curvature)) : 0;
  const hz = sampleRate / (bestLag + offset);
  if (!Number.isFinite(hz) || hz < MIN_HZ || hz > MAX_HZ) return { hz: null, confidence: 0 };
  return { hz, confidence: Math.max(0, Math.min(1, bestCorrelation)) };
}

export function noteForHz(hz) {
  if (!hz || hz <= 0) return "—";
  const names = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
  const midi = Math.round(69 + 12 * Math.log2(hz / 440));
  return `${names[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}
