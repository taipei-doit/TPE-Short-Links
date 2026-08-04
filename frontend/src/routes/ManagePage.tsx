import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { DateTimePicker } from '@mantine/dates';
import '@mantine/dates/styles.css';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconBan, IconCalendar, IconCheck, IconPencil, IconRefresh } from '@tabler/icons-react';
import dayjs from 'dayjs';
import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';
import type { Link, Tag } from '../api/types';

type StatusFilter = 'active' | 'disabled' | 'expired' | 'all';

function EditExpiryForm({
  link,
  initialExpiresAt,
  onSave,
  onCancel,
}: {
  link: Link;
  initialExpiresAt: Date | null;
  onSave: (expiresAt: Date | null) => Promise<void>;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<'permanent' | 'datetime'>(initialExpiresAt ? 'datetime' : 'permanent');
  const [expiresAt, setExpiresAt] = useState<Date | null>(initialExpiresAt);
  const [saving, setSaving] = useState(false);
  return (
    <Stack gap="md">
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
        <DateTimePicker
          label="到期時間"
          value={expiresAt}
          onChange={setExpiresAt}
        />
      )}
      <Group justify="flex-end" gap="sm">
        <Button variant="default" onClick={onCancel}>
          取消
        </Button>
        <Button
          loading={saving}
          onClick={async () => {
            setSaving(true);
            await onSave(mode === 'permanent' ? null : expiresAt);
            setSaving(false);
          }}
        >
          儲存
        </Button>
      </Group>
    </Stack>
  );
}

function EditUrlForm({
  link,
  onSave,
  onCancel,
}: {
  link: Link;
  onSave: (originalUrl: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [url, setUrl] = useState(link.original_url);
  const [saving, setSaving] = useState(false);

  const urlError = (() => {
    if (!url.trim()) return '請輸入原始網址';
    try {
      const u = new URL(url.trim());
      if (u.protocol !== 'https:') return '必須為 https:// 開頭（預設不允許 http://）';
      return null;
    } catch {
      return '必須為有效的完整網址';
    }
  })();

  return (
    <Stack gap="md">
      <TextInput
        label="原始網址"
        placeholder="https://example.com/some/path"
        value={url}
        onChange={(e) => setUrl(e.currentTarget.value)}
        error={url !== link.original_url ? urlError : null}
        data-autofocus
      />
      <Text size="xs" c="dimmed">
        短網址代碼 <Text span fw={600} style={{ fontFamily: 'monospace' }}>{link.code}</Text>{' '}
        不變，儲存後會改為導向新的網址。
      </Text>
      <Group justify="flex-end" gap="sm">
        <Button variant="default" onClick={onCancel}>
          取消
        </Button>
        <Button
          loading={saving}
          disabled={!!urlError || url.trim() === link.original_url}
          onClick={async () => {
            setSaving(true);
            await onSave(url.trim());
            setSaving(false);
          }}
        >
          儲存
        </Button>
      </Group>
    </Stack>
  );
}

function statusBadge(link: Link) {
  if (link.is_expired) return <Badge color="orange">已過期</Badge>;
  if (link.status === 'active') return <Badge color="green">使用中</Badge>;
  if (link.status === 'disabled') return <Badge color="gray">已停用</Badge>;
  return <Badge color="orange">已過期</Badge>;
}

export function ManagePage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(false);

  const [query, setQuery] = useState('');
  const [tagId, setTagId] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusFilter>('all');

  const [items, setItems] = useState<Link[]>([]);
  const [total, setTotal] = useState(0);

  const limit = 20;
  const [page, setPage] = useState(1);
  const offset = (page - 1) * limit;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  useEffect(() => {
    api
      .getTags()
      .then(setTags)
      .catch((e) => notifications.show({ color: 'red', message: e.message }));
  }, []);

  const tagOptions = useMemo(
    () => [{ value: '', label: '全部標籤' }, ...tags.map((t) => ({ value: String(t.id), label: t.name }))],
    [tags],
  );

  async function load() {
    setLoading(true);
    try {
      const res = await api.listLinks({
        query: query.trim() || undefined,
        tag_id: tagId ? Number(tagId) : undefined,
        status,
        limit,
        offset,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      const msg = e instanceof Error ? e.message : '載入失敗';
      notifications.show({ color: 'red', message: msg });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, status, tagId, query]);

  const canEditExpiry = (l: Link) => l.status === 'active' || l.is_expired;

  function confirmEnable(code: string) {
    modals.openConfirmModal({
      title: '啟用短網址',
      children: (
        <Text size="sm">
          此短網址將重新啟用。若到期時間已過，會顯示為「已過期」，需延長有效期限後才能繼續轉址。
        </Text>
      ),
      labels: { confirm: '啟用', cancel: '取消' },
      confirmProps: { color: 'green' },
      onConfirm: async () => {
        try {
          await api.enableLink(code);
          notifications.show({ color: 'green', message: '短網址已啟用' });
          load();
        } catch (e) {
          notifications.show({ color: 'red', message: e instanceof Error ? e.message : '操作失敗' });
        }
      },
    });
  }

  function openEditUrlModal(l: Link) {
    modals.open({
      title: '編輯原始網址',
      size: 'lg',
      children: (
        <EditUrlForm
          link={l}
          onSave={async (newUrl) => {
            try {
              await api.updateLinkUrl(l.code, newUrl);
              notifications.show({ color: 'green', message: '原始網址已更新' });
              modals.closeAll();
              load();
            } catch (e) {
              const msg = e instanceof Error ? e.message : '操作失敗';
              if (msg.startsWith('A short link already exists for this URL:')) {
                const existingUrl = msg.replace('A short link already exists for this URL:', '').trim();
                notifications.show({
                  color: 'red',
                  message: `這個網址已經有使用中的短網址：${existingUrl}`,
                });
              } else {
                notifications.show({ color: 'red', message: msg });
              }
            }
          }}
          onCancel={() => modals.closeAll()}
        />
      ),
    });
  }

  function openEditExpiryModal(l: Link) {
    modals.open({
      title: '編輯有效期限',
      size: 'md',
      children: (
        <EditExpiryForm
          link={l}
          initialExpiresAt={l.expires_at ? new Date(l.expires_at) : null}
          onSave={async (newExpiresAt) => {
            try {
              await api.updateLinkExpiry(l.code, newExpiresAt ? newExpiresAt.toISOString() : null);
              notifications.show({ color: 'green', message: '有效期限已更新' });
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

  const [exporting, setExporting] = useState(false);

  async function exportCsv() {
    setExporting(true);
    try {
      await api.exportLinksCsv({
        query: query.trim() || undefined,
        tag_id: tagId ? Number(tagId) : undefined,
        status,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : '匯出失敗';
      notifications.show({ color: 'red', message: msg });
    } finally {
      setExporting(false);
    }
  }
  async function confirmDisable(code: string) {
    modals.openConfirmModal({
      title: '停用短網址？',
      children: (
        <Text size="sm">
          將把 <Text span fw={600}>{code}</Text> 標記為停用。此代碼日後不會再重新配發使用。
        </Text>
      ),
      labels: { confirm: '停用', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.disableLink(code);
          notifications.show({ color: 'green', message: '已停用' });
          load();
        } catch (e) {
          const msg = e instanceof Error ? e.message : '停用失敗';
          notifications.show({ color: 'red', message: msg });
        }
      },
    });
  }

  return (
    <Stack gap="xl">
      <Group justify="space-between" align="center">
        <div>
          <Title order={1} style={{ marginBottom: '8px', fontWeight: 700 }}>
            管理短網址
          </Title>
          <Text c="dimmed" size="sm">
            檢視、搜尋並管理您的短網址
          </Text>
        </div>
        <Group gap="sm">
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
          <Button variant="outline" size="md" radius="md" loading={exporting} onClick={exportCsv}>
            匯出 CSV
          </Button>
        </Group>
      </Group>

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
        <Stack gap="md">
          <Group align="flex-end" grow>
            <TextInput
              label="搜尋"
              placeholder="代碼、網址或備註"
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  setPage(1);
                  load();
                }
              }}
              size="md"
              radius="md"
            />
            <Select
              label="標籤"
              data={tagOptions}
              value={tagId ?? ''}
              onChange={(v) => {
                setPage(1);
                setTagId(v && v !== '' ? v : null);
              }}
              searchable
              nothingFoundMessage="查無符合的標籤"
              maxDropdownHeight={320}
              size="md"
              radius="md"
            />
            <Select
              label="狀態"
              data={[
                { value: 'all', label: '全部' },
                { value: 'active', label: '使用中' },
                { value: 'expired', label: '已過期' },
                { value: 'disabled', label: '已停用' },
              ]}
              value={status}
              onChange={(v) => {
                setPage(1);
                setStatus((v as StatusFilter) ?? 'all');
              }}
              size="md"
              radius="md"
            />
            <Button
              variant="filled"
              disabled={loading}
              onClick={() => {
                setPage(1);
                load();
              }}
              size="md"
              radius="md"
              style={{
                background: 'linear-gradient(135deg, var(--mantine-color-blue-6) 0%, var(--mantine-color-blue-7) 100%)',
                fontWeight: 600,
              }}
            >
              搜尋
            </Button>
          </Group>
        </Stack>
      </Card>

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
        <Table highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: '80px', fontWeight: 600 }}>代碼</Table.Th>
              <Table.Th style={{ width: '200px', fontWeight: 600 }}>短網址</Table.Th>
              <Table.Th style={{ fontWeight: 600 }}>原始網址</Table.Th>
              <Table.Th style={{ width: '120px', fontWeight: 600 }}>標籤</Table.Th>
              <Table.Th style={{ width: '140px', fontWeight: 600 }}>建立時間</Table.Th>
              <Table.Th style={{ width: '140px', fontWeight: 600 }}>有效期限</Table.Th>
              <Table.Th style={{ width: '100px', fontWeight: 600 }}>狀態</Table.Th>
              <Table.Th style={{ width: '100px', fontWeight: 600 }}>點擊次數</Table.Th>
              <Table.Th style={{ width: '100px' }}>操作</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loading ? (
              <Table.Tr>
                <Table.Td colSpan={9}>
                  <Text c="dimmed" size="sm" ta="center" py="xl">
                    載入中…
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : items.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={9}>
                  <Text c="dimmed" size="sm" ta="center" py="xl">
                    {query || tagId || status !== 'all'
                      ? '查無符合篩選條件的資料'
                      : '目前尚無短網址，請至「建立短網址」頁面建立第一筆。'}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              items.map((l) => (
                <Table.Tr key={l.id} style={{ transition: 'background-color 0.2s' }}>
                  <Table.Td>
                    <Text
                      fw={700}
                      size="sm"
                      style={{
                        fontFamily: 'monospace',
                        background: 'var(--mantine-color-gray-1)',
                        padding: '4px 8px',
                        borderRadius: 'var(--mantine-radius-sm)',
                        display: 'inline-block',
                      }}
                    >
                      {l.code}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text
                      component="a"
                      href={l.short_url}
                      target="_blank"
                      rel="noreferrer"
                      size="sm"
                      style={{ wordBreak: 'break-all', color: 'var(--mantine-color-blue-7)' }}
                    >
                      {l.short_url}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text lineClamp={2} size="sm" style={{ wordBreak: 'break-all' }}>
                      {l.original_url}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light" color="blue" size="sm">
                      {l.tag_name}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{dayjs(l.created_at).format('YYYY-MM-DD HH:mm')}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{l.expires_at ? dayjs(l.expires_at).format('YYYY-MM-DD HH:mm') : '永久有效'}</Text>
                  </Table.Td>
                  <Table.Td>{statusBadge(l)}</Table.Td>
                  <Table.Td>
                    <Text fw={600} size="sm" c="blue">
                      {l.click_count.toLocaleString()}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      {l.status === 'disabled' ? (
                        <ActionIcon
                          variant="subtle"
                          color="green"
                          onClick={() => confirmEnable(l.code)}
                          aria-label="啟用"
                          size="md"
                          radius="md"
                        >
                          <IconCheck size={18} />
                        </ActionIcon>
                      ) : (
                        <>
                          {canEditExpiry(l) && (
                            <>
                              <ActionIcon
                                variant="subtle"
                                color="blue"
                                onClick={() => openEditUrlModal(l)}
                                aria-label="編輯原始網址"
                                size="md"
                                radius="md"
                              >
                                <IconPencil size={18} />
                              </ActionIcon>
                              <ActionIcon
                                variant="subtle"
                                color="blue"
                                onClick={() => openEditExpiryModal(l)}
                                aria-label="編輯有效期限"
                                size="md"
                                radius="md"
                              >
                                <IconCalendar size={18} />
                              </ActionIcon>
                            </>
                          )}
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            onClick={() => confirmDisable(l.code)}
                            aria-label="停用"
                            size="md"
                            radius="md"
                          >
                            <IconBan size={18} />
                          </ActionIcon>
                        </>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>

        <Group justify="space-between" mt="xl" align="center">
          <Text size="sm" c="dimmed" fw={500}>
            共 {total} 筆短網址
          </Text>
          <Pagination value={page} onChange={setPage} total={totalPages} size="md" radius="md" />
        </Group>
      </Card>
    </Stack>
  );
}

