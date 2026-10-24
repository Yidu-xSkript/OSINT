// Run: npx tsx forensics.check.ts   — verifies the forensic pixel pipeline (no DOM needed).
import assert from 'node:assert'
import { apply, DEFAULT_FILTER, isDefault, PRESETS } from './src/forensics/ImageForensicsEngine.ts'

const px = (rgb: number[], s = DEFAULT_FILTER) => {
  const img = { data: new Uint8ClampedArray([...rgb, 255]), width: 1, height: 1 }
  apply(img, s)
  return [img.data[0], img.data[1], img.data[2]]
}

// Shadow Recovery lifts deep shadows well clear of their original value
assert(px([11, 13, 16], { ...DEFAULT_FILTER, ...PRESETS['Shadow Recovery'] })[0] > 70, 'shadow lift')
// Invert
assert(Math.abs(px([200, 0, 0], { ...DEFAULT_FILTER, invert: true })[0] - 55) < 5, 'invert')
// Channel isolation zeroes the other two channels
assert.deepEqual(px([100, 150, 200], { ...DEFAULT_FILTER, channelIsolation: 'R' }), [100, 0, 0], 'isolate R')
assert.deepEqual(px([100, 150, 200], { ...DEFAULT_FILTER, channelIsolation: 'B' }), [0, 0, 200], 'isolate B')
// Default is a no-op
assert.deepEqual(px([42, 99, 7]), [42, 99, 7], 'default no-op')
assert(isDefault(DEFAULT_FILTER) && !isDefault({ ...DEFAULT_FILTER, gamma: 1.5 }), 'isDefault')
// Sharpness runs without error and preserves alpha / dimensions
const big = { data: new Uint8ClampedArray(4 * 9), width: 3, height: 3 }
for (let i = 0; i < 9; i++) { big.data[i * 4] = 128; big.data[i * 4 + 3] = 255 }
big.data[16] = 255 // a bright center pixel so the kernel has an edge to act on
apply(big, { ...DEFAULT_FILTER, sharpness: 50 })
assert(big.data.length === 36 && big.data[3] === 255, 'sharpen keeps shape + alpha')
console.log('ok')
