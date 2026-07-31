import { Button, Card, Checkbox, CopyButton, Group, Select, Stack, Text, TextInput, Textarea, Title } from '@mantine/core';
import { IconQrcode } from '@tabler/icons-react';
import { DateTimePicker } from '@mantine/dates';
import '@mantine/dates/styles.css';
import { notifications } from '@mantine/notifications';
import { modals } from '@mantine/modals';
import dayjs from 'dayjs';
import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';
import type { CreateLinkIn, Link, Tag } from '../api/types';

type ExpiryMode = 'permanent' | 'datetime';

export function CreatePage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(false);

  const [originalUrl, setOriginalUrl] = useState('');
  const [tagId, setTagId] = useState<string | null>(null);
  const [tagTouched, setTagTouched] = useState(false);
  const [expiryMode, setExpiryMode] = useState<ExpiryMode>('permanent');
  const [expiresAt, setExpiresAt] = useState<Date | null>(null);
  const [note, setNote] = useState('');
  const [manualCode, setManualCode] = useState('');
  const [useManualCode, setUseManualCode] = useState(false);

  const [result, setResult] = useState<Link | null>(null);

  useEffect(() => {
    api
      .getTags()
      .then(setTags)
      .catch((e) => notifications.show({ color: 'red', message: e.message }));
  }, []);

  const tagOptions = useMemo(
    () => tags.map((t) => ({ value: String(t.id), label: t.name })),
    [tags],
  );

  const originalUrlError = useMemo(() => {
    if (!originalUrl.trim()) return '請輸入原始網址';
    try {
      const u = new URL(originalUrl.trim());
      if (u.protocol !== 'https:') return '必須為 https:// 開頭（預設不允許 http://）';
      return null;
    } catch {
      return '必須為有效的完整網址';
    }
  }, [originalUrl]);

  const expiryError = useMemo(() => {
    if (expiryMode === 'permanent') return null;
    if (!expiresAt) return '請選擇到期日期／時間';
    if (dayjs(expiresAt).isBefore(dayjs())) return '到期時間必須晚於現在';
    return null;
  }, [expiryMode, expiresAt]);

  const canSubmit = !originalUrlError && !!tagId && !expiryError && !loading;

  async function onSubmit() {
    setTagTouched(true);
    setLoading(true);
    setResult(null);
    try {
      const payload: CreateLinkIn = {
        original_url: originalUrl.trim(),
        tag_id: Number(tagId),
        expires_at: expiryMode === 'permanent' ? null : dayjs(expiresAt!).toISOString(),
        note: note.trim() ? note.trim() : null,
        code: useManualCode && manualCode.trim() ? manualCode.trim() : null,
      };
      const created = await api.createLink(payload);
      setResult(created);
      notifications.show({ color: 'green', message: '短網址建立成功' });
    } catch (e) {
      const msg = e instanceof Error ? e.message : '建立失敗';

      if (msg.startsWith('A short link already exists for this URL:')) {
        const existingUrl = msg.replace('A short link already exists for this URL:', '').trim();
        modals.open({
          title: '短網址已存在',
          children: (
            <Stack gap="xs">
              <Text size="sm">
                這個網址已經有使用中的短網址，建議直接沿用現有短網址，不需重複建立。
              </Text>
              <Text
                size="sm"
                fw={600}
                style={{ wordBreak: 'break-all', fontFamily: 'monospace' }}
                component="a"
                href={existingUrl}
                target="_blank"
                rel="noreferrer"
              >
                {existingUrl}
              </Text>
            </Stack>
          ),
        });
      } else {
        notifications.show({ color: 'red', message: msg });
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <Stack gap="xl">
      <div>
        <Title order={1} style={{ marginBottom: '8px', fontWeight: 700 }}>
          建立短網址
        </Title>
        <Text c="dimmed" size="sm">
          為您的網址產生簡短好記的短網址
        </Text>
      </div>

      <Card
        withBorder
        padding="xl"
        radius="md"
        style={{
          boxShadow: '0 2px 12px rgba(0, 0, 0, 0.1)',
          background: 'white',
          border: '1px solid var(--mantine-color-gray-2)',
        }}
      >
        <Stack gap="lg">
          <TextInput
            label="原始網址"
            placeholder="https://example.com/some/path?x=y"
            value={originalUrl}
            onChange={(e) => setOriginalUrl(e.currentTarget.value)}
            error={originalUrl ? originalUrlError : null}
            size="md"
            radius="md"
          />

          <Checkbox
            label="使用自訂代碼（手動輸入）"
            checked={useManualCode}
            onChange={(e) => setUseManualCode(e.currentTarget.checked)}
          />

          {useManualCode ? (
            <TextInput
              label="自訂代碼"
              placeholder="請輸入自訂代碼（1–32 個字元）"
              value={manualCode}
              onChange={(e) => setManualCode(e.currentTarget.value.slice(0, 32))}
              maxLength={32}
              size="md"
              radius="md"
              description="自訂代碼（1–32 個字元，可使用中文、英文字母與數字），不可與現有代碼重複，也不可使用系統保留字（如 api、docs）。"
            />
          ) : null}

          <Group grow align="flex-start">
            <Select
              label="標籤"
              placeholder="請選擇標籤"
              data={tagOptions}
              value={tagId}
              onChange={(value) => {
                setTagTouched(true);
                setTagId(value);
              }}
              searchable
              nothingFoundMessage="查無符合的標籤"
              maxDropdownHeight={320}
              error={tagTouched && !tagId ? '請選擇標籤' : null}
              size="md"
              radius="md"
            />
            <Select
              label="有效期限"
              data={[
                { value: 'permanent', label: '永久有效' },
                { value: 'datetime', label: '指定日期／時間' },
              ]}
              value={expiryMode}
              onChange={(v) => setExpiryMode((v as ExpiryMode) ?? 'permanent')}
              size="md"
              radius="md"
            />
          </Group>

          {expiryMode === 'datetime' ? (
            <DateTimePicker
              label="到期時間"
              value={expiresAt}
              onChange={setExpiresAt}
              error={expiryError}
              minDate={new Date()}
              size="md"
              radius="md"
            />
          ) : null}

          <Textarea
            label="備註"
            placeholder="選填，可記錄這個短網址的用途"
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
            autosize
            minRows={2}
            maxRows={6}
            size="md"
            radius="md"
          />

          <Group justify="flex-start" mt="md">
            <Button
              loading={loading}
              disabled={!canSubmit}
              onClick={onSubmit}
              size="lg"
              radius="md"
              style={{
                background: 'linear-gradient(135deg, var(--mantine-color-blue-6) 0%, var(--mantine-color-blue-7) 100%)',
                fontWeight: 600,
              }}
            >
              建立短網址
            </Button>
          </Group>
          <Text size="xs" c="dimmed" mt="xs" style={{ lineHeight: 1.6 }}>
            自動產生的代碼為 4 個字元（區分大小寫），代碼一經使用即不再重複配發；系統會避開常見英文單字。
          </Text>
        </Stack>
      </Card>

      {result ? (
        <Card
          withBorder
          padding="xl"
          radius="md"
          style={{
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.12)',
            background: 'linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%)',
            border: '2px solid var(--mantine-color-blue-4)',
          }}
        >
          <Stack gap="md">
            <div>
              <Title order={4} style={{ marginBottom: '4px', color: 'var(--mantine-color-blue-9)' }}>
                ✓ 短網址建立成功！
              </Title>
              <Text c="dimmed" size="sm">您的短網址已可分享使用</Text>
            </div>
            <div
              style={{
                background: 'white',
                padding: '16px',
                borderRadius: 'var(--mantine-radius-md)',
                border: '1px solid var(--mantine-color-blue-3)',
              }}
            >
              <Text
                fw={700}
                size="xl"
                style={{
                  wordBreak: 'break-all',
                  fontFamily: 'monospace',
                  color: 'var(--mantine-color-blue-9)',
                  letterSpacing: '0.5px',
                }}
              >
                {result.short_url}
              </Text>
            </div>
            <Group gap="sm" mt="xs">
              <CopyButton value={result.short_url}>
                {({ copied, copy }) => (
                  <Button
                    variant="filled"
                    onClick={copy}
                    size="md"
                    radius="md"
                    style={{
                      background: copied
                        ? 'var(--mantine-color-green-6)'
                        : 'linear-gradient(135deg, var(--mantine-color-blue-6) 0%, var(--mantine-color-blue-7) 100%)',
                      fontWeight: 600,
                    }}
                  >
                    {copied ? '✓ 已複製！' : '複製連結'}
                  </Button>
                )}
              </CopyButton>
              <Button
                variant="light"
                component="a"
                href={result.short_url}
                target="_blank"
                rel="noreferrer"
                size="md"
                radius="md"
              >
                開啟連結
              </Button>
              <Button
                variant="outline"
                leftSection={<IconQrcode size={18} />}
                component="a"
                href={api.getQrCodeUrl(result.code)}
                download={`qrcode_${result.code}.png`}
                size="md"
                radius="md"
              >
                下載 QR Code
              </Button>
            </Group>
          </Stack>
        </Card>
      ) : null}
    </Stack>
  );
}

