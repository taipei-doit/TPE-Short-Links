import { Alert, Button, Card, Group, Loader, Stack, Text, TextInput, Title } from '@mantine/core';
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconExternalLink,
  IconFileZip,
  IconInfoCircle,
  IconSearch,
  IconShieldCheck,
} from '@tabler/icons-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { api } from '../api/client';
import { Crumbs } from '../components/Crumbs';
import { INK, SERIF_TC } from '../publicTheme';
import { EmblemStripe } from './LandingPage';

type Preview = {
  title: string | null;
  description: string | null;
  image: string | null;
  site_name: string | null;
};

const PUBLIC_BASE = 'https://url.taipei';
const TARGET_RE = /^(f\/)?[A-Za-z0-9_-]{1,32}$/;

/** 民眾可能貼整條短網址、也可能只打代碼，都收。 */
function normalizeTarget(input: string): string | null {
  let s = input.trim();
  if (/^https?:\/\//i.test(s)) {
    try {
      s = new URL(s).pathname;
    } catch {
      return null;
    }
  }
  s = s.replace(/^\/+/, '').replace(/^check\//i, '').replace(/\/+$/, '');
  return TARGET_RE.test(s) ? s : null;
}

type CheckResult = { kind: 'link' | 'file_share'; state: string; original_url: string | null };

/**
 * 查核結果標題色。Mantine 預設的 red.8／orange.8／blue.8 壓在同色淺底上只有 3～4.5:1，
 * 無障礙 AAA（GN3140600E）要求一般文字 7:1，這裡各自加深到 7.5:1 以上（對應淺底實測）。
 */
const RESULT_TITLE = {
  danger: '#7F1D1D',
  warning: '#6F3404',
  info: '#0B3A66',
  success: '#14532D',
} as const;
/** 欄位錯誤訊息：Mantine 預設紅 #E03131 對白底 4.5:1，加深到 7.4:1 */
const FIELD_ERROR_COLOR = '#A61E1E';

const cardStyle = {
  boxShadow: '0 2px 12px rgba(0, 0, 0, 0.1)',
  background: 'white',
  border: '1px solid var(--mantine-color-gray-2)',
};

export function CheckPage() {
  const params = useParams();
  const navigate = useNavigate();
  const urlTarget = params['*'] ?? '';

  const [value, setValue] = useState(urlTarget);
  const [inputError, setInputError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState<{ target: string; result: CheckResult } | null>(null);
  const [failed, setFailed] = useState(false);

  const runCheck = useCallback(async (target: string) => {
    setChecking(true);
    setFailed(false);
    setChecked(null);
    try {
      const result = await api.checkTarget(target);
      setChecked({ target, result });
    } catch {
      setFailed(true);
    } finally {
      setChecking(false);
    }
  }, []);

  // 帶著代碼進來（url.taipei/check/AAAA）就直接查
  useEffect(() => {
    if (TARGET_RE.test(urlTarget)) {
      setValue(urlTarget);
      runCheck(urlTarget);
    }
  }, [urlTarget, runCheck]);

  const submit = () => {
    if (checking) return;
    const t = normalizeTarget(value);
    if (!t) {
      // 檢核 GN2330300E：錯誤時除了文字說明，鍵盤焦點也要導回出錯欄位
      setInputError('必填欄位未填寫或格式不正確：請輸入短網址代碼，或貼上完整的 url.taipei 短網址');
      inputRef.current?.focus();
      return;
    }
    // 讓網址列同步，查核結果可以直接複製網址轉傳
    // keepFocus：這只是同步網址列、不算換頁，App 不要把焦點拉回頁首
    navigate(`/check/${t}`, { replace: true, state: { keepFocus: true } });
    runCheck(t);
  };

  return (
    <Stack gap="xl" style={{ maxWidth: '40em', margin: '0 auto' }}>
      <Crumbs current="短網址查核" />
      <Stack gap="sm">
        <Group gap="sm" align="center">
          <IconShieldCheck size={30} color={INK} />
          <Title
            order={1}
            style={{
              margin: 0,
              fontFamily: SERIF_TC,
              color: INK,
              fontWeight: 700,
              letterSpacing: 2,
            }}
          >
            短網址查核
          </Title>
        </Group>
        <EmblemStripe width={168} />
        <Text c="dark.6" size="sm" style={{ lineHeight: 1.9 }}>
          url.taipei 是臺北市政府的官方短網址服務。在這裡輸入您收到的短網址，
          即可在開啟前確認它將前往哪個網站。本頁的官方網址是{' '}
          <Text span fw={600}>
            {PUBLIC_BASE}/check
          </Text>
          。
        </Text>
      </Stack>

      <Card withBorder padding="xl" radius="md" style={cardStyle}>
        <Stack gap="md">
          <TextInput
            ref={inputRef}
            label="短網址或代碼（必填）"
            autoComplete="off"
            placeholder="例如 https://url.taipei/AAAA 或 AAAA"
            value={value}
            error={inputError}
            styles={{ error: { color: FIELD_ERROR_COLOR } }}
            size="md"
            radius="md"
            onChange={(e) => {
              setValue(e.currentTarget.value);
              setInputError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
          />
          <Group justify="flex-end">
            {/* 不用 loading 屬性：它會停用按鈕，鍵盤焦點會掉回 body、查完得從頁首重新 Tab。
                改為查核中維持可聚焦，重複送出由 submit 開頭的 checking 判斷擋下。 */}
            <Button
              leftSection={checking ? <Loader size={16} color="white" /> : <IconSearch size={18} />}
              aria-busy={checking}
              onClick={submit}
              size="md"
              radius="md"
            >
              查核
            </Button>
          </Group>
        </Stack>
      </Card>

      {/* 查核結果是動態插入的內容：包在常駐的 role=status 區塊裡，報讀軟體才會主動唸出結果（AR2410300E） */}
      <Stack gap="xl" role="status" aria-live="polite">
        {checking && (
          <Group justify="center">
            <Loader size="sm" aria-label="查核中" />
          </Group>
        )}

        {failed && (
          <Alert color="red" icon={<IconAlertTriangle size={18} />}>
            查詢失敗，請稍後再試。
          </Alert>
        )}

        {checked && <ResultCard target={checked.target} result={checked.result} />}
      </Stack>
    </Stack>
  );
}

function ResultCard({ target, result }: { target: string; result: CheckResult }) {
  const shortUrl = `${PUBLIC_BASE}/${target}`;
  const isActiveLink = result.kind === 'link' && result.state === 'active';

  // 卡片是加分項：查核結果先出，卡片抓得到再補上，抓不到就安靜略過。
  const [preview, setPreview] = useState<Preview | null>(null);
  useEffect(() => {
    setPreview(null);
    if (!isActiveLink) return;
    let alive = true;
    api
      .getCheckPreview(target)
      .then((p) => {
        if (alive) setPreview(p);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [target, isActiveLink]);

  if (result.state === 'not_found') {
    return (
      <Alert
        color="red"
        icon={<IconAlertTriangle size={18} />}
        title="查無此短網址"
        styles={{ title: { color: RESULT_TITLE.danger } }}
      >
        <Text size="sm">
          臺北市政府從未發出過 <Text span fw={600}>{shortUrl}</Text>{' '}
          這個短網址。若您在簡訊或文宣上看到它，請提高警覺，切勿點擊或掃描。
        </Text>
      </Alert>
    );
  }

  if (result.state === 'disabled' || result.state === 'expired') {
    return (
      <Alert
        color="orange"
        icon={<IconInfoCircle size={18} />}
        title={result.state === 'disabled' ? '此短網址已停用' : '此短網址已過期'}
        styles={{ title: { color: RESULT_TITLE.warning } }}
      >
        <Text size="sm">
          <Text span fw={600}>{shortUrl}</Text>{' '}
          曾是本府發出的短網址，但目前已失效，點擊後只會看到官方說明頁，不會轉向任何網站。
        </Text>
      </Alert>
    );
  }

  if (result.kind === 'file_share') {
    return (
      <Alert
        color="blue"
        icon={<IconFileZip size={18} />}
        title="這是本府的檔案分享連結"
        styles={{ title: { color: RESULT_TITLE.info } }}
      >
        <Text size="sm">
          <Text span fw={600}>{shortUrl}</Text>{' '}
          是臺北市政府的檔案分享頁，開啟後需輸入承辦提供的 PIN
          碼才能下載檔案，不會轉向其他網站。
        </Text>
      </Alert>
    );
  }

  return (
    <Card withBorder padding="xl" radius="md" style={cardStyle}>
      <Stack gap="sm">
        <Group gap="xs">
          <IconCircleCheck size={24} color="var(--mantine-color-green-7)" />
          <Text fw={700} size="lg" style={{ color: RESULT_TITLE.success }}>
            這是臺北市政府的有效短網址
          </Text>
        </Group>
        <Text size="sm" c="dimmed">
          {shortUrl} 點擊或掃描後將轉向：
        </Text>
        <Text
          fw={600}
          style={{
            wordBreak: 'break-all',
            background: 'var(--mantine-color-gray-1)',
            padding: '12px 16px',
            borderRadius: 'var(--mantine-radius-sm)',
          }}
        >
          {result.original_url}
        </Text>
        {preview && (
          <Card
            component="a"
            href={shortUrl}
            target="_blank"
            rel="noopener"
            title="[另開新視窗]前往目標網站"
            withBorder
            radius="md"
            padding={0}
            style={{ overflow: 'hidden', cursor: 'pointer' }}
          >
            {preview.image && (
              <img
                src={preview.image}
                alt={preview.title ? `目標網站「${preview.title}」的代表圖片` : '目標網站的代表圖片'}
                style={{ width: '100%', maxHeight: 220, objectFit: 'cover', display: 'block' }}
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                }}
              />
            )}
            <Stack gap={4} p="md">
              {preview.site_name && (
                <Text size="xs" c="dimmed">
                  {preview.site_name}
                </Text>
              )}
              {preview.title && (
                <Text fw={600} size="sm">
                  {preview.title}
                </Text>
              )}
              {preview.description && (
                <Text size="sm" c="dimmed" lineClamp={2}>
                  {preview.description}
                </Text>
              )}
              <Text size="xs" c="dimmed" mt={4}>
                目標網站預覽，擷取自該網站的公開資訊
              </Text>
            </Stack>
          </Card>
        )}
        <Group justify="flex-end">
          <Button
            component="a"
            href={shortUrl}
            target="_blank"
            rel="noopener"
            title="[另開新視窗]前往目標網站"
            leftSection={<IconExternalLink size={18} />}
            size="md"
            radius="md"
          >
            確認無誤，前往目標網站
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          提醒：請確認上方目標網域是否為您預期的網站；本查詢頁僅適用於 url.taipei
          的短網址，無法查核其他服務產生的連結。
        </Text>
      </Stack>
    </Card>
  );
}
