/**
 * 把 encoder.ts 產生的模組矩陣畫成有樣式的 SVG。
 *
 * 定位點（三個角落的方框）與一般資料模組分開繪製，才能各自套用不同形狀。
 * 中央市徽會把底下的模組挖空，並靠容錯能力還原，因此使用市徽時容錯固定為 H。
 */

import { encode, type Ecl } from './encoder';
import { TAIPEI_MARK } from './taipeiMark';

export type ModuleShape = 'square' | 'rounded' | 'dot' | 'diamond' | 'liquid';
export type EyeFrame = 'square' | 'rounded' | 'circle' | 'leaf';
export type EyeBall = 'square' | 'rounded' | 'circle' | 'leaf' | 'azalea';
export type ColorMode = 'solid' | 'linear' | 'radial';

export interface QrStyle {
  moduleShape: ModuleShape;
  eyeFrame: EyeFrame;
  eyeBall: EyeBall;
  colorMode: ColorMode;
  /** 前景色；漸層時為起點 */
  fg1: string;
  /** 漸層終點，colorMode 為 solid 時忽略 */
  fg2: string;
  /** QR 本體底色，通常是白色 */
  bg: string;
  /** 定位點顏色，留空則跟前景一致 */
  eyeColor?: string;
  /** 外框卡片底色 */
  frameBg: string;
  /** 外框文字顏色 */
  frameFg: string;
}

export interface RenderOptions {
  /** 要編碼的內容，通常是短網址 */
  text: string;
  style: QrStyle;
  /** 上方文字，空字串代表不畫上方色帶 */
  topText?: string;
  /** 下方文字，空字串代表不畫下方色帶 */
  bottomText?: string;
  /** 中央是否放市徽 */
  showLogo?: boolean;
  /** 容錯等級，預設 H；showLogo 為 true 時強制 H */
  ecl?: Ecl;
  /** 靜區留白（模組數），規範要求至少 4 */
  margin?: number;
}

export interface RenderResult {
  svg: string;
  /** QR 版本 1-40 */
  version: number;
  /** 邊長模組數 */
  size: number;
  /** 市徽佔用的模組寬度 */
  logoModules: number;
  /** 市徽佔整體碼面積的比例 0-1 */
  logoCoverage: number;
}

/** 中央市徽的邊長佔 QR 邊長的比例。實測 0.22 在 H 級容錯下面積約 5.8%，安全。 */
const LOGO_SCALE = 0.22;

const FONT_STACK =
  '&quot;PingFang TC&quot;,&quot;Noto Sans TC&quot;,&quot;Microsoft JhengHei&quot;,sans-serif';

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}

/** 四個角可各自指定圓角半徑的矩形路徑，順時針。 */
function rrPath(x: number, y: number, w: number, h: number, r: [number, number, number, number]): string {
  const [tl, tr, br, bl] = r;
  return (
    `M${x + tl} ${y}` +
    `H${x + w - tr}` + (tr ? `A${tr} ${tr} 0 0 1 ${x + w} ${y + tr}` : '') +
    `V${y + h - br}` + (br ? `A${br} ${br} 0 0 1 ${x + w - br} ${y + h}` : '') +
    `H${x + bl}` + (bl ? `A${bl} ${bl} 0 0 1 ${x} ${y + h - bl}` : '') +
    `V${y + tl}` + (tl ? `A${tl} ${tl} 0 0 1 ${x + tl} ${y}` : '') +
    'Z'
  );
}

/** 與 rrPath 同形但逆時針，接在同一個 path 後面就會挖成中空。 */
function rrPathReversed(x: number, y: number, size: number, r: [number, number, number, number]): string {
  const [tl, tr, br, bl] = r;
  const w = size, h = size;
  return (
    `M${x + tl} ${y}` + (tl ? `A${tl} ${tl} 0 0 0 ${x} ${y + tl}` : '') +
    `V${y + h - bl}` + (bl ? `A${bl} ${bl} 0 0 0 ${x + bl} ${y + h}` : '') +
    `H${x + w - br}` + (br ? `A${br} ${br} 0 0 0 ${x + w} ${y + h - br}` : '') +
    `V${y + tr}` + (tr ? `A${tr} ${tr} 0 0 0 ${x + w - tr} ${y}` : '') +
    `H${x + tl}Z`
  );
}

interface Neighbours { t: boolean; r: boolean; b: boolean; l: boolean; }

function modulePath(x: number, y: number, shape: ModuleShape, nb: Neighbours): string {
  switch (shape) {
    case 'dot':
      return `M${x + 0.5} ${y + 0.06}a0.44 0.44 0 1 0 0.001 0Z`;
    case 'diamond':
      return `M${x + 0.5} ${y}L${x + 1} ${y + 0.5}L${x + 0.5} ${y + 1}L${x} ${y + 0.5}Z`;
    case 'rounded':
      return rrPath(x + 0.04, y + 0.04, 0.92, 0.92, [0.3, 0.3, 0.3, 0.3]);
    case 'liquid': {
      // 只在沒有鄰居的那一角做圓角，相鄰的模組就會連成一整片
      const k = 0.5;
      return rrPath(x, y, 1, 1, [
        nb.t || nb.l ? 0 : k,
        nb.t || nb.r ? 0 : k,
        nb.b || nb.r ? 0 : k,
        nb.b || nb.l ? 0 : k,
      ]);
    }
    default:
      return rrPath(x, y, 1, 1, [0, 0, 0, 0]);
  }
}

type Corner = 'tl' | 'tr' | 'bl';

/** 定位點外框：7×7 的一圈，外形 + 逆時針內孔。 */
function eyeFramePath(x: number, y: number, style: EyeFrame, corner: Corner): string {
  if (style === 'circle') {
    return (
      `M${x + 3.5} ${y}a3.5 3.5 0 1 0 0.001 0Z` +
      `M${x + 3.5} ${y + 1}a2.5 2.5 0 1 1 -0.001 0Z`
    );
  }
  const idx = corner === 'tl' ? 0 : corner === 'tr' ? 1 : 3;
  let ro: [number, number, number, number];
  let ri: [number, number, number, number];
  if (style === 'rounded') {
    ro = [2, 2, 2, 2];
    ri = [1.3, 1.3, 1.3, 1.3];
  } else if (style === 'leaf') {
    // 尖角朝向碼的外側，其餘三角收圓
    ro = [3.5, 3.5, 3.5, 3.5];
    ri = [2.5, 2.5, 2.5, 2.5];
    ro[idx] = 0; ro[(idx + 2) % 4] = 0;
    ri[idx] = 0; ri[(idx + 2) % 4] = 0;
  } else {
    ro = [0, 0, 0, 0];
    ri = [0, 0, 0, 0];
  }
  return rrPath(x, y, 7, 7, ro) + ' ' + rrPathReversed(x + 1, y + 1, 5, ri);
}

/** 杜鵑花：五片花瓣加花心，用重疊的圓組成。 */
function flowerCircles(cx: number, cy: number, r: number, fill: string): string {
  let out = '';
  const petal = r * 0.46;
  const dist = r * 0.55;
  for (let i = 0; i < 5; i++) {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / 5;
    out +=
      `<circle cx="${(cx + Math.cos(a) * dist).toFixed(3)}" ` +
      `cy="${(cy + Math.sin(a) * dist).toFixed(3)}" ` +
      `r="${petal.toFixed(3)}" fill="${fill}"/>`;
  }
  out += `<circle cx="${cx.toFixed(3)}" cy="${cy.toFixed(3)}" r="${(r * 0.42).toFixed(3)}" fill="${fill}"/>`;
  return out;
}

function eyeBallSvg(x: number, y: number, style: EyeBall, corner: Corner, fill: string): string {
  const bx = x + 2, by = y + 2; // 內點是中央的 3×3
  if (style === 'azalea') return flowerCircles(bx + 1.5, by + 1.5, 1.55, fill);
  let d: string;
  if (style === 'circle') {
    d = `M${bx + 1.5} ${by}a1.5 1.5 0 1 0 0.001 0Z`;
  } else if (style === 'rounded') {
    d = rrPath(bx, by, 3, 3, [1, 1, 1, 1]);
  } else if (style === 'leaf') {
    const idx = corner === 'tl' ? 0 : corner === 'tr' ? 1 : 3;
    const r: [number, number, number, number] = [1.5, 1.5, 1.5, 1.5];
    r[idx] = 0; r[(idx + 2) % 4] = 0;
    d = rrPath(bx, by, 3, 3, r);
  } else {
    d = rrPath(bx, by, 3, 3, [0, 0, 0, 0]);
  }
  return `<path d="${d}" fill="${fill}"/>`;
}

export function renderQrSvg(o: RenderOptions): RenderResult {
  const style = o.style;
  const topText = (o.topText ?? '').trim();
  const bottomText = (o.bottomText ?? '').trim();
  const showLogo = !!o.showLogo;
  const ecl: Ecl = showLogo ? 'H' : (o.ecl ?? 'H');
  const margin = o.margin ?? 4;

  const q = encode(o.text, { ecl });
  const n = q.size;
  const inner = n + margin * 2;

  const hasFrame = topText.length > 0 || bottomText.length > 0;
  const frameTop = topText ? 7 : 0;
  const frameBottom = bottomText ? 7 : 0;
  const framePad = hasFrame ? 2.5 : 0;

  const totalW = inner + framePad * 2;
  const totalH = inner + frameTop + frameBottom + framePad * 2;

  const fill = style.colorMode === 'solid' ? style.fg1 : 'url(#qrg)';
  const eyeFill = style.eyeColor ? style.eyeColor : fill;

  let defs = '';
  if (style.colorMode === 'linear') {
    defs =
      `<linearGradient id="qrg" x1="0" y1="0" x2="1" y2="1">` +
      `<stop offset="0" stop-color="${style.fg1}"/><stop offset="1" stop-color="${style.fg2}"/></linearGradient>`;
  } else if (style.colorMode === 'radial') {
    defs =
      `<radialGradient id="qrg" cx="0.5" cy="0.5" r="0.75">` +
      `<stop offset="0" stop-color="${style.fg1}"/><stop offset="1" stop-color="${style.fg2}"/></radialGradient>`;
  }

  // 市徽挖空範圍，取偶奇一致才能正好置中
  let logoModules = 0;
  let lo0 = 0, lo1 = -1;
  if (showLogo) {
    logoModules = Math.round(n * LOGO_SCALE);
    if (logoModules % 2 !== n % 2) logoModules += 1;
    lo0 = Math.floor((n - logoModules) / 2);
    lo1 = lo0 + logoModules - 1;
  }
  const inLogo = (x: number, y: number) =>
    logoModules > 0 && x >= lo0 && x <= lo1 && y >= lo0 && y <= lo1;

  const isDark = (x: number, y: number): boolean => {
    if (x < 0 || y < 0 || x >= n || y >= n) return false;
    const role = q.role[y][x];
    if (role === 'finder' || role === 'separator') return false; // 定位點另外畫
    if (inLogo(x, y)) return false;
    return q.m[y][x] === 1;
  };

  let d = '';
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      if (!isDark(x, y)) continue;
      d += modulePath(x + margin, y + margin, style.moduleShape, {
        t: isDark(x, y - 1), b: isDark(x, y + 1),
        l: isDark(x - 1, y), r: isDark(x + 1, y),
      });
    }
  }

  let eyes = '';
  const corners: Array<[number, number, Corner]> = [
    [0, 0, 'tl'],
    [n - 7, 0, 'tr'],
    [0, n - 7, 'bl'],
  ];
  for (const [cx, cy, corner] of corners) {
    eyes += `<path d="${eyeFramePath(cx + margin, cy + margin, style.eyeFrame, corner)}" fill="${eyeFill}"/>`;
    eyes += eyeBallSvg(cx + margin, cy + margin, style.eyeBall, corner, eyeFill);
  }

  let logoSvg = '';
  if (showLogo && logoModules > 0) {
    const pad = 0.6;
    const bx = lo0 + margin - pad;
    const bs = logoModules + pad * 2;
    logoSvg =
      `<rect x="${bx}" y="${bx}" width="${bs}" height="${bs}" rx="${bs * 0.18}" fill="${style.bg}"/>` +
      `<svg x="${lo0 + margin}" y="${lo0 + margin}" width="${logoModules}" height="${logoModules}" ` +
      `viewBox="${TAIPEI_MARK.viewBox}" preserveAspectRatio="xMidYMid meet">${TAIPEI_MARK.body}</svg>`;
  }

  const ox = framePad;
  const oy = framePad + frameTop;

  let frameSvg: string;
  if (hasFrame) {
    frameSvg =
      `<rect x="0" y="0" width="${totalW}" height="${totalH}" rx="${totalW * 0.06}" fill="${style.frameBg}"/>` +
      `<rect x="${ox}" y="${oy}" width="${inner}" height="${inner}" rx="${inner * 0.04}" fill="${style.bg}"/>`;
    if (topText) {
      frameSvg += textBand(totalW / 2, framePad + frameTop / 2 + 0.3, topText, 3.4, style.frameFg);
    }
    if (bottomText) {
      frameSvg += textBand(totalW / 2, oy + inner + frameBottom / 2, bottomText, 3, style.frameFg);
    }
  } else {
    frameSvg = `<rect x="0" y="0" width="${totalW}" height="${totalH}" fill="${style.bg}"/>`;
  }

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${totalW} ${totalH}" ` +
    `width="${totalW * 12}" height="${totalH * 12}" shape-rendering="geometricPrecision">` +
    (defs ? `<defs>${defs}</defs>` : '') +
    frameSvg +
    `<g transform="translate(${ox},${oy})">` +
    `<path d="${d}" fill="${fill}"/>${eyes}${logoSvg}` +
    `</g></svg>`;

  return {
    svg,
    version: q.ver,
    size: n,
    logoModules,
    logoCoverage: logoModules ? (logoModules * logoModules) / (n * n) : 0,
  };
}

function textBand(cx: number, cy: number, text: string, size: number, fill: string): string {
  return (
    `<text x="${cx}" y="${cy}" font-size="${size}" font-family="${FONT_STACK}" font-weight="600" ` +
    `fill="${fill}" text-anchor="middle" dominant-baseline="central" letter-spacing="0.4">${esc(text)}</text>`
  );
}

/**
 * 把 SVG 字串轉成 PNG Blob。
 * 走 Image + canvas，不需要任何額外套件；中文字靠系統字型繪製。
 */
export function svgToPngBlob(svg: string, width = 1024, background = '#ffffff'): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = Math.round((width * img.height) / img.width);
        const ctx = canvas.getContext('2d');
        if (!ctx) throw new Error('無法建立 canvas context');
        ctx.fillStyle = background;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((out) => {
          URL.revokeObjectURL(url);
          if (out) resolve(out);
          else reject(new Error('PNG 轉檔失敗'));
        }, 'image/png');
      } catch (e) {
        URL.revokeObjectURL(url);
        reject(e);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('SVG 無法載入為圖片'));
    };
    img.src = url;
  });
}
