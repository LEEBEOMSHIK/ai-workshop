/** Shared pixel artwork: a visitor, Founder and the publicly registered RAG team. */
export const humanPalettes = {
  visitor: { hair: "#53382d", light: "#a36b44", coat: "#cb7650", shade: "#944b38", shirt: "#f5d5a0", skin: "#ecc49b", style: "casual", accessory: "bag" },
  founder: { hair: "#283139", light: "#535656", coat: "#344958", shade: "#20313e", shirt: "#faf0d9", skin: "#e8bd94", style: "parted", accessory: "tie" },
  "rag-chief": { hair: "#354247", light: "#728085", coat: "#397a77", shade: "#255450", shirt: "#f6e3ba", skin: "#e7ba90", style: "swept", accessory: "glasses" },
  "document-structure": { hair: "#784b32", light: "#b5794b", coat: "#eee4ce", shade: "#b4bfaf", shirt: "#588c83", skin: "#efc8a4", style: "bob", accessory: "glasses" },
  chunking: { hair: "#393945", light: "#696274", coat: "#b98e4e", shade: "#8a693d", shirt: "#f0dcc0", skin: "#dfae83", style: "bun", accessory: "pencil" },
  "embedding-indexing": { hair: "#384244", light: "#637778", coat: "#557c9d", shade: "#355570", shirt: "#d4e5de", skin: "#c78f6a", style: "swept", accessory: "headset" },
  "retrieval-fusion": { hair: "#944f39", light: "#c88354", coat: "#788e58", shade: "#546b40", shirt: "#e9d9ad", skin: "#efc59c", style: "parted", accessory: "bag" },
  "evidence-highlighting": { hair: "#494253", light: "#776986", coat: "#a27a95", shade: "#74576f", shirt: "#f1dfc6", skin: "#d6a17b", style: "bob", accessory: "pencil" },
  "quality-evaluation": { hair: "#c3b8a1", light: "#eee1c4", coat: "#568b94", shade: "#36676f", shirt: "#e8dfc6", skin: "#e4b890", style: "curly", accessory: "glasses" },
} as const;
export type HumanIdentity = keyof typeof humanPalettes;
export type Pixel = readonly [color: string, x: number, y: number, width: number, height: number];
export function humanPixels(identity: HumanIdentity, direction = 0, step = 0): Pixel[] {
  const p = humanPalettes[identity];
  if (!p) throw new Error(`Unknown character artwork: ${identity}`);
  const pixels: Pixel[] = [];
  const r = (c: string, x: number, y: number, w: number, h: number) => pixels.push([c, x, y, w, h]);
  const side = direction > 1, back = direction === 1;
  r("#22313235", 9, 60, 31, 3);
  if (side) {
    // Draw a right-facing profile, mirrored as a whole for left. Far limbs
    // precede the torso; the near arm occludes it, rather than two front arms.
    const s = (c: string, x: number, y: number, w: number, h: number) => r(c, direction === 2 ? 48 - x - w : x, y, w, h);
    const stride = step * 4;
    s(p.shade, 24 + stride, 33, 5, 13); s(p.skin, 24 + stride, 45, 4, 5);
    s("#283642", 21, 47, 7, 7); s("#283642", 21 - stride, 52, 7, 8);
    s("#172630", 21 - stride, 58, 11, 4);
    s("#364958", 19, 47, 8, 8); s("#364958", 19 + stride, 53, 8, 8);
    s("#172630", 19 + stride, 59, 12, 3); s("#74817d", 24 + stride, 59, 6, 1);
    s(p.shade, 16, 29, 17, 22); s(p.coat, 18, 30, 13, 18);
    s(p.shirt, 30, 31, 2, 9); s(p.shade, 17, 47, 15, 3);
    s(p.coat, 19 - stride, 32, 6, 14); s(p.skin, 20 - stride, 46, 5, 5);
    s("#fff4d033", 19 - stride, 33, 3, 2);
    s("#bd8b68", 22, 24, 8, 7);
    s(p.hair, 15, 7, 17, 6); s(p.hair, 12, 12, 21, 14);
    s(p.skin, 23, 13, 11, 13); s("#f6d6af", 28, 15, 6, 8);
    s(p.skin, 33, 20, 4, 4); // nose extends beyond the profile
    s(p.hair, 14, 10, 19, 5); s(p.light, 16, 8, 12, 3);
    s(p.hair, 13, 14, 11, 12); s(p.skin, 23, 20, 3, 5);
    s("#29383c", 31, 18, 2, 3); s("#c88f73", 31, 25, 3, 1);
    if (p.style === "bob") { s(p.hair, 12, 15, 10, 19); s(p.light, 13, 17, 2, 13); }
    if (p.style === "bun") { s(p.hair, 9, 3, 10, 10); s(p.light, 10, 4, 6, 3); }
    if (p.style === "swept") { s(p.hair, 25, 11, 9, 5); s(p.light, 26, 11, 6, 2); }
    if (p.style === "curly") { s(p.hair, 11, 9, 5, 12); s(p.light, 17, 6, 5, 3); }
    if (p.style === "parted") s(p.light, 17, 11, 10, 2);
    if (p.accessory === "glasses") { s("#405457", 28, 17, 7, 1); s("#405457", 28, 22, 7, 1); s("#405457", 34, 18, 1, 4); s("#405457", 24, 18, 5, 1); }
    if (p.accessory === "tie") s("#b5804e", 32, 32, 2, 10);
    if (p.accessory === "headset") { s("#233d48", 21, 15, 4, 11); s("#82cbbd", 22, 17, 2, 5); s("#233d48", 25, 24, 7, 2); }
    if (p.accessory === "bag") { s("#8d603d", 17, 30, 3, 19); s("#66432f", 12, 43, 10, 11); s("#b18752", 12, 43, 10, 3); }
    if (p.accessory === "pencil") { s("#f7cd69", 24 - stride, 42, 2, 10); s("#393b41", 24 - stride, 52, 2, 2); }
    return pixels;
  }
  step *= 2;
  r("#283642", 14, 47, 9, 13 + step); r("#364958", 27, 47, 8, 13 - step);
  r("#172630", 12, 58 + step, 11, 4); r("#172630", 27, 58 - step, 11, 4);
  r("#74817d", 13, 58 + step, 7, 1); r("#74817d", 28, 58 - step, 7, 1);
  r(p.shade, 10, 29, 29, 22); r(p.coat, 12, 29, 23, 19);
  if (back) { r(p.shade, 23, 32, 1, 16); r(p.shade, 14, 46, 20, 2); }
  else { r(p.shirt, 21, 29, 8, 17); r(p.shade, 19, 30, 2, 14); r(p.shade, 29, 30, 2, 16); }
  r(p.coat, 7, 32 - step, 6, 12); r(p.shade, 36, 32 + step, 6, 12);
  r(p.skin, 7, 44 - step, 5, 6); r(p.skin, 37, 44 + step, 5, 6);
  r("#fff4d033", 13, 31, 4, 2);
  if (!back) r("#ead5ac", 14, 39, 4, 3);
  if (back) {
    r("#bd8b68", 19, 24, 12, 7);
    r(p.hair, 12, 5, 24, 7); r(p.hair, 9, 11, 29, 15);
    r(p.hair, 13, 24, 21, 4); r(p.light, 13, 7, 14, 3); r(p.light, 11, 14, 3, 9);
    if (p.style === "bob") { r(p.hair, 8, 14, 6, 20); r(p.hair, 34, 14, 6, 21); r(p.light, 9, 17, 2, 13); }
    if (p.style === "bun") { r(p.hair, 28, 1, 10, 9); r(p.light, 29, 2, 6, 3); }
    if (p.style === "curly") { r(p.hair, 8, 9, 5, 9); r(p.hair, 35, 8, 5, 9); r(p.light, 13, 5, 5, 3); }
    if (p.accessory === "headset") { r("#233d48", 8, 14, 4, 12); r("#82cbbd", 9, 17, 2, 5); r("#233d48", 35, 15, 4, 10); }
    if (p.accessory === "bag") { r("#8d603d", 33, 30, 3, 20); r("#66432f", 29, 43, 10, 11); r("#b18752", 29, 43, 10, 3); }
    if (p.accessory === "pencil") { r("#f7cd69", 8, 39 - step, 2, 11); r("#393b41", 8, 50 - step, 2, 2); }
    return pixels;
  }
  r(p.hair, 12, 5, 24, 7); r(p.hair, 9, 11, 29, 16);
  r("#bd8b68", 15, 24, 19, 8); r(p.skin, 13, 12, 23, 14);
  r("#f6d6af", 15, 14, 16, 10); r(p.hair, 10, 9, 27, 5);
  r(p.light, 13, 7, 14, 3); r(p.hair, 10, 13, 4, 10);
  if (p.style === "bob") { r(p.hair, 8, 14, 6, 20); r(p.hair, 34, 14, 6, 21); r(p.light, 9, 17, 2, 13); }
  if (p.style === "bun") { r(p.hair, 28, 1, 10, 9); r(p.light, 29, 2, 6, 3); }
  if (p.style === "swept") { r(p.hair, 24, 10, 12, 8); r(p.light, 27, 10, 7, 2); }
  if (p.style === "curly") { r(p.hair, 8, 9, 5, 9); r(p.hair, 35, 8, 5, 9); r(p.light, 13, 5, 5, 3); }
  if (p.style === "parted") { r(p.skin, 27, 10, 2, 4); r(p.light, 12, 10, 12, 2); }
  r("#29383c", 17, 19, 2, 3); r("#29383c", 29, 19, 2, 3);
  r("#c88f73", 22, 25, 5, 1);
  if (p.accessory === "glasses") { r("#405457", 14, 17, 9, 1); r("#405457", 26, 17, 9, 1); r("#405457", 14, 22, 9, 1); r("#405457", 26, 22, 9, 1); r("#405457", 14, 18, 1, 4); r("#405457", 22, 18, 5, 1); r("#405457", 34, 18, 1, 4); }
  if (p.accessory === "tie") { r("#b5804e", 24, 31, 3, 13); r("#e0b375", 24, 31, 2, 3); }
  if (p.accessory === "headset") { r("#233d48", 8, 14, 4, 12); r("#82cbbd", 9, 17, 2, 5); r("#233d48", 35, 15, 4, 10); }
  if (p.accessory === "bag") { r("#8d603d", 12, 30, 3, 20); r("#66432f", 9, 43, 10, 11); r("#b18752", 9, 43, 10, 3); }
  if (p.accessory === "pencil") { r("#f7cd69", 38, 39, 2, 11); r("#393b41", 38, 50, 2, 2); }
  return pixels;
}
