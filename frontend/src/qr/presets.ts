/**
 * QR Code 樣式預設。
 *
 * 這三組的形狀與配色都已用解碼器實測通過。新增樣式前請先確認：
 * 1. 前景與底色的對比至少 4:1，前景必須比底色深（反白的 QR 很多掃描器讀不到）。
 * 2. 定位點外框改成非方形時，手機相機沒問題，但工業型讀取器可能失敗，
 *    票證、門禁類用途請用方形。
 */

import type { QrStyle } from './render';

export interface QrPreset {
  id: string;
  label: string;
  /** 這個樣式適合什麼場合，顯示在選項下方 */
  hint: string;
  style: QrStyle;
}

export const QR_PRESETS: QrPreset[] = [
  {
    id: 'campaign',
    label: '活動宣傳',
    hint: '深藍放射漸層，沉穩，適合海報與公告',
    style: {
      moduleShape: 'rounded',
      eyeFrame: 'rounded',
      eyeBall: 'rounded',
      colorMode: 'radial',
      fg1: '#0B2130',
      fg2: '#0F5C86',
      bg: '#FFFFFF',
      frameBg: '#0B2130',
      frameFg: '#FFFFFF',
    },
  },
  {
    id: 'friendly',
    label: '圓潤親民',
    hint: '圓點模組配藍綠漸層，適合便民服務與市民活動',
    style: {
      moduleShape: 'dot',
      eyeFrame: 'circle',
      eyeBall: 'circle',
      colorMode: 'linear',
      fg1: '#0F5C86',
      fg2: '#10645C',
      bg: '#FFFFFF',
      frameBg: '#0F5C86',
      frameFg: '#FFFFFF',
    },
  },
  {
    id: 'azalea',
    label: '杜鵑',
    hint: '取市花杜鵑的洋紅漸層，定位點內點是五瓣花，辨識度最高',
    style: {
      moduleShape: 'liquid',
      eyeFrame: 'leaf',
      eyeBall: 'azalea',
      colorMode: 'linear',
      fg1: '#C23A70',
      fg2: '#7C3193',
      bg: '#FFFFFF',
      eyeColor: '#5B2470',
      frameBg: '#5B2470',
      frameFg: '#FFFFFF',
    },
  },
  {
    id: 'classic',
    label: '方正經典',
    hint: '單色方形定位點，相容性最高；票證、門禁等機器讀取用途請選這組',
    style: {
      moduleShape: 'square',
      eyeFrame: 'square',
      eyeBall: 'square',
      colorMode: 'solid',
      fg1: '#0B2130',
      fg2: '#0B2130',
      bg: '#FFFFFF',
      frameBg: '#0B2130',
      frameFg: '#FFFFFF',
    },
  },
];

export const DEFAULT_PRESET_ID = 'campaign';

export function getPreset(id: string): QrPreset {
  return QR_PRESETS.find((p) => p.id === id) ?? QR_PRESETS[0];
}
