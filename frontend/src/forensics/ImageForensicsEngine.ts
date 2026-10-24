// Non-destructive forensic pixel pipeline (Canvas 2D). apply() mutates an ImageData in place.
// Point ops (brightness/contrast/shadowLift/gamma/invert) go through a per-channel LUT; sharpness is a
// separate convolution pass; channel isolation zeroes the other channels.

export interface ImageFilterState {
  brightness: number // -100..100
  contrast: number // -100..100
  shadowLift: number // 0..100 — boosts values under RGB 60 (reveal dark window silhouettes)
  gamma: number // 0.2..3.0
  invert: boolean
  sharpness: number // 0..100 — convolution strength (also the high-pass control)
  channelIsolation: 'ALL' | 'R' | 'G' | 'B'
}

export const DEFAULT_FILTER: ImageFilterState = {
  brightness: 0, contrast: 0, shadowLift: 0, gamma: 1, invert: false, sharpness: 0, channelIsolation: 'ALL',
}

export const PRESETS: Record<string, Partial<ImageFilterState>> = {
  // Shadow Recovery: lift darks hard + gamma expansion — pull detail out of black windows/corners
  'Shadow Recovery': { ...DEFAULT_FILTER, shadowLift: 75, gamma: 1.7, brightness: 8, contrast: 10 },
  // Invert & High-Pass: accentuate structural edges / street furniture
  'Invert & High-Pass': { ...DEFAULT_FILTER, invert: true, contrast: 40, sharpness: 70 },
  // RGB Channel Splitter: isolate the red channel (neon/ambient light signatures); cycle R→G→B in the UI
  'Red Channel': { ...DEFAULT_FILTER, channelIsolation: 'R', contrast: 25 },
  'Green Channel': { ...DEFAULT_FILTER, channelIsolation: 'G', contrast: 25 },
  'Blue Channel': { ...DEFAULT_FILTER, channelIsolation: 'B', contrast: 25 },
  // Reflective De-glare: contrast normalization for glossy glass/mirrors
  'Reflective De-glare': { ...DEFAULT_FILTER, contrast: -28, shadowLift: 22, gamma: 1.15 },
}

function clamp(x: number) {
  return x < 0 ? 0 : x > 255 ? 255 : x
}

// One LUT for every point operation, applied per channel.
function buildLut(s: ImageFilterState): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(256)
  const c = (s.contrast / 100) * 255
  const cf = (259 * (c + 255)) / (255 * (259 - c)) // standard contrast factor
  const invGamma = 1 / s.gamma
  for (let i = 0; i < 256; i++) {
    let v = i
    if (s.shadowLift > 0 && v < 60) v += (s.shadowLift / 100) * (60 - v) // raise only the deep shadows
    v = v + s.brightness * 1.5
    v = cf * (v - 128) + 128
    v = 255 * Math.pow(clamp(v) / 255, invGamma)
    if (s.invert) v = 255 - v
    lut[i] = clamp(v)
  }
  return lut
}

function sharpen(src: Uint8ClampedArray, w: number, h: number, strength: number): Uint8ClampedArray {
  // high-pass / unsharp 3x3: center 1+4k, edges -k
  const k = (strength / 100) * 4
  const center = 1 + 4 * k
  const out = new Uint8ClampedArray(src.length)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4
      for (let ch = 0; ch < 3; ch++) {
        const up = y > 0 ? src[i - w * 4 + ch] : src[i + ch]
        const dn = y < h - 1 ? src[i + w * 4 + ch] : src[i + ch]
        const lf = x > 0 ? src[i - 4 + ch] : src[i + ch]
        const rt = x < w - 1 ? src[i + 4 + ch] : src[i + ch]
        out[i + ch] = clamp(center * src[i + ch] - k * (up + dn + lf + rt))
      }
      out[i + 3] = src[i + 3]
    }
  }
  return out
}

export function apply(img: ImageData, s: ImageFilterState): void {
  const d = img.data
  const lut = buildLut(s)
  const iso = s.channelIsolation
  for (let i = 0; i < d.length; i += 4) {
    const r = lut[d[i]], g = lut[d[i + 1]], b = lut[d[i + 2]]
    d[i] = iso === 'ALL' || iso === 'R' ? r : 0
    d[i + 1] = iso === 'ALL' || iso === 'G' ? g : 0
    d[i + 2] = iso === 'ALL' || iso === 'B' ? b : 0
  }
  if (s.sharpness > 0) {
    const sharpened = sharpen(d, img.width, img.height, s.sharpness)
    d.set(sharpened)
  }
}

export function isDefault(s: ImageFilterState): boolean {
  return (Object.keys(DEFAULT_FILTER) as (keyof ImageFilterState)[]).every((k) => s[k] === DEFAULT_FILTER[k])
}
