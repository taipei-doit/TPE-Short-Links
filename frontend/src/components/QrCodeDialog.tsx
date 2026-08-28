import { Button, Group, Modal, SegmentedControl, Stack, Switch, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useEffect, useMemo, useState } from 'react';

import { DEFAULT_PRESET_ID, QR_PRESETS, getPreset } from '../qr/presets';
import { renderQrSvg, svgToPngBlob } from '../qr/render';

const PREFS_KEY = 'tpe-shortlinks.qr-prefs';

type Prefs = {
  presetId: string;
  topText: string;
  bottomText: string;
  showLogo: boolean;
};

const DEFAULT_PREFS: Prefs = {
  presetId: DEFAULT_PRESET_ID,
  topText: '臺北市政府',
  bottomText: '掃描查看服務說明',
  showLogo: true,
};

/** 記住上次用的樣式，同一個人連續產很多張時不用每次重設。 */
function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<Prefs>;
    return {
      presetId: typeof parsed.presetId === 'string' ? parsed.presetId : DEFAULT_PREFS.presetId,
      topText: typeof parsed.topText === 'string' ? parsed.topText : DEFAULT_PREFS.topText,
      bottomText: typeof parsed.bottomText === 'string' ? parsed.bottomText : DEFAULT_PREFS.bottomText,
      showLogo: typeof parsed.showLogo === 'boolean' ? parsed.showLogo : DEFAULT_PREFS.showLogo,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface QrCodeDialogProps {
  opened: boolean;
  onClose: () => void;
  /** 短碼，用來組檔名 */
  code: string;
  /** 要編碼進 QR 的完整短網址 */
  shortUrl: string;
}

export function QrCodeDialog({ opened, onClose, code, shortUrl }: QrCodeDialogProps) {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [downloading, setDownloading] = useState(false);

  // 開啟時才讀偏好，避免 SSR / 初次渲染就碰 localStorage
  useEffect(() => {
    if (opened) setPrefs(loadPrefs());
  }, [opened]);

  useEffect(() => {
    if (!opened) return;
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch {
      // 隱私模式寫不進去就算了，不影響功能
    }
  }, [opened, prefs]);

  const rendered = useMemo(() => {
    if (!shortUrl) return null;
    try {
      return renderQrSvg({
        text: shortUrl,
        style: getPreset(prefs.presetId).style,
        topText: prefs.topText,
        bottomText: prefs.bottomText,
        showLogo: prefs.showLogo,
      });
    } catch {
      return null;
    }
  }, [shortUrl, prefs]);

  // 只給最外層 svg 加行內樣式。
  // 注意：絕對不要用 `.wrapper svg { width: 100% }` 這種後代選擇器，
  // 市徽是巢狀 <svg>，CSS 寬度會蓋掉它的 width 屬性，整個標誌會爆版。
  const previewHtml = useMemo(
    () => (rendered ? rendered.svg.replace('<svg ', '<svg style="width:100%;height:auto;display:block" ') : ''),
    [rendered],
  );

  const download = async (kind: 'png' | 'svg') => {
    if (!rendered) return;
    setDownloading(true);
    try {
      if (kind === 'svg') {
        triggerDownload(new Blob([rendered.svg], { type: 'image/svg+xml;charset=utf-8' }), `qrcode_${code}.svg`);
      } else {
        const blob = await svgToPngBlob(rendered.svg, 1024);
        triggerDownload(blob, `qrcode_${code}.png`);
      }
    } catch (e) {
      notifications.show({ color: 'red', message: e instanceof Error ? e.message : 'QR Code 下載失敗' });
    } finally {
      setDownloading(false);
    }
  };

  const preset = getPreset(prefs.presetId);

  return (
    <Modal opened={opened} onClose={onClose} title="下載 QR Code" size="lg" radius="md" centered>
      <Stack gap="md">
        <SegmentedControl
          fullWidth
          value={prefs.presetId}
          onChange={(value) => setPrefs((p) => ({ ...p, presetId: value }))}
          data={QR_PRESETS.map((p) => ({ value: p.id, label: p.label }))}
        />
        <Text size="xs" c="dimmed" mt={-8}>
          {preset.hint}
        </Text>

        <Group align="flex-start" gap="lg" wrap="nowrap">
          <div style={{ width: 220, flex: 'none' }}>
            {previewHtml ? (
              <div dangerouslySetInnerHTML={{ __html: previewHtml }} />
            ) : (
              <Text size="sm" c="dimmed">
                無法產生預覽
              </Text>
            )}
            {rendered ? (
              <Text size="xs" c="dimmed" ta="center" mt="xs">
                版本 {rendered.version}．{rendered.size}×{rendered.size} 模組
              </Text>
            ) : null}
          </div>

          <Stack gap="sm" style={{ flex: 1 }}>
            <TextInput
              label="上方文字"
              description="留空就不顯示上方色帶"
              value={prefs.topText}
              maxLength={14}
              onChange={(e) => setPrefs((p) => ({ ...p, topText: e.currentTarget.value }))}
            />
            <TextInput
              label="下方文字"
              description="留空就不顯示下方色帶"
              value={prefs.bottomText}
              maxLength={16}
              onChange={(e) => setPrefs((p) => ({ ...p, bottomText: e.currentTarget.value }))}
            />
            <Switch
              label="中央放市徽"
              checked={prefs.showLogo}
              onChange={(e) => setPrefs((p) => ({ ...p, showLogo: e.currentTarget.checked }))}
            />
            <Text size="xs" c="dimmed">
              放市徽時容錯等級會自動提高到 H，遮蔽面積約佔 6%，仍在安全範圍。
            </Text>
          </Stack>
        </Group>

        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose}>
            關閉
          </Button>
          <Button variant="light" loading={downloading} onClick={() => download('svg')}>
            下載 SVG
          </Button>
          <Button loading={downloading} onClick={() => download('png')}>
            下載 PNG
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
