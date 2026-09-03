import {
  Alert,
  Button,
  Card,
  ColorInput,
  FileInput,
  Group,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconAlertTriangle, IconDownload, IconInfoCircle, IconQrcode } from '@tabler/icons-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { notifications } from '@mantine/notifications';

import { api } from '../api/client';
import { DEFAULT_PRESET_ID, QR_PRESETS, getPreset } from '../qr/presets';
import { renderQrSvg, svgToPngBlob, type Ecl, type QrStyle } from '../qr/render';

/** 只服務自家網域的連結，這個頁面刻意不能為任意網址產 QR。 */
const PUBLIC_BASE = 'https://url.taipei';

/** 短網址代碼，或檔案分享的 f/代碼。 */
const TARGET_RE = /^(f\/)?[A-Za-z0-9_-]{1,32}$/;

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

/** 對白底的最低對比。低於這個值很多掃描器會讀不到，直接擋下載。 */
const MIN_CONTRAST = 4;

function parseHex(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.exec(hex.trim());
  if (!m) return null;
  let h = m[1];
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function luminance(hex: string): number | null {
  const rgb = parseHex(hex);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(a: string, b: string): number | null {
  const la = luminance(a);
  const lb = luminance(b);
  if (la === null || lb === null) return null;
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
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

/** 把使用者貼進來的東西（代碼或完整網址）整理成合法的目標路徑。 */
function normalizeTarget(input: string): string | null {
  let s = input.trim();
  if (/^https?:\/\//i.test(s)) {
    try {
      s = new URL(s).pathname;
    } catch {
      return null;
    }
  }
  s = s.replace(/^\/+/, '').replace(/^qr\//i, '');
  return TARGET_RE.test(s) ? s : null;
}

const cardStyle = {
  boxShadow: '0 2px 12px rgba(0, 0, 0, 0.1)',
  background: 'white',
  border: '1px solid var(--mantine-color-gray-2)',
};

export function QrStudioPage() {
  const params = useParams();
  const target = params['*'] ?? '';
  if (!TARGET_RE.test(target)) {
    return <StudioLanding hadInvalidTarget={target !== ''} />;
  }
  return <StudioEditor target={target} />;
}

function StudioLanding({ hadInvalidTarget }: { hadInvalidTarget: boolean }) {
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(
    hadInvalidTarget ? '網址中的代碼格式不正確，請重新輸入' : null,
  );

  const go = () => {
    const t = normalizeTarget(value);
    if (!t) {
      setError('請輸入短網址代碼，或貼上完整的 url.taipei 短網址');
      return;
    }
    navigate(`/qr/${t}`);
  };

  return (
    <Stack gap="xl">
      <div>
        <Title order={1} style={{ marginBottom: '8px', fontWeight: 700 }}>
          QR Code 產生器
        </Title>
        <Text c="dimmed" size="sm">
          為 url.taipei 短網址產生樣式化的 QR Code。圖檔完全在您的瀏覽器產生，不會上傳任何資料。
        </Text>
      </div>
      <Card withBorder padding="xl" radius="md" style={cardStyle}>
        <Stack gap="md">
          <TextInput
            label="短網址代碼"
            description="輸入代碼（例如 AAAA），或直接貼上完整短網址（例如 https://url.taipei/AAAA）"
            placeholder="AAAA"
            value={value}
            error={error}
            size="md"
            radius="md"
            onChange={(e) => {
              setValue(e.currentTarget.value);
              setError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') go();
            }}
          />
          <Group justify="flex-end">
            <Button leftSection={<IconQrcode size={18} />} onClick={go} size="md" radius="md">
              產生 QR Code
            </Button>
          </Group>
        </Stack>
      </Card>
    </Stack>
  );
}

type LogoMode = 'none' | 'taipei' | 'custom';

type LinkState = 'active' | 'disabled' | 'expired' | 'not_found' | 'unknown';

const LINK_STATE_WARNINGS: Partial<Record<LinkState, string>> = {
  not_found: '查無此代碼：這個短網址目前不存在，掃描只會看到 404 頁。請先確認代碼拼字，或先到管理介面建立短網址。',
  expired: '這個短網址已過期，掃描目前會導向 404 頁。QR 圖不會變，延長效期後即可繼續使用；若是要補印既有文宣可放心下載。',
  disabled: '這個短網址目前是停用狀態，掃描會導向 404 頁。QR 圖不會變，重新啟用後即可繼續使用。',
};

function StudioEditor({ target }: { target: string }) {
  const targetUrl = `${PUBLIC_BASE}/${target}`;
  const isFileShare = target.startsWith('f/');

  // 只提醒、不阻擋：過期或停用的連結可能要補印文宣，仍允許下載。
  const [linkState, setLinkState] = useState<LinkState>('unknown');
  useEffect(() => {
    let alive = true;
    setLinkState('unknown');
    api
      .getQrStatus(target)
      .then((r) => {
        if (!alive) return;
        const s = r.state;
        setLinkState(
          s === 'active' || s === 'disabled' || s === 'expired' || s === 'not_found' ? s : 'unknown',
        );
      })
      .catch(() => {
        // 查不到狀態（離線、舊版後端）就不顯示提醒
      });
    return () => {
      alive = false;
    };
  }, [target]);

  const [presetId, setPresetId] = useState<string>(DEFAULT_PRESET_ID);
  const [customStyle, setCustomStyle] = useState<QrStyle>({ ...getPreset(DEFAULT_PRESET_ID).style });
  const [topText, setTopText] = useState('臺北市政府');
  const [bottomText, setBottomText] = useState(isFileShare ? '掃描下載檔案' : '掃描查看服務說明');
  const [logoMode, setLogoMode] = useState<LogoMode>('taipei');
  const [logoImage, setLogoImage] = useState<string | null>(null);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [ecl, setEcl] = useState<Ecl>('H');
  const [downloading, setDownloading] = useState(false);

  const isCustom = presetId === 'custom';
  const style: QrStyle = isCustom ? customStyle : getPreset(presetId).style;
  const hasLogo = logoMode === 'taipei' || (logoMode === 'custom' && logoImage !== null);

  const patch = (p: Partial<QrStyle>) => setCustomStyle((s) => ({ ...s, ...p }));

  // 自訂模式下色帶文字自動取用可讀的顏色，不用多一個設定。
  const effStyle: QrStyle = useMemo(() => {
    if (!isCustom) return style;
    const lum = luminance(style.frameBg);
    return { ...style, frameFg: lum !== null && lum > 0.4 ? '#1A1A1A' : '#FFFFFF' };
  }, [isCustom, style]);

  // 前景（含漸層兩端與定位點色）對白底的最差對比。
  const contrast = useMemo(() => {
    const colors = [effStyle.fg1];
    if (effStyle.colorMode !== 'solid') colors.push(effStyle.fg2);
    if (effStyle.eyeColor) colors.push(effStyle.eyeColor);
    let worst: number | null = null;
    let inverted = false;
    const bgLum = luminance(effStyle.bg) ?? 1;
    for (const c of colors) {
      const r = contrastRatio(c, effStyle.bg);
      if (r === null) return { worst: null, inverted: false };
      if (worst === null || r < worst) worst = r;
      const l = luminance(c);
      if (l !== null && l > bgLum) inverted = true;
    }
    return { worst, inverted };
  }, [effStyle]);

  const contrastOk = !contrast.inverted && contrast.worst !== null && contrast.worst >= MIN_CONTRAST;

  const rendered = useMemo(() => {
    try {
      return renderQrSvg({
        text: targetUrl,
        style: effStyle,
        topText,
        bottomText,
        showLogo: logoMode === 'taipei',
        logoImage: logoMode === 'custom' && logoImage ? logoImage : undefined,
        ecl,
      });
    } catch {
      return null;
    }
  }, [targetUrl, effStyle, topText, bottomText, logoMode, logoImage, ecl]);

  // 只給最外層 svg 加行內樣式；市徽是巢狀 <svg>，用後代選擇器會把它撐爆。
  const previewHtml = useMemo(
    () =>
      rendered ? rendered.svg.replace('<svg ', '<svg style="width:100%;height:auto;display:block" ') : '',
    [rendered],
  );

  const onLogoFile = (file: File | null) => {
    setLogoFile(file);
    if (!file) {
      setLogoImage(null);
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      notifications.show({ color: 'red', message: '圖檔請小於 2MB' });
      setLogoFile(null);
      setLogoImage(null);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setLogoImage(typeof reader.result === 'string' ? reader.result : null);
    reader.onerror = () => notifications.show({ color: 'red', message: '圖檔讀取失敗' });
    reader.readAsDataURL(file);
  };

  const download = async (kind: 'png' | 'svg') => {
    if (!rendered || !contrastOk) return;
    setDownloading(true);
    const name = `qrcode_${target.replace('/', '_')}`;
    try {
      if (kind === 'svg') {
        triggerDownload(new Blob([rendered.svg], { type: 'image/svg+xml;charset=utf-8' }), `${name}.svg`);
      } else {
        const blob = await svgToPngBlob(rendered.svg, 1024);
        triggerDownload(blob, `${name}.png`);
      }
    } catch (e) {
      notifications.show({ color: 'red', message: e instanceof Error ? e.message : 'QR Code 下載失敗' });
    } finally {
      setDownloading(false);
    }
  };

  const eyeNotSquare = effStyle.eyeFrame === 'rounded' || effStyle.eyeFrame === 'circle';

  return (
    <Stack gap="xl">
      <div>
        <Title order={1} style={{ marginBottom: '8px', fontWeight: 700 }}>
          QR Code 產生器
        </Title>
        <Text c="dimmed" size="sm">
          此 QR Code 掃描後將前往{isFileShare ? '檔案分享頁' : '短網址'}{' '}
          <Text span fw={600} c="blue">
            {targetUrl}
          </Text>
          ；圖檔完全在您的瀏覽器產生，不會上傳任何資料。
        </Text>
      </div>

      {LINK_STATE_WARNINGS[linkState] && (
        <Alert color="yellow" icon={<IconAlertTriangle size={18} />} title="連結狀態提醒">
          {LINK_STATE_WARNINGS[linkState]}
        </Alert>
      )}

      <Card withBorder padding="xl" radius="md" style={cardStyle}>
        <Stack gap="md">
          <SegmentedControl
            fullWidth
            value={presetId}
            onChange={(value) => {
              if (value === 'custom' && presetId !== 'custom') {
                // 從目前的樣式出發改，不要跳回預設值
                setCustomStyle({ ...style });
              }
              setPresetId(value);
            }}
            data={[...QR_PRESETS.map((p) => ({ value: p.id, label: p.label })), { value: 'custom', label: '自訂' }]}
          />
          {!isCustom && (
            <Text size="xs" c="dimmed" mt={-8}>
              {getPreset(presetId).hint}
            </Text>
          )}

          <Group align="flex-start" gap="xl" wrap="wrap">
            <div style={{ width: 280, flex: 'none' }}>
              {previewHtml ? (
                <div dangerouslySetInnerHTML={{ __html: previewHtml }} />
              ) : (
                <Text size="sm" c="dimmed">
                  無法產生預覽
                </Text>
              )}
              {rendered ? (
                <Text size="xs" c="dimmed" ta="center" mt="xs">
                  版本 {rendered.version}．{rendered.size}×{rendered.size} 模組．容錯 {hasLogo ? 'H' : ecl}
                </Text>
              ) : null}
            </div>

            <Stack gap="sm" style={{ flex: 1, minWidth: 280 }}>
              <TextInput
                label="上方文字"
                description="留空就不顯示上方色帶"
                value={topText}
                maxLength={14}
                onChange={(e) => setTopText(e.currentTarget.value)}
              />
              <TextInput
                label="下方文字"
                description="留空就不顯示下方色帶"
                value={bottomText}
                maxLength={16}
                onChange={(e) => setBottomText(e.currentTarget.value)}
              />

              <Select
                label="中央圖示"
                value={logoMode}
                onChange={(v) => setLogoMode((v as LogoMode) ?? 'none')}
                data={[
                  { value: 'none', label: '不放圖示' },
                  { value: 'taipei', label: '臺北市市徽' },
                  { value: 'custom', label: '自訂圖片（機關徽章、活動標誌）' },
                ]}
              />
              {logoMode === 'custom' && (
                <FileInput
                  label="上傳圖示"
                  description="建議使用正方形、背景透明的 PNG 或 SVG；圖片只在瀏覽器處理，不會上傳"
                  placeholder="選擇圖檔"
                  accept="image/png,image/jpeg,image/svg+xml"
                  value={logoFile}
                  onChange={onLogoFile}
                  clearable
                />
              )}
              {hasLogo ? (
                <Text size="xs" c="dimmed">
                  放圖示時容錯等級固定為 H，圖示大小已限制在安全遮蔽範圍內。
                </Text>
              ) : (
                <SegmentedControl
                  value={ecl}
                  onChange={(v) => setEcl(v as Ecl)}
                  data={[
                    { value: 'L', label: '容錯 L（7%）' },
                    { value: 'M', label: 'M（15%）' },
                    { value: 'Q', label: 'Q（25%）' },
                    { value: 'H', label: 'H（30%）' },
                  ]}
                />
              )}

              {isCustom && (
                <>
                  <Group grow>
                    <Select
                      label="模組形狀"
                      value={style.moduleShape}
                      onChange={(v) => patch({ moduleShape: (v as QrStyle['moduleShape']) ?? 'square' })}
                      data={[
                        { value: 'square', label: '方塊' },
                        { value: 'rounded', label: '圓角' },
                        { value: 'dot', label: '圓點' },
                        { value: 'diamond', label: '菱形' },
                        { value: 'liquid', label: '連續' },
                      ]}
                    />
                    <Select
                      label="定位點外框"
                      value={style.eyeFrame}
                      onChange={(v) => patch({ eyeFrame: (v as QrStyle['eyeFrame']) ?? 'square' })}
                      data={[
                        { value: 'square', label: '方形' },
                        { value: 'rounded', label: '圓角' },
                        { value: 'circle', label: '圓形' },
                        { value: 'leaf', label: '葉形' },
                      ]}
                    />
                    <Select
                      label="定位點內點"
                      value={style.eyeBall}
                      onChange={(v) => patch({ eyeBall: (v as QrStyle['eyeBall']) ?? 'square' })}
                      data={[
                        { value: 'square', label: '方形' },
                        { value: 'rounded', label: '圓角' },
                        { value: 'circle', label: '圓形' },
                        { value: 'leaf', label: '葉形' },
                        { value: 'azalea', label: '杜鵑花' },
                      ]}
                    />
                  </Group>
                  <SegmentedControl
                    value={style.colorMode}
                    onChange={(v) => patch({ colorMode: v as QrStyle['colorMode'] })}
                    data={[
                      { value: 'solid', label: '單色' },
                      { value: 'linear', label: '線性漸層' },
                      { value: 'radial', label: '放射漸層' },
                    ]}
                  />
                  <Group grow>
                    <ColorInput
                      label={style.colorMode === 'solid' ? '前景色' : '漸層起點'}
                      format="hex"
                      value={style.fg1}
                      onChange={(v) => patch({ fg1: v })}
                    />
                    {style.colorMode !== 'solid' && (
                      <ColorInput
                        label="漸層終點"
                        format="hex"
                        value={style.fg2}
                        onChange={(v) => patch({ fg2: v })}
                      />
                    )}
                    <ColorInput
                      label="色帶底色"
                      format="hex"
                      value={style.frameBg}
                      onChange={(v) => patch({ frameBg: v })}
                    />
                  </Group>
                  <Switch
                    label="定位點另用一色"
                    checked={!!style.eyeColor}
                    onChange={(e) => patch({ eyeColor: e.currentTarget.checked ? style.fg1 : undefined })}
                  />
                  {style.eyeColor && (
                    <ColorInput
                      label="定位點顏色"
                      format="hex"
                      value={style.eyeColor}
                      onChange={(v) => patch({ eyeColor: v })}
                    />
                  )}
                </>
              )}
            </Stack>
          </Group>

          {!contrastOk && (
            <Alert color="red" icon={<IconAlertTriangle size={18} />} title="這個配色掃不出來">
              {contrast.inverted
                ? '前景色比底色淺（反白 QR），很多掃描器無法讀取，請改用比白色深的前景色。'
                : `前景色對白底的對比只有 ${contrast.worst?.toFixed(1) ?? '?'}:1，未達安全值 ${MIN_CONTRAST}:1，請加深顏色。`}
            </Alert>
          )}
          {contrastOk && eyeNotSquare && (
            <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
              圓角、圓形定位點適合海報與文宣，手機相機掃描沒有問題；若要給票證、門禁、倉儲等機器讀取，請改用方形或葉形定位點（或直接選「方正經典」樣式）。
            </Alert>
          )}

          <Group justify="flex-end" gap="sm">
            <Button
              variant="light"
              leftSection={<IconDownload size={18} />}
              loading={downloading}
              disabled={!rendered || !contrastOk}
              onClick={() => download('svg')}
              size="md"
              radius="md"
            >
              下載 SVG（印刷用）
            </Button>
            <Button
              leftSection={<IconDownload size={18} />}
              loading={downloading}
              disabled={!rendered || !contrastOk}
              onClick={() => download('png')}
              size="md"
              radius="md"
            >
              下載 PNG
            </Button>
          </Group>

          <Text size="xs" c="dimmed">
            下載後請務必先用手機相機實際掃描一次，確認導向 {targetUrl} 再送印。
          </Text>
        </Stack>
      </Card>
    </Stack>
  );
}
