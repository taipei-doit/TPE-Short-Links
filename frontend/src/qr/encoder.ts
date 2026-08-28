/**
 * QR Code 編碼器（byte mode，版本 1-40，容錯 L/M/Q/H）。
 * 依 ISO/IEC 18004 實作，輸出模組矩陣與「功能圖案」對照表，
 * 讓 render.ts 可以把定位點跟一般資料模組分開畫。
 *
 * 這份實作的矩陣輸出已與 Python `qrcode` 套件逐格比對驗證過
 * （4 種容錯 × 8 種遮罩 × 多種長度，全數相符）。
 */

export type Ecl = 'L' | 'M' | 'Q' | 'H';
export type ModuleRole = 'data' | 'finder' | 'separator' | 'timing' | 'alignment' | 'format' | 'version';

export interface QrMatrix {
  /** 邊長（模組數） */
  size: number;
  /** 版本 1-40 */
  ver: number;
  /** 實際採用的遮罩編號 0-7 */
  mask: number;
  ecl: Ecl;
  /** m[y][x]，1 為深色 */
  m: number[][];
  /** fn[y][x] 為 true 代表功能圖案，不可被遮罩或資料覆蓋 */
  fn: boolean[][];
  /** role[y][x] 說明該格屬於哪一種圖案 */
  role: ModuleRole[][];
}

export interface EncodeOptions {
  ecl?: Ecl;
  /** 指定遮罩 0-7；省略或給負數則自動挑分數最低的 */
  mask?: number;
  /** 最低版本，用來讓同一批 QR 尺寸一致 */
  minVersion?: number;
}

var ECC_CODEWORDS_PER_BLOCK = [
  // 0, 1,2,3,4,5,6,7,8,9,10..40
  [0,7,10,15,20,26,18,20,24,30,18,20,24,26,30,22,24,28,30,28,28,28,28,30,30,26,28,30,30,30,30,30,30,30,30,30,30,30,30,30,30], // L
  [0,10,16,26,18,24,16,18,22,22,26,30,22,22,24,24,28,28,26,26,26,26,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28], // M
  [0,13,22,18,26,18,24,18,22,20,24,28,26,24,20,30,24,28,28,26,30,28,30,30,30,30,28,30,30,30,30,30,30,30,30,30,30,30,30,30,30], // Q
  [0,17,28,22,16,22,28,26,26,24,28,24,28,22,24,24,30,28,28,26,28,30,24,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30]  // H
];
var NUM_ECC_BLOCKS = [
  [0,1,1,1,1,1,2,2,2,2,4,4,4,4,4,6,6,6,6,7,8,8,9,9,10,12,12,12,13,14,15,16,17,18,19,19,20,21,22,24,25],
  [0,1,1,1,2,2,4,4,4,5,5,5,8,9,9,10,10,11,13,14,16,17,17,18,20,21,23,25,26,28,29,31,33,35,37,38,40,43,45,47,49],
  [0,1,1,2,2,4,4,6,6,8,8,8,10,12,16,12,17,16,18,21,20,23,23,25,27,29,34,34,35,38,40,43,45,48,51,53,56,59,62,65,68],
  [0,1,1,2,4,4,4,5,6,8,8,11,11,16,16,18,16,19,21,25,25,25,34,30,32,35,37,40,42,45,48,51,54,57,60,63,66,70,74,77,81]
];
const ECL_BITS: Record<Ecl, number> = { L: 1, M: 0, Q: 3, H: 2 };
const ECL_INDEX: Record<Ecl, number> = { L: 0, M: 1, Q: 2, H: 3 };

// ---- Galois field arithmetic (GF(256), primitive polynomial 0x11D) ----
var EXP = new Uint8Array(512), LOG = new Uint8Array(256);
(function () {
  var x = 1;
  for (var i = 0; i < 255; i++) {
    EXP[i] = x; LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11D;
  }
  for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255];
})();

function gfMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0;
  return EXP[LOG[a] + LOG[b]];
}

function rsGenerator(degree: number): number[] {
  var poly = [1];
  for (var i = 0; i < degree; i++) {
    var next = new Array(poly.length + 1).fill(0);
    for (var j = 0; j < poly.length; j++) {
      next[j] ^= gfMul(poly[j], 1);
      next[j + 1] ^= gfMul(poly[j], EXP[i]);
    }
    poly = next;
  }
  return poly; // length degree+1, leading coeff 1
}

function rsRemainder(data: number[], degree: number): number[] {
  var gen = rsGenerator(degree);
  var rem = new Array(degree).fill(0);
  for (var i = 0; i < data.length; i++) {
    var factor = data[i] ^ rem[0];
    rem.shift();
    rem.push(0);
    for (var j = 0; j < degree; j++) rem[j] ^= gfMul(gen[j + 1], factor);
  }
  return rem;
}

// ---- capacity helpers ----
export function alignPositions(ver: number): number[] {
  if (ver === 1) return [];
  var num = Math.floor(ver / 7) + 2;
  var step = (ver === 32) ? 26
    : Math.ceil((ver * 4 + 4) / (num * 2 - 2)) * 2;
  var pos: number[] = [];
  for (var p = ver * 4 + 10; pos.length < num - 1; p -= step) pos.push(p);
  pos.push(6);
  pos.reverse();
  return pos;
}

function rawDataModules(ver: number): number {
  var result = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    var n = Math.floor(ver / 7) + 2;
    result -= (25 * n - 10) * n - 55;
    if (ver >= 7) result -= 36;
  }
  return result;
}

function totalCodewords(ver: number): number { return Math.floor(rawDataModules(ver) / 8); }

function dataCodewords(ver: number, ecl: Ecl): number {
  var e = ECL_INDEX[ecl];
  return totalCodewords(ver) - ECC_CODEWORDS_PER_BLOCK[e][ver] * NUM_ECC_BLOCKS[e][ver];
}

// ---- bit stream ----
class BitBuf {
  bits: number[] = [];
  push(val: number, len: number): void {
    for (let i = len - 1; i >= 0; i--) this.bits.push((val >>> i) & 1);
  }
}

function utf8Bytes(str: string): number[] {
  const out: number[] = [];
  const arr = new TextEncoder().encode(str);
  for (var i = 0; i < arr.length; i++) out.push(arr[i]);
  return out;
}

function buildCodewords(text: string, ver: number, ecl: Ecl): number[] | null {
  var bytes = utf8Bytes(text);
  var bb = new BitBuf();
  bb.push(4, 4); // byte mode
  bb.push(bytes.length, ver <= 9 ? 8 : 16);
  for (var i = 0; i < bytes.length; i++) bb.push(bytes[i], 8);

  var capacity = dataCodewords(ver, ecl) * 8;
  if (bb.bits.length > capacity) return null;
  bb.push(0, Math.min(4, capacity - bb.bits.length));
  while (bb.bits.length % 8 !== 0) bb.bits.push(0);
  var pad = [0xEC, 0x11], k = 0;
  while (bb.bits.length < capacity) { bb.push(pad[k % 2], 8); k++; }

  const dat: number[] = [];
  for (var b = 0; b < bb.bits.length; b += 8) {
    var v = 0;
    for (var j = 0; j < 8; j++) v = (v << 1) | bb.bits[b + j];
    dat.push(v);
  }

  // split into blocks and interleave
  var e = ECL_INDEX[ecl];
  var numBlocks = NUM_ECC_BLOCKS[e][ver];
  var eccLen = ECC_CODEWORDS_PER_BLOCK[e][ver];
  var total = totalCodewords(ver);
  var shortLen = Math.floor(total / numBlocks) - eccLen;
  var numShort = numBlocks - (total % numBlocks);

  const blocks: number[][] = [], eccBlocks: number[][] = []; let off = 0;
  for (var bi = 0; bi < numBlocks; bi++) {
    var len = shortLen + (bi < numShort ? 0 : 1);
    var blk = dat.slice(off, off + len);
    off += len;
    blocks.push(blk);
    eccBlocks.push(rsRemainder(blk, eccLen));
  }

  const result: number[] = [];
  for (var i2 = 0; i2 < shortLen + 1; i2++) {
    for (var bj = 0; bj < numBlocks; bj++) {
      if (i2 < blocks[bj].length) result.push(blocks[bj][i2]);
    }
  }
  for (var i3 = 0; i3 < eccLen; i3++) {
    for (var bk = 0; bk < numBlocks; bk++) result.push(eccBlocks[bk][i3]);
  }
  return result;
}

// ---- matrix construction ----
function makeMatrix(ver: number): QrMatrix {
  var size = ver * 4 + 17;
  const m: number[][] = [], fn: boolean[][] = [], role: ModuleRole[][] = [];
  for (var y = 0; y < size; y++) {
    m.push(new Array(size).fill(0));
    fn.push(new Array(size).fill(false));
    role.push(new Array(size).fill('data'));
  }
  return { size, m, fn, role, ver, mask: 0, ecl: 'H' };
}

function setFn(q: QrMatrix, x: number, y: number, val: boolean | number, kind: ModuleRole): void {
  if (x < 0 || y < 0 || x >= q.size || y >= q.size) return;
  q.m[y][x] = val ? 1 : 0;
  q.fn[y][x] = true;
  q.role[y][x] = kind;
}

function drawFunctionPatterns(q: QrMatrix): void {
  var size = q.size;
  // timing
  for (var i = 0; i < size; i++) {
    setFn(q, 6, i, i % 2 === 0, 'timing');
    setFn(q, i, 6, i % 2 === 0, 'timing');
  }
  // finders + separators
  var corners = [[0, 0], [size - 7, 0], [0, size - 7]];
  corners.forEach(function (c) {
    var cx = c[0], cy = c[1];
    for (var dy = -1; dy <= 7; dy++) {
      for (var dx = -1; dx <= 7; dx++) {
        var x = cx + dx, y = cy + dy;
        if (x < 0 || y < 0 || x >= size || y >= size) continue;
        var inBox = dx >= 0 && dx <= 6 && dy >= 0 && dy <= 6;
        if (!inBox) { setFn(q, x, y, false, 'separator'); continue; }
        var d = Math.max(Math.abs(dx - 3), Math.abs(dy - 3));
        setFn(q, x, y, d !== 2, 'finder');
      }
    }
  });
  // alignment
  var pos = alignPositions(q.ver);
  for (var a = 0; a < pos.length; a++) {
    for (var b = 0; b < pos.length; b++) {
      if ((a === 0 && b === 0) || (a === 0 && b === pos.length - 1) || (a === pos.length - 1 && b === 0)) continue;
      var px = pos[a], py = pos[b];
      for (var dy2 = -2; dy2 <= 2; dy2++) {
        for (var dx2 = -2; dx2 <= 2; dx2++) {
          setFn(q, px + dx2, py + dy2, Math.max(Math.abs(dx2), Math.abs(dy2)) !== 1, 'alignment');
        }
      }
    }
  }
  // version info
  if (q.ver >= 7) {
    var rem = q.ver;
    for (var v = 0; v < 12; v++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
    var bitsV = (q.ver << 12) | rem;
    for (var i2 = 0; i2 < 18; i2++) {
      var bit = ((bitsV >>> i2) & 1) === 1;
      var xx = Math.floor(i2 / 3), yy = size - 11 + (i2 % 3);
      setFn(q, xx, yy, bit, 'version');
      setFn(q, yy, xx, bit, 'version');
    }
  }
  // reserve format information area (must happen before data placement)
  for (var f = 0; f <= 8; f++) {
    if (f !== 6) { setFn(q, 8, f, false, 'format'); setFn(q, f, 8, false, 'format'); }
  }
  for (var g = 0; g < 8; g++) { setFn(q, size - 1 - g, 8, false, 'format'); setFn(q, 8, size - 1 - g, false, 'format'); }
  setFn(q, 8, size - 8, true, 'format');
}

function drawFormatBits(q: QrMatrix, ecl: Ecl, mask: number): void {
  var data = (ECL_BITS[ecl] << 3) | mask;
  var rem = data;
  for (var i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  var bits = ((data << 10) | rem) ^ 0x5412;
  var size = q.size;
  for (var j = 0; j <= 5; j++) setFn(q, 8, j, (bits >>> j) & 1, 'format');
  setFn(q, 8, 7, (bits >>> 6) & 1, 'format');
  setFn(q, 8, 8, (bits >>> 7) & 1, 'format');
  setFn(q, 7, 8, (bits >>> 8) & 1, 'format');
  for (var k = 9; k < 15; k++) setFn(q, 14 - k, 8, (bits >>> k) & 1, 'format');
  for (var l = 0; l < 8; l++) setFn(q, size - 1 - l, 8, (bits >>> l) & 1, 'format');
  for (var n = 8; n < 15; n++) setFn(q, 8, size - 15 + n, (bits >>> n) & 1, 'format');
  setFn(q, 8, size - 8, true, 'format');
}

function drawData(q: QrMatrix, codewords: number[]): void {
  var size = q.size, i = 0;
  for (var right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (var vert = 0; vert < size; vert++) {
      for (var jj = 0; jj < 2; jj++) {
        var x = right - jj;
        var upward = ((right + 1) & 2) === 0;
        var y = upward ? size - 1 - vert : vert;
        if (q.fn[y][x]) continue;
        if (i < codewords.length * 8) {
          q.m[y][x] = (codewords[i >>> 3] >>> (7 - (i & 7))) & 1;
          i++;
        }
      }
    }
  }
}

function maskFn(id: number, x: number, y: number): boolean {
  switch (id) {
    case 0: return (x + y) % 2 === 0;
    case 1: return y % 2 === 0;
    case 2: return x % 3 === 0;
    case 3: return (x + y) % 3 === 0;
    case 4: return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0;
    case 5: return (x * y) % 2 + (x * y) % 3 === 0;
    case 6: return ((x * y) % 2 + (x * y) % 3) % 2 === 0;
    default: return (((x + y) % 2) + ((x * y) % 3)) % 2 === 0;
  }
}

function applyMask(q: QrMatrix, id: number): void {
  for (var y = 0; y < q.size; y++)
    for (var x = 0; x < q.size; x++)
      if (!q.fn[y][x] && maskFn(id, x, y)) q.m[y][x] ^= 1;
}

function penalty(q: QrMatrix): number {
  var size = q.size, m = q.m, p = 0;
  // rule 1: runs
  for (var y = 0; y < size; y++) {
    var runC = m[y][0], runL = 1;
    for (var x = 1; x < size; x++) {
      if (m[y][x] === runC) { runL++; if (runL === 5) p += 3; else if (runL > 5) p += 1; }
      else { runC = m[y][x]; runL = 1; }
    }
  }
  for (var x2 = 0; x2 < size; x2++) {
    var rc = m[0][x2], rl = 1;
    for (var y2 = 1; y2 < size; y2++) {
      if (m[y2][x2] === rc) { rl++; if (rl === 5) p += 3; else if (rl > 5) p += 1; }
      else { rc = m[y2][x2]; rl = 1; }
    }
  }
  // rule 2: 2x2 blocks
  for (var y3 = 0; y3 < size - 1; y3++)
    for (var x3 = 0; x3 < size - 1; x3++) {
      var c = m[y3][x3];
      if (c === m[y3][x3 + 1] && c === m[y3 + 1][x3] && c === m[y3 + 1][x3 + 1]) p += 3;
    }
  // rule 3: finder-like patterns
  var pat = [1, 0, 1, 1, 1, 0, 1];
  function matches(get: (i: number) => number, i: number): boolean {
    for (var k = 0; k < 7; k++) if (get(i + k) !== pat[k]) return false;
    // needs 4 light modules on one side
    var before = true, after = true;
    for (var k2 = 1; k2 <= 4; k2++) { if (get(i - k2) !== 0) { before = false; break; } }
    for (var k3 = 0; k3 < 4; k3++) { if (get(i + 7 + k3) !== 0) { after = false; break; } }
    return before || after;
  }
  for (var y4 = 0; y4 < size; y4++) {
    (function (yy) {
      const get = function (i: number): number { return (i < 0 || i >= size) ? 0 : m[yy][i]; };
      for (var i = 0; i <= size - 7; i++) if (matches(get, i)) p += 40;
    })(y4);
  }
  for (var x4 = 0; x4 < size; x4++) {
    (function (xx) {
      const get = function (i: number): number { return (i < 0 || i >= size) ? 0 : m[i][xx]; };
      for (var i = 0; i <= size - 7; i++) if (matches(get, i)) p += 40;
    })(x4);
  }
  // rule 4: balance
  var dark = 0;
  for (var y5 = 0; y5 < size; y5++) for (var x5 = 0; x5 < size; x5++) dark += m[y5][x5];
  var ratio = dark * 100 / (size * size);
  p += Math.floor(Math.abs(ratio - 50) / 5) * 10;
  return p;
}

export function encode(text: string, opts?: EncodeOptions): QrMatrix {
  opts = opts || {};
  const ecl: Ecl = opts.ecl || 'H';
  var ver = 1;
  for (; ver <= 40; ver++) {
    var bytes = utf8Bytes(text).length;
    var need = 4 + (ver <= 9 ? 8 : 16) + bytes * 8;
    if (need <= dataCodewords(ver, ecl) * 8) break;
  }
  if (ver > 40) throw new Error('資料太長，無法編碼');
  if (opts.minVersion && ver < opts.minVersion) ver = opts.minVersion;

  const codewords = buildCodewords(text, ver, ecl)!;
  let best: QrMatrix | null = null, bestScore = Infinity;
  const masks: number[] = (opts.mask === undefined || opts.mask === null || opts.mask < 0)
    ? [0, 1, 2, 3, 4, 5, 6, 7] : [opts.mask];
  for (var mi = 0; mi < masks.length; mi++) {
    var q = makeMatrix(ver);
    drawFunctionPatterns(q);
    drawData(q, codewords);
    drawFormatBits(q, ecl, masks[mi]);
    applyMask(q, masks[mi]);
    var s = penalty(q);
    if (s < bestScore) { bestScore = s; best = q; best.mask = masks[mi]; }
  }
  best!.ecl = ecl;
  return best!;
}
