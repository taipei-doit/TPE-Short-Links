import { Alert, Button, Card, Group, Loader, Stack, Text, TextInput, Title } from '@mantine/core';
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconFileZip,
  IconInfoCircle,
  IconSearch,
  IconShieldCheck,
} from '@tabler/icons-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { api } from '../api/client';

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
    const t = normalizeTarget(value);
    if (!t) {
      setInputError('請輸入短網址代碼，或貼上完整的 url.taipei 短網址');
      return;
    }
    // 讓網址列同步，查核結果可以直接複製網址轉傳
    navigate(`/check/${t}`, { replace: true });
    runCheck(t);
  };

  return (
    <Stack gap="xl" style={{ maxWidth: 760, margin: '0 auto' }}>
      <div>
        <Group gap="xs" mb={8}>
          <IconShieldCheck size={30} color="var(--mantine-color-blue-7)" />
          <Title order={1} style={{ margin: 0, fontWeight: 700 }}>
            短網址查核
          </Title>
        </Group>
        <Text c="dimmed" size="sm">
          url.taipei 是臺北市政府的官方短網址服務。在這裡輸入您收到的短網址，
          即可在點擊前確認它將轉向哪個網站。本頁的官方網址是{' '}
          <Text span fw={600}>
            {PUBLIC_BASE}/check
          </Text>
          。
        </Text>
      </div>

      <Card withBorder padding="xl" radius="md" style={cardStyle}>
        <Stack gap="md">
          <TextInput
            label="短網址或代碼"
            placeholder="例如 https://url.taipei/AAAA 或 AAAA"
            value={value}
            error={inputError}
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
            <Button
              leftSection={<IconSearch size={18} />}
              loading={checking}
              onClick={submit}
              size="md"
              radius="md"
            >
              查核
            </Button>
          </Group>
        </Stack>
      </Card>

      {checking && (
        <Group justify="center">
          <Loader size="sm" />
        </Group>
      )}

      {failed && (
        <Alert color="red" icon={<IconAlertTriangle size={18} />}>
          查詢失敗，請稍後再試。
        </Alert>
      )}

      {checked && <ResultCard target={checked.target} result={checked.result} />}
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
      <Alert color="red" icon={<IconAlertTriangle size={18} />} title="查無此短網址">
        <Text size="sm">
          臺北市政府從未發出過 <Text span fw={600}>{shortUrl}</Text>{' '}
          這個短網址。若您在簡訊或文宣上看到它，請提高警覺，切勿點擊或掃描。
        </Text>
      </Alert>
    );
  }

  if (result.state === 'disabled' || result.state === 'expired') {
    return (
      <Alert color="orange" icon={<IconInfoCircle size={18} />} title={result.state === 'disabled' ? '此短網址已停用' : '此短網址已過期'}>
        <Text size="sm">
          <Text span fw={600}>{shortUrl}</Text>{' '}
          曾是本府發出的短網址，但目前已失效，點擊後只會看到官方說明頁，不會轉向任何網站。
        </Text>
      </Alert>
    );
  }

  if (result.kind === 'file_share') {
    return (
      <Alert color="blue" icon={<IconFileZip size={18} />} title="這是本府的檔案分享連結">
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
          <Text fw={700} size="lg" c="green.8">
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
          <Card withBorder radius="md" padding={0} style={{ overflow: 'hidden' }}>
            {preview.image && (
              <img
                src={preview.image}
                alt=""
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
        <Text size="xs" c="dimmed">
          提醒：請確認上方目標網域是否為您預期的網站；本查詢頁僅適用於 url.taipei
          的短網址，無法查核其他服務產生的連結。
        </Text>
      </Stack>
    </Card>
  );
}
