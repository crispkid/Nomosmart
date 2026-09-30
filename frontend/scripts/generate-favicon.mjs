// First-party brand-mark: the existing green gradient/white N, no fonts or dependencies.
// Reproduce with: node frontend/scripts/generate-favicon.mjs
import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

export function faviconBytes() {
  const sizes = [16, 32];
  const images = sizes.map((size) => {
    const maskStride = Math.ceil(size / 32) * 4;
    const bitmap = Buffer.alloc(40 + size * size * 4 + maskStride * size);
    bitmap.writeUInt32LE(40, 0); bitmap.writeInt32LE(size, 4); bitmap.writeInt32LE(size * 2, 8);
    bitmap.writeUInt16LE(1, 12); bitmap.writeUInt16LE(32, 14);
    bitmap.writeUInt32LE(size * size * 4, 20);
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      let alpha = 0; const rgb = [0, 0, 0];
      for (let sy = 0; sy < 4; sy++) for (let sx = 0; sx < 4; sx++) {
        const px = (x + (sx + 0.5) / 4) * 32 / size;
        const py = (y + (sy + 0.5) / 4) * 32 / size;
        const dx = Math.max(6 - px, px - 26, 0), dy = Math.max(6 - py, py - 26, 0);
        if (dx * dx + dy * dy > 36) continue;
        alpha++;
        const letter = py >= 7 && py <= 25 && ((px >= 8 && px <= 11.5) ||
          (px >= 20.5 && px <= 24) || (px >= 11 && px <= 21 && Math.abs(py - (7 + (px - 10) * 1.6)) <= 3));
        const gradient = (px + py) / 64;
        [47, 125, 87].forEach((start, c) => { rgb[c] += letter ? 255 : start + ([95, 174, 136][c] - start) * gradient; });
      }
      const offset = 40 + ((size - 1 - y) * size + x) * 4;
      if (alpha) for (let c = 0; c < 3; c++) bitmap[offset + 2 - c] = Math.round(rgb[c] / alpha);
      bitmap[offset + 3] = Math.round(alpha * 255 / 16);
      if (!alpha) bitmap[40 + size * size * 4 + (size - 1 - y) * maskStride + (x >> 3)] |= 0x80 >> (x % 8);
    }
    return bitmap;
  });
  const header = Buffer.alloc(6 + sizes.length * 16);
  header.writeUInt16LE(1, 2); header.writeUInt16LE(sizes.length, 4);
  let offset = header.length;
  sizes.forEach((size, i) => {
    const entry = 6 + i * 16;
    header[entry] = size; header[entry + 1] = size;
    header.writeUInt16LE(1, entry + 4); header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(images[i].length, entry + 8); header.writeUInt32LE(offset, entry + 12);
    offset += images[i].length;
  });
  return Buffer.concat([header, ...images]);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await writeFile(new URL("../public/favicon.ico", import.meta.url), faviconBytes());
}
