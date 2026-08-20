import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  CopyButton,
  FileInput,
  Group,
  Pagination,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { DateTimePicker } from '@mantine/dates';
import '@mantine/dates/styles.css';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import {
  IconAlertTriangle,
  IconBan,
  IconCalendar,
  IconCheck,
  IconCopy,
  IconKey,
  IconLock,
  IconRefresh,
  IconTrash,
  IconUpload,
} from '@tabler/icons-react';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { SharedFile } from '../api/types';

type StatusFilter = 'active' | 'disabled' | 'expired' | 'deleted' | 'all';
type ExpiryPreset = '1' | '7' | '30' | 'custom' | 'never';

const PIN_LENGTH = 8;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let size = bytes / 1024;
  for (const unit of units) {
    if (size < 1024 || unit === 'GB') return `${size.toFixed(1)} ${unit}`;
    size /= 1024;
  }
  return `${size.toFixed(1)} GB`;
}

function CopyableField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <Text size="sm" fw={600} mb={4}>
        {label}
      </Text>
      <Group gap="xs" wrap="nowrap">
        <Text
          style={{
            flex: 1,
            wordBreak: 'break-all',
            fontFamily: mono ? 'monospace' : undefined,
            fontSize: mono ? '22px' : '15px',
            letterSpacing: mono ? '3px' : undefined,
            fontWeight: mono ? 700 : 400,
            background: 'var(--mantine-color-gray-1)',
            padding: '10px 14px',
            borderRadius: 'var(--mantine-radius-sm)',
          }}
        >
          {value}
        </Text>
        <CopyButton value={value} timeout={2000}>
          {({ copied, copy }) => (
            <Tooltip label={copied ? '已複製' : '複製'} withArrow>
              <ActionIcon variant="light" color={copied ? 'green' : 'blue'} size="lg" onClick={copy}>
                {copied ? <IconCheck size={18} /> : <IconCopy size={18} />}
              </ActionIcon>
            </Tooltip>
          )}
        </CopyButton>
      </Group>
    </div>
  );
}

/**
 * Shown right after upload or a PIN regeneration.
 *
 * This is the only time the PIN is readable — it is stored hashed, so it can be
 * replaced but never looked up again.
 */
function ShareResult({ shareUrl, pin, filename }: { shareUrl: string; pin: string; filename?: string }) {
  const combined = `檔案：${filename ?? ''}\n下載連結：${shareUrl}\nPIN 碼：${pin}`;
  return (
    <Stack gap="lg">
      <Alert color="orange" icon={<IconAlertTriangle size={18} />} title="請立即複製 PIN 碼">
        PIN 碼僅顯示這一次，關閉後就無法再查看。若日後遺失，只能重新產生一組新的 PIN 碼。
      </Alert>
      {filename && <CopyableField label="檔案名稱" value={filename} />}
      <CopyableField label="下載連結" value={shareUrl} />
      <CopyableField label="PIN 碼" value={pin} mono />
      <Group justify="space-between">
        <CopyButton value={combined} timeout={2000}>
          {({ copied, copy }) => (
            <Button
              variant="light"
              color={copied ? 'green' : 'blue'}
              leftSection={copied ? <IconCheck size={18} /> : <IconCopy size={18} />}
              onClick={copy}
            >
              {copied ? '已複製連結與 PIN 碼' : '一併複製連結與 PIN 碼'}
            </Button>
          )}
        </CopyButton>
        <Button onClick={() => modals.closeAll()}>我已複製，關閉</Button>
      </Group>
    </Stack>
  );
}

function openShareResult(opts: { shareUrl: string; pin: string; filename?: string; title: string }) {
  modals.open({
    title: opts.title,
    size: 'lg',
    closeOnClickOutside: false,
    children: <ShareResult shareUrl={opts.shareUrl} pin={opts.pin} filename={opts.filename} />,
  });
}

function EditForm({
  file,
  onSave,
  onCancel,
}: {
  file: SharedFile;
  onSave: (patch: { expires_at?: string | null; note?: string | null }) => Promise<void>;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<'permanent' | 'datetime'>(file.expires_at ? 'datetime' : 'permanent');
  const [expiresAt, setExpiresAt] = useState<Date | null>(file.expires_at ? new Date(file.expires_at) : null);
  const [note, setNote] = useState(file.note ?? '');
  const [saving, setSaving] = useState(false);

  return (
    <Stack gap="md">
      <TextInput label="備註" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
      <Select
        label="有效期限"
        data={[
          { value: 'permanent', label: '永久有效' },
          { value: 'datetime', label: '指定日期／時間' },
        ]}
        value={mode}
        onChange={(v) => setMode((v as 'permanent' | 'datetime') ?? 'permanent')}
      />
      {mode === 'datetime' && (
        <DateTimePicker label="到期時間" value={expiresAt} onChange={setExpiresAt} />
      )}
      <Group justify="flex-end" gap="sm">
        <Button variant="default" onClick={onCancel}>
          取消
        </Button>
        <Button
          loading={saving}
          onClick={async () => {
            setSaving(true);
            await onSave({
              note: note.trim() || null,
              expires_at: mode === 'permanent' ? null : expiresAt ? expiresAt.toISOString() : null,
            });
            setSaving(false);
          }}
        >
          儲存
        </Button>
      </Group>
    </Stack>
  );
}

function statusBadge(f: SharedFile) {
  if (f.status === 'deleted') return <Badge color="dark">已刪除</Badge>;
  if (f.status === 'disabled') return <Badge color="gray">已停用</Badge>;
  if (f.is_expired) return <Badge color="orange">已過期</Badge>;
  return <Badge color="green">分享中</Badge>;
}

export function FilesPage() {
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState('');
  const [customPin, setCustomPin] = useState('');
  const [expiryPreset, setExpiryPreset] = useState<ExpiryPreset>('7');
  const [customExpiry, setCustomExpiry] = useState<Date | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);

  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [items, setItems] = useState<SharedFile[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const limit = 20;
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(total / limit));

  async function load() {
    setLoading(true);
    try {
      const res = await api.listSharedFiles({
        query: query.trim() || undefined,
        status,
        limit,
        offset: (page - 1) * limit,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      notifications.show({ color: 'red', message: e instanceof Error ? e.message : '載入失敗' });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, status, query]);

  const pinError = (() => {
    if (!customPin) return null;
    const value = customPin.toUpperCase();
    if (value.length !== PIN_LENGTH) return `PIN 碼必須為 ${PIN_LENGTH} 碼`;
    if (!/^[A-Z0-9]+$/.test(value)) return 'PIN 碼只能使用英文字母與數字';
    if (!/[A-Z]/.test(value)) return 'PIN 碼必須至少包含一個英文字母';
    if (!/[0-9]/.test(value)) return 'PIN 碼必須至少包含一個數字';
    return null;
  })();

  function resolveExpiry(): string | null {
    if (expiryPreset === 'never') return null;
    if (expiryPreset === 'custom') return customExpiry ? customExpiry.toISOString() : null;
    return dayjs().add(Number(expiryPreset), 'day').toISOString();
  }

  async function upload() {
    if (!file) return;
    setUploading(true);
    setProgress(0);
    try {
      const created = await api.uploadSharedFile(
        {
          file,
          note: note.trim() || null,
          expires_at: resolveExpiry(),
          pin: customPin ? customPin.toUpperCase() : null,
        },
        setProgress,
      );
      setFile(null);
      setNote('');
      setCustomPin('');
      openShareResult({
        title: '檔案已上傳',
        shareUrl: created.share_url,
        pin: created.pin,
        filename: created.filename,
      });
      load();
    } catch (e) {
      notifications.show({ color: 'red', message: e instanceof Error ? e.message : '上傳失敗' });
    } finally {
      setUploading(false);
      setProgress(0);
    }
  }

  function confirmRegeneratePin(f: SharedFile) {
    modals.openConfirmModal({
      title: '重新產生 PIN 碼？',
      children: (
        <Text size="sm">
          將為 <Text span fw={600}>{f.filename}</Text> 產生一組新的 PIN
          碼。舊的 PIN 碼會立即失效，已經拿到舊 PIN 碼的人將無法再下載，請記得通知對方新的 PIN 碼。
        </Text>
      ),
      labels: { confirm: '重新產生', cancel: '取消' },
      confirmProps: { color: 'orange' },
      onConfirm: async () => {
        try {
          const res = await api.regenerateSharedFilePin(f.code);
          openShareResult({
            title: '已產生新的 PIN 碼',
            shareUrl: f.share_url,
            pin: res.pin,
            filename: f.filename,
          });
          load();
        } catch (e) {
          notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
        }
      },
    });
  }

  function openEditModal(f: SharedFile) {
    modals.open({
      title: '編輯檔案設定',
      size: 'md',
      children: (
        <EditForm
          file={f}
          onSave={async (patch) => {
            try {
              await api.updateSharedFile(f.code, patch);
              notifications.show({ color: 'green', message: '已更新' });
              modals.closeAll();
              load();
            } catch (e) {
              notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
            }
          }}
          onCancel={() => modals.closeAll()}
        />
      ),
    });
  }

  function confirmDisable(f: SharedFile) {
    modals.openConfirmModal({
      title: '停用分享連結？',
      children: (
        <Text size="sm">
          停用後任何人都無法再下載 <Text span fw={600}>{f.filename}</Text>，檔案本身仍保留在系統中，日後可再重新啟用。
        </Text>
      ),
      labels: { confirm: '停用', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.disableSharedFile(f.code);
          notifications.show({ color: 'green', message: '已停用' });
          load();
        } catch (e) {
          notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
        }
      },
    });
  }

  function confirmDelete(f: SharedFile) {
    modals.openConfirmModal({
      title: '永久刪除檔案？',
      children: (
        <Text size="sm">
          將把 <Text span fw={600}>{f.filename}</Text> 從儲存空間中<Text span fw={700} c="red">永久刪除</Text>
          ，此操作無法復原。系統只會保留這筆分享紀錄供日後查核。
        </Text>
      ),
      labels: { confirm: '永久刪除', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.deleteSharedFile(f.code);
          notifications.show({ color: 'green', message: '檔案已刪除' });
          load();
        } catch (e) {
          notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
        }
      },
    });
  }

  const cardStyle = {
    boxShadow: '0 2px 12px rgba(0, 0, 0, 0.1)',
    background: 'white',
    border: '1px solid var(--mantine-color-gray-2)',
  };

  return (
    <Stack gap="xl">
      <Group justify="space-between" align="center">
        <div>
          <Title order={1} style={{ marginBottom: '8px', fontWeight: 700 }}>
            檔案分享
          </Title>
          <Text c="dimmed" size="sm">
            上傳檔案並產生需輸入 PIN 碼才能下載的分享連結
          </Text>
        </div>
        <Button
          leftSection={<IconRefresh size={18} />}
          variant="light"
          loading={loading}
          onClick={load}
          size="md"
          radius="md"
        >
          重新整理
        </Button>
      </Group>

      <Card withBorder padding="xl" radius="md" style={cardStyle}>
        <Stack gap="md">
          <Title order={4}>上傳新檔案</Title>
          <Group align="flex-start" grow>
            <FileInput
              label="選擇檔案"
              placeholder="點此選擇要分享的檔案"
              value={file}
              onChange={setFile}
              clearable
              size="md"
              radius="md"
              description={file ? `檔案大小：${formatSize(file.size)}` : '單一檔案上限 25 MB'}
            />
            <Select
              label="有效期限"
              data={[
                { value: '1', label: '1 天後失效' },
                { value: '7', label: '7 天後失效' },
                { value: '30', label: '30 天後失效' },
                { value: 'custom', label: '指定日期／時間' },
                { value: 'never', label: '永久有效' },
              ]}
              value={expiryPreset}
              onChange={(v) => setExpiryPreset((v as ExpiryPreset) ?? '7')}
              size="md"
              radius="md"
            />
          </Group>
          {expiryPreset === 'custom' && (
            <DateTimePicker
              label="到期時間"
              value={customExpiry}
              onChange={setCustomExpiry}
              size="md"
              radius="md"
            />
          )}
          <Group align="flex-start" grow>
            <TextInput
              label="備註"
              placeholder="例如：長官交辦、會議簡報"
              value={note}
              onChange={(e) => setNote(e.currentTarget.value)}
              size="md"
              radius="md"
            />
            <TextInput
              label="自訂 PIN 碼（選填）"
              placeholder="留空則自動產生"
              value={customPin}
              onChange={(e) => setCustomPin(e.currentTarget.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
              maxLength={PIN_LENGTH}
              error={pinError}
              size="md"
              radius="md"
              description={`${PIN_LENGTH} 碼英文字母與數字組合`}
              styles={{ input: { fontFamily: 'monospace', letterSpacing: '2px' } }}
            />
          </Group>
          {uploading && <Progress value={progress} striped animated size="lg" radius="md" />}
          <Group justify="flex-end">
            <Button
              leftSection={<IconUpload size={18} />}
              disabled={!file || !!pinError || (expiryPreset === 'custom' && !customExpiry)}
              loading={uploading}
              onClick={upload}
              size="md"
              radius="md"
              style={{
                background:
                  'linear-gradient(135deg, var(--mantine-color-blue-6) 0%, var(--mantine-color-blue-7) 100%)',
                fontWeight: 600,
              }}
            >
              上傳並產生分享連結
            </Button>
          </Group>
        </Stack>
      </Card>

      <Card withBorder padding="xl" radius="md" style={cardStyle}>
        <Stack gap="md">
          <Group align="flex-end" grow>
            <TextInput
              label="搜尋"
              placeholder="代碼、檔名或備註"
              value={query}
              onChange={(e) => {
                setPage(1);
                setQuery(e.currentTarget.value);
              }}
              size="md"
              radius="md"
            />
            <Select
              label="狀態"
              data={[
                { value: 'all', label: '全部' },
                { value: 'active', label: '分享中' },
                { value: 'expired', label: '已過期' },
                { value: 'disabled', label: '已停用' },
                { value: 'deleted', label: '已刪除' },
              ]}
              value={status}
              onChange={(v) => {
                setPage(1);
                setStatus((v as StatusFilter) ?? 'all');
              }}
              size="md"
              radius="md"
            />
          </Group>

          <Table highlightOnHover withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ fontWeight: 600 }}>檔案名稱</Table.Th>
                <Table.Th style={{ width: '220px', fontWeight: 600 }}>分享連結</Table.Th>
                <Table.Th style={{ width: '90px', fontWeight: 600 }}>大小</Table.Th>
                <Table.Th style={{ width: '140px', fontWeight: 600 }}>有效期限</Table.Th>
                <Table.Th style={{ width: '100px', fontWeight: 600 }}>狀態</Table.Th>
                <Table.Th style={{ width: '90px', fontWeight: 600 }}>下載次數</Table.Th>
                <Table.Th style={{ width: '150px' }}>操作</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {loading ? (
                <Table.Tr>
                  <Table.Td colSpan={7}>
                    <Text c="dimmed" size="sm" ta="center" py="xl">
                      載入中…
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : items.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={7}>
                    <Text c="dimmed" size="sm" ta="center" py="xl">
                      {query || status !== 'all'
                        ? '查無符合篩選條件的資料'
                        : '目前尚無分享檔案，請於上方上傳第一個檔案。'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                items.map((f) => (
                  <Table.Tr key={f.id}>
                    <Table.Td>
                      <Group gap="xs" wrap="nowrap">
                        <Text size="sm" style={{ wordBreak: 'break-all' }}>
                          {f.filename}
                        </Text>
                        {f.is_locked && (
                          <Tooltip label="PIN 碼連續輸入錯誤，連結暫時鎖定中" withArrow>
                            <IconLock size={16} color="var(--mantine-color-red-6)" />
                          </Tooltip>
                        )}
                      </Group>
                      {f.note && (
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          {f.note}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <Text size="xs" style={{ wordBreak: 'break-all', flex: 1 }}>
                          {f.share_url}
                        </Text>
                        <CopyButton value={f.share_url} timeout={2000}>
                          {({ copied, copy }) => (
                            <Tooltip label={copied ? '已複製' : '複製連結'} withArrow>
                              <ActionIcon
                                variant="subtle"
                                color={copied ? 'green' : 'blue'}
                                onClick={copy}
                                aria-label="複製連結"
                              >
                                {copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                              </ActionIcon>
                            </Tooltip>
                          )}
                        </CopyButton>
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{formatSize(f.size_bytes)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">
                        {f.expires_at ? dayjs(f.expires_at).format('YYYY-MM-DD HH:mm') : '永久有效'}
                      </Text>
                    </Table.Td>
                    <Table.Td>{statusBadge(f)}</Table.Td>
                    <Table.Td>
                      <Text fw={600} size="sm" c="blue">
                        {f.download_count.toLocaleString()}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {f.status === 'deleted' ? (
                        <Text size="xs" c="dimmed">
                          —
                        </Text>
                      ) : (
                        <Group gap="xs" wrap="nowrap">
                          {f.status === 'disabled' ? (
                            <Tooltip label="重新啟用" withArrow>
                              <ActionIcon
                                variant="subtle"
                                color="green"
                                aria-label="重新啟用"
                                onClick={async () => {
                                  try {
                                    await api.enableSharedFile(f.code);
                                    notifications.show({ color: 'green', message: '已重新啟用' });
                                    load();
                                  } catch (e) {
                                    notifications.show({
                                      color: 'red',
                                      message: e instanceof Error ? e.message : '操作失敗',
                                    });
                                  }
                                }}
                              >
                                <IconCheck size={18} />
                              </ActionIcon>
                            </Tooltip>
                          ) : (
                            <>
                              <Tooltip label="重新產生 PIN 碼" withArrow>
                                <ActionIcon
                                  variant="subtle"
                                  color="orange"
                                  aria-label="重新產生 PIN 碼"
                                  onClick={() => confirmRegeneratePin(f)}
                                >
                                  <IconKey size={18} />
                                </ActionIcon>
                              </Tooltip>
                              <Tooltip label="編輯期限與備註" withArrow>
                                <ActionIcon
                                  variant="subtle"
                                  color="blue"
                                  aria-label="編輯期限與備註"
                                  onClick={() => openEditModal(f)}
                                >
                                  <IconCalendar size={18} />
                                </ActionIcon>
                              </Tooltip>
                              <Tooltip label="停用" withArrow>
                                <ActionIcon
                                  variant="subtle"
                                  color="red"
                                  aria-label="停用"
                                  onClick={() => confirmDisable(f)}
                                >
                                  <IconBan size={18} />
                                </ActionIcon>
                              </Tooltip>
                            </>
                          )}
                          <Tooltip label="永久刪除檔案" withArrow>
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              aria-label="永久刪除檔案"
                              onClick={() => confirmDelete(f)}
                            >
                              <IconTrash size={18} />
                            </ActionIcon>
                          </Tooltip>
                        </Group>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))
              )}
            </Table.Tbody>
          </Table>

          <Group justify="space-between" mt="md" align="center">
            <Text size="sm" c="dimmed" fw={500}>
              共 {total} 筆分享檔案
            </Text>
            <Pagination value={page} onChange={setPage} total={totalPages} size="md" radius="md" />
          </Group>
        </Stack>
      </Card>
    </Stack>
  );
}
