import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Collapse,
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
  IconArrowDown,
  IconArrowUp,
  IconBan,
  IconCalendar,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconCopy,
  IconKey,
  IconLock,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconUpload,
} from '@tabler/icons-react';
import dayjs from 'dayjs';
import { Fragment, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { FileShare } from '../api/types';

type StatusFilter = 'active' | 'disabled' | 'expired' | 'deleted' | 'all';
type ExpiryPreset = '1' | '7' | '30' | 'custom' | 'never';

const PIN_LENGTH = 8;

/**
 * Mirrors the backend's MAX_FILE_MB. Files above the Cloud Run request limit go
 * straight to object storage, so this ceiling is about sanity, not plumbing.
 * The backend stays authoritative.
 */
const MAX_FILE_MB = 2048;

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
 * Shown right after a share is created or its PIN regenerated.
 *
 * This is the only time the PIN is readable — it is stored hashed, so it can be
 * replaced but never looked up again.
 */
function ShareResult({
  shareUrl,
  pin,
  filenames,
}: {
  shareUrl: string;
  pin: string;
  filenames?: string[];
}) {
  const fileLine = filenames?.length ? `檔案：${filenames.join('、')}\n` : '';
  const combined = `${fileLine}下載連結：${shareUrl}\nPIN 碼：${pin}`;
  return (
    <Stack gap="lg">
      <Alert color="orange" icon={<IconAlertTriangle size={18} />} title="請立即複製 PIN 碼">
        PIN 碼僅顯示這一次，關閉後就無法再查看。若日後遺失，只能重新產生一組新的 PIN 碼。
      </Alert>
      {filenames && filenames.length > 0 && (
        <div>
          <Text size="sm" fw={600} mb={4}>
            檔案（{filenames.length}）
          </Text>
          <Stack gap={2}>
            {filenames.map((name) => (
              <Text key={name} size="sm" c="dimmed" style={{ wordBreak: 'break-all' }}>
                {name}
              </Text>
            ))}
          </Stack>
        </div>
      )}
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

function openShareResult(opts: {
  shareUrl: string;
  pin: string;
  filenames?: string[];
  title: string;
}) {
  modals.open({
    title: opts.title,
    size: 'lg',
    closeOnClickOutside: false,
    children: <ShareResult shareUrl={opts.shareUrl} pin={opts.pin} filenames={opts.filenames} />,
  });
}

function EditForm({
  share,
  onSave,
  onCancel,
}: {
  share: FileShare;
  onSave: (patch: { expires_at?: string | null; note?: string | null }) => Promise<void>;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<'permanent' | 'datetime'>(share.expires_at ? 'datetime' : 'permanent');
  const [expiresAt, setExpiresAt] = useState<Date | null>(
    share.expires_at ? new Date(share.expires_at) : null,
  );
  const [note, setNote] = useState(share.note ?? '');
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

function statusBadge(share: FileShare) {
  if (share.status === 'deleted') return <Badge color="dark">已刪除</Badge>;
  if (share.status === 'disabled') return <Badge color="gray">已停用</Badge>;
  if (share.is_expired) return <Badge color="orange">已過期</Badge>;
  if (share.file_count === 0) return <Badge color="yellow">尚無檔案</Badge>;
  return <Badge color="green">分享中</Badge>;
}

type UploadState = { name: string; percent: number; done: boolean; error?: string };

export function FilesPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [note, setNote] = useState('');
  const [customPin, setCustomPin] = useState('');
  const [expiryPreset, setExpiryPreset] = useState<ExpiryPreset>('7');
  const [customExpiry, setCustomExpiry] = useState<Date | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploads, setUploads] = useState<UploadState[]>([]);

  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [items, setItems] = useState<FileShare[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const limit = 20;
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(total / limit));

  async function load() {
    setLoading(true);
    try {
      const res = await api.listShares({
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

  const oversized = files.filter((f) => f.size > MAX_FILE_MB * 1024 * 1024);
  const fileError = oversized.length
    ? `${oversized[0].name} 超過上限 ${MAX_FILE_MB} MB`
    : null;
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);

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

  /**
   * Upload files into a share one at a time.
   *
   * Sequential rather than parallel: it keeps each progress bar meaningful, and
   * avoids several large uploads competing for an office connection. Returns
   * the names that made it.
   */
  async function uploadInto(code: string, chosen: File[]): Promise<string[]> {
    setUploads(chosen.map((f) => ({ name: f.name, percent: 0, done: false })));
    const uploaded: string[] = [];

    for (let i = 0; i < chosen.length; i += 1) {
      const file = chosen[i];
      try {
        await api.uploadFileToShare(code, file, (percent) => {
          setUploads((prev) => prev.map((u, idx) => (idx === i ? { ...u, percent } : u)));
        });
        uploaded.push(file.name);
        setUploads((prev) =>
          prev.map((u, idx) => (idx === i ? { ...u, percent: 100, done: true } : u)),
        );
      } catch (e) {
        const message = e instanceof Error ? e.message : '上傳失敗';
        setUploads((prev) => prev.map((u, idx) => (idx === i ? { ...u, error: message } : u)));
        notifications.show({ color: 'red', message: `${file.name}：${message}` });
      }
    }
    return uploaded;
  }

  async function createAndUpload() {
    if (!files.length) return;
    setUploading(true);
    try {
      const created = await api.createShare({
        note: note.trim() || null,
        expires_at: resolveExpiry(),
        pin: customPin ? customPin.toUpperCase() : null,
      });

      const uploaded = await uploadInto(created.code, files);

      if (uploaded.length === 0) {
        notifications.show({
          color: 'red',
          message: '所有檔案都上傳失敗，分享連結已建立但沒有內容，請用「加入檔案」重試',
        });
      } else {
        setFiles([]);
        setNote('');
        setCustomPin('');
        openShareResult({
          title:
            uploaded.length === files.length
              ? '分享連結已建立'
              : `分享連結已建立（${uploaded.length}/${files.length} 個檔案上傳成功）`,
          shareUrl: created.share_url,
          pin: created.pin,
          filenames: uploaded,
        });
      }
      load();
    } catch (e) {
      notifications.show({ color: 'red', message: e instanceof Error ? e.message : '建立失敗' });
    } finally {
      setUploading(false);
      setUploads([]);
    }
  }

  function openAddFiles(share: FileShare) {
    modals.open({
      title: `加入檔案到 ${share.code}`,
      size: 'lg',
      children: (
        <AddFilesForm
          share={share}
          onUpload={async (chosen) => {
            const uploaded = await uploadInto(share.code, chosen);
            if (uploaded.length) {
              notifications.show({ color: 'green', message: `已加入 ${uploaded.length} 個檔案` });
            }
            modals.closeAll();
            setUploads([]);
            load();
          }}
          onCancel={() => modals.closeAll()}
        />
      ),
    });
  }

  function confirmRegeneratePin(share: FileShare) {
    modals.openConfirmModal({
      title: '重新產生 PIN 碼？',
      children: (
        <Text size="sm">
          將為 <Text span fw={600}>{share.code}</Text> 產生一組新的 PIN
          碼。舊的 PIN 碼會立即失效，已經拿到舊 PIN 碼的人將無法再下載，請記得通知對方新的 PIN 碼。
        </Text>
      ),
      labels: { confirm: '重新產生', cancel: '取消' },
      confirmProps: { color: 'orange' },
      onConfirm: async () => {
        try {
          const res = await api.regenerateSharePin(share.code);
          openShareResult({
            title: '已產生新的 PIN 碼',
            shareUrl: share.share_url,
            pin: res.pin,
            filenames: share.files.filter((f) => f.status === 'active').map((f) => f.filename),
          });
          load();
        } catch (e) {
          notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
        }
      },
    });
  }

  function openEditModal(share: FileShare) {
    modals.open({
      title: '編輯分享設定',
      size: 'md',
      children: (
        <EditForm
          share={share}
          onSave={async (patch) => {
            try {
              await api.updateShare(share.code, patch);
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

  function confirmDisable(share: FileShare) {
    modals.openConfirmModal({
      title: '停用分享連結？',
      children: (
        <Text size="sm">
          停用後任何人都無法再下載這 {share.file_count} 個檔案，檔案本身仍保留在系統中，日後可再重新啟用。
        </Text>
      ),
      labels: { confirm: '停用', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.disableShare(share.code);
          notifications.show({ color: 'green', message: '已停用' });
          load();
        } catch (e) {
          notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
        }
      },
    });
  }

  function confirmDelete(share: FileShare) {
    modals.openConfirmModal({
      title: '永久刪除這個分享？',
      children: (
        <Text size="sm">
          將把 <Text span fw={600}>{share.code}</Text> 底下的 {share.file_count} 個檔案從儲存空間中
          <Text span fw={700} c="red">永久刪除</Text>，此操作無法復原。系統只會保留這筆分享紀錄供日後查核。
        </Text>
      ),
      labels: { confirm: '永久刪除', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.deleteShare(share.code);
          notifications.show({ color: 'green', message: '檔案已刪除' });
          load();
        } catch (e) {
          notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
        }
      },
    });
  }

  function confirmDeleteFile(share: FileShare, fileId: number, filename: string) {
    modals.openConfirmModal({
      title: '從分享中移除這個檔案？',
      children: (
        <Text size="sm">
          將把 <Text span fw={600}>{filename}</Text> 從儲存空間中
          <Text span fw={700} c="red">永久刪除</Text>，分享中的其他檔案不受影響。
        </Text>
      ),
      labels: { confirm: '永久刪除', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.deleteShareFile(share.code, fileId);
          notifications.show({ color: 'green', message: '檔案已移除' });
          load();
        } catch (e) {
          notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
        }
      },
    });
  }

  /**
   * Move one file up or down within its share.
   *
   * Up/down buttons rather than drag-and-drop: they need no library, work with
   * a keyboard, and a share holds a handful of files, not hundreds.
   */
  async function moveFile(share: FileShare, fileId: number, direction: -1 | 1) {
    const ids = share.files.filter((f) => f.status === 'active').map((f) => f.id);
    const from = ids.indexOf(fileId);
    const to = from + direction;
    if (from < 0 || to < 0 || to >= ids.length) return;
    [ids[from], ids[to]] = [ids[to], ids[from]];

    try {
      const updated = await api.reorderShareFiles(share.code, ids);
      setItems((prev) => prev.map((s) => (s.code === updated.code ? updated : s)));
    } catch (e) {
      notifications.show({ color: 'red', message: e instanceof Error ? e.message : '排序失敗' });
      load();
    }
  }

  function toggleExpanded(code: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
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
            上傳檔案並產生需輸入 PIN 碼才能下載的分享連結；一個連結可放多個檔案
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
          <Title order={4}>建立新的分享</Title>
          <Group align="flex-start" grow>
            <FileInput
              label="選擇檔案（可多選）"
              placeholder="點此選擇要分享的檔案"
              value={files}
              onChange={setFiles}
              multiple
              clearable
              size="md"
              radius="md"
              error={fileError}
              description={
                files.length
                  ? `${files.length} 個檔案，共 ${formatSize(totalBytes)}`
                  : '可一次選取多個檔案，它們會共用同一個連結與 PIN 碼'
              }
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
          <UploadProgress uploads={uploads} />
          <Group justify="flex-end">
            <Button
              leftSection={<IconUpload size={18} />}
              disabled={
                !files.length || !!fileError || !!pinError || (expiryPreset === 'custom' && !customExpiry)
              }
              loading={uploading}
              onClick={createAndUpload}
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
                <Table.Th style={{ width: '40px' }} />
                <Table.Th style={{ width: '100px', fontWeight: 600 }}>代碼</Table.Th>
                <Table.Th style={{ fontWeight: 600 }}>內容</Table.Th>
                <Table.Th style={{ width: '220px', fontWeight: 600 }}>分享連結</Table.Th>
                <Table.Th style={{ width: '140px', fontWeight: 600 }}>有效期限</Table.Th>
                <Table.Th style={{ width: '100px', fontWeight: 600 }}>狀態</Table.Th>
                <Table.Th style={{ width: '90px', fontWeight: 600 }}>下載次數</Table.Th>
                <Table.Th style={{ width: '180px' }}>操作</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {loading ? (
                <Table.Tr>
                  <Table.Td colSpan={8}>
                    <Text c="dimmed" size="sm" ta="center" py="xl">
                      載入中…
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : items.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={8}>
                    <Text c="dimmed" size="sm" ta="center" py="xl">
                      {query || status !== 'all'
                        ? '查無符合篩選條件的資料'
                        : '目前尚無分享，請於上方建立第一個。'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                items.map((share) => {
                  const isOpen = expanded.has(share.code);
                  const liveFiles = share.files.filter((f) => f.status === 'active');
                  return (
                    <Fragment key={share.code}>
                      <Table.Tr>
                        <Table.Td>
                          <ActionIcon
                            variant="subtle"
                            color="gray"
                            aria-label={isOpen ? '收合檔案清單' : '展開檔案清單'}
                            onClick={() => toggleExpanded(share.code)}
                          >
                            {isOpen ? <IconChevronDown size={18} /> : <IconChevronRight size={18} />}
                          </ActionIcon>
                        </Table.Td>
                        <Table.Td>
                          <Group gap={6} wrap="nowrap">
                            <Text
                              fw={700}
                              size="sm"
                              style={{
                                fontFamily: 'monospace',
                                background: 'var(--mantine-color-gray-1)',
                                padding: '4px 8px',
                                borderRadius: 'var(--mantine-radius-sm)',
                              }}
                            >
                              {share.code}
                            </Text>
                            {share.is_locked && (
                              <Tooltip label="PIN 碼連續輸入錯誤，連結暫時鎖定中" withArrow>
                                <IconLock size={16} color="var(--mantine-color-red-6)" />
                              </Tooltip>
                            )}
                          </Group>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">
                            {share.file_count} 個檔案 · {formatSize(share.total_bytes)}
                          </Text>
                          {share.note && (
                            <Text size="xs" c="dimmed" lineClamp={1}>
                              {share.note}
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td>
                          <Group gap={4} wrap="nowrap">
                            <Text size="xs" style={{ wordBreak: 'break-all', flex: 1 }}>
                              {share.share_url}
                            </Text>
                            <CopyButton value={share.share_url} timeout={2000}>
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
                          <Text size="sm">
                            {share.expires_at
                              ? dayjs(share.expires_at).format('YYYY-MM-DD HH:mm')
                              : '永久有效'}
                          </Text>
                        </Table.Td>
                        <Table.Td>{statusBadge(share)}</Table.Td>
                        <Table.Td>
                          <Text fw={600} size="sm" c="blue">
                            {share.download_count.toLocaleString()}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          {share.status === 'deleted' ? (
                            <Text size="xs" c="dimmed">
                              —
                            </Text>
                          ) : (
                            <Group gap="xs" wrap="nowrap">
                              {share.status === 'disabled' ? (
                                <Tooltip label="重新啟用" withArrow>
                                  <ActionIcon
                                    variant="subtle"
                                    color="green"
                                    aria-label="重新啟用"
                                    onClick={async () => {
                                      try {
                                        await api.enableShare(share.code);
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
                                  <Tooltip label="加入檔案" withArrow>
                                    <ActionIcon
                                      variant="subtle"
                                      color="blue"
                                      aria-label="加入檔案"
                                      onClick={() => openAddFiles(share)}
                                    >
                                      <IconPlus size={18} />
                                    </ActionIcon>
                                  </Tooltip>
                                  <Tooltip label="重新產生 PIN 碼" withArrow>
                                    <ActionIcon
                                      variant="subtle"
                                      color="orange"
                                      aria-label="重新產生 PIN 碼"
                                      onClick={() => confirmRegeneratePin(share)}
                                    >
                                      <IconKey size={18} />
                                    </ActionIcon>
                                  </Tooltip>
                                  <Tooltip label="編輯期限與備註" withArrow>
                                    <ActionIcon
                                      variant="subtle"
                                      color="blue"
                                      aria-label="編輯期限與備註"
                                      onClick={() => openEditModal(share)}
                                    >
                                      <IconCalendar size={18} />
                                    </ActionIcon>
                                  </Tooltip>
                                  <Tooltip label="停用" withArrow>
                                    <ActionIcon
                                      variant="subtle"
                                      color="red"
                                      aria-label="停用"
                                      onClick={() => confirmDisable(share)}
                                    >
                                      <IconBan size={18} />
                                    </ActionIcon>
                                  </Tooltip>
                                </>
                              )}
                              <Tooltip label="永久刪除全部檔案" withArrow>
                                <ActionIcon
                                  variant="subtle"
                                  color="red"
                                  aria-label="永久刪除全部檔案"
                                  onClick={() => confirmDelete(share)}
                                >
                                  <IconTrash size={18} />
                                </ActionIcon>
                              </Tooltip>
                            </Group>
                          )}
                        </Table.Td>
                      </Table.Tr>
                      <Table.Tr>
                        <Table.Td colSpan={8} p={0} style={{ borderBottom: 0 }}>
                          <Collapse in={isOpen}>
                            <Stack gap="xs" p="md" bg="var(--mantine-color-gray-0)">
                              {liveFiles.length === 0 ? (
                                <Text size="sm" c="dimmed">
                                  這個分享目前沒有檔案，公開連結不會顯示內容。
                                </Text>
                              ) : (
                                liveFiles.map((f, index) => (
                                  <Group key={f.id} gap="sm" wrap="nowrap">
                                    {share.status !== 'deleted' && liveFiles.length > 1 && (
                                      <Group gap={2} wrap="nowrap">
                                        <ActionIcon
                                          variant="subtle"
                                          color="gray"
                                          size="sm"
                                          aria-label="上移"
                                          disabled={index === 0}
                                          onClick={() => moveFile(share, f.id, -1)}
                                        >
                                          <IconArrowUp size={16} />
                                        </ActionIcon>
                                        <ActionIcon
                                          variant="subtle"
                                          color="gray"
                                          size="sm"
                                          aria-label="下移"
                                          disabled={index === liveFiles.length - 1}
                                          onClick={() => moveFile(share, f.id, 1)}
                                        >
                                          <IconArrowDown size={16} />
                                        </ActionIcon>
                                      </Group>
                                    )}
                                    <Text size="sm" c="dimmed" style={{ minWidth: 20 }}>
                                      {index + 1}.
                                    </Text>
                                    <Text size="sm" style={{ flex: 1, wordBreak: 'break-all' }}>
                                      {f.filename}
                                    </Text>
                                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                                      {formatSize(f.size_bytes)}
                                    </Text>
                                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                                      下載 {f.download_count} 次
                                    </Text>
                                    {share.status !== 'deleted' && (
                                      <Tooltip label="從分享中移除" withArrow>
                                        <ActionIcon
                                          variant="subtle"
                                          color="red"
                                          size="sm"
                                          aria-label="從分享中移除"
                                          onClick={() => confirmDeleteFile(share, f.id, f.filename)}
                                        >
                                          <IconTrash size={16} />
                                        </ActionIcon>
                                      </Tooltip>
                                    )}
                                  </Group>
                                ))
                              )}
                              {liveFiles.length > 1 && share.status !== 'deleted' && (
                                <Text size="xs" c="dimmed" mt={4}>
                                  此順序就是對方看到的順序，也是「全部下載」壓縮檔內的順序。
                                </Text>
                              )}
                            </Stack>
                          </Collapse>
                        </Table.Td>
                      </Table.Tr>
                    </Fragment>
                  );
                })
              )}
            </Table.Tbody>
          </Table>

          <Group justify="space-between" mt="md" align="center">
            <Text size="sm" c="dimmed" fw={500}>
              共 {total} 個分享
            </Text>
            <Pagination value={page} onChange={setPage} total={totalPages} size="md" radius="md" />
          </Group>
        </Stack>
      </Card>
    </Stack>
  );
}

function UploadProgress({ uploads }: { uploads: UploadState[] }) {
  if (!uploads.length) return null;
  return (
    <Stack gap="xs">
      {uploads.map((u) => (
        <div key={u.name}>
          <Group justify="space-between" gap="xs">
            <Text size="xs" style={{ wordBreak: 'break-all' }}>
              {u.name}
            </Text>
            <Text size="xs" c={u.error ? 'red' : u.done ? 'green' : 'dimmed'}>
              {u.error ?? (u.done ? '完成' : `${u.percent}%`)}
            </Text>
          </Group>
          <Progress
            value={u.percent}
            color={u.error ? 'red' : u.done ? 'green' : 'blue'}
            striped={!u.done && !u.error}
            animated={!u.done && !u.error}
            size="md"
            radius="md"
          />
        </div>
      ))}
    </Stack>
  );
}

function AddFilesForm({
  share,
  onUpload,
  onCancel,
}: {
  share: FileShare;
  onUpload: (files: File[]) => Promise<void>;
  onCancel: () => void;
}) {
  const [chosen, setChosen] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        新加入的檔案會使用 <Text span fw={600}>{share.code}</Text> 既有的連結與 PIN
        碼，不需要另外通知對方新的 PIN 碼。
      </Text>
      <FileInput
        label="選擇檔案（可多選）"
        placeholder="點此選擇檔案"
        value={chosen}
        onChange={setChosen}
        multiple
        clearable
        data-autofocus
      />
      <Group justify="flex-end" gap="sm">
        <Button variant="default" onClick={onCancel} disabled={busy}>
          取消
        </Button>
        <Button
          loading={busy}
          disabled={!chosen.length}
          onClick={async () => {
            setBusy(true);
            await onUpload(chosen);
            setBusy(false);
          }}
        >
          上傳
        </Button>
      </Group>
    </Stack>
  );
}
