import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  CopyButton,
  Group,
  LoadingOverlay,
  Pagination,
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
  IconBan,
  IconCalendar,
  IconCheck,
  IconChevronDown,
  IconChevronUp,
  IconCopy,
  IconPencil,
  IconQrcode,
  IconRefresh,
  IconSelector,
} from '@tabler/icons-react';
import dayjs from 'dayjs';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { QrCodeDialog } from '../components/QrCodeDialog';
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

/** 原始網址欄：網域放大、全網址縮小，滑過看完整內容——不必再冒險開編輯視窗。 */
function TargetCell({ url }: { url: string }) {
  let host = url;
  try {
    host = new URL(url).hostname;
  } catch {
    // 非標準網址就原樣顯示
  }
  return (
    <Tooltip label={url} withArrow multiline maw={480} position="top-start">
      <div>
        <Text size="sm" fw={600}>
          {host}
        </Text>
        <Text size="xs" c="dimmed" lineClamp={1} style={{ wordBreak: 'break-all' }}>
          {url}
        </Text>
      </div>
    </Tooltip>
  );
}

function statusBadge(link: Link) {
  if (link.is_expired) return <Badge color="orange">已過期</Badge>;
  if (link.status === 'active') return <Badge color="green">使用中</Badge>;
  if (link.status === 'disabled') return <Badge color="gray">已停用</Badge>;
  return <Badge color="orange">已過期</Badge>;
}

type SortField = 'created_at' | 'click_count' | 'expires_at' | 'code';

export function ManagePage() {
  const [qrLink, setQrLink] = useState<Link | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(false);

  // 篩選、排序與頁碼都放進網址：F5 不歸零，篩選結果的網址可以直接丟給同事。
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get('q') ?? '';
  const tagId = searchParams.get('tag');
  const status = (searchParams.get('status') as StatusFilter) ?? 'all';
  const sort = (searchParams.get('sort') as SortField) ?? 'created_at';
  const order = searchParams.get('order') === 'asc' ? 'asc' : 'desc';
  const page = Math.max(1, Number(searchParams.get('page') ?? '1') || 1);

  function updateParams(patch: Record<string, string | null>) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v === null || v === '') next.delete(k);
          else next.set(k, v);
        }
        return next;
      },
      { replace: true },
    );
  }

  // 搜尋框有自己的輸入狀態，停止輸入 350ms 才真正送出查詢。
  const [queryInput, setQueryInput] = useState(query);
  useEffect(() => {
    const t = setTimeout(() => {
      if (queryInput.trim() !== query) {
        updateParams({ q: queryInput.trim() || null, page: null });
      }
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryInput]);

  const [items, setItems] = useState<Link[]>([]);
  const [total, setTotal] = useState(0);

  const limit = 20;
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

  // 逐鍵搜尋下慢的舊回應可能晚到，序號守門避免舊資料蓋掉新資料。
  const loadSeq = useRef(0);

  async function load() {
    const seq = ++loadSeq.current;
    setLoading(true);
    try {
      const res = await api.listLinks({
        query: query.trim() || undefined,
        tag_id: tagId ? Number(tagId) : undefined,
        status,
        sort,
        order,
        limit,
        offset,
      });
      if (seq !== loadSeq.current) return;
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      const msg = e instanceof Error ? e.message : '載入失敗';
      notifications.show({ color: 'red', message: msg });
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, status, tagId, query, sort, order]);

  function toggleSort(field: SortField) {
    const nextOrder = sort === field && order === 'desc' ? 'asc' : 'desc';
    updateParams({ sort: field, order: nextOrder, page: null });
  }

  function SortableTh({ field, w, children }: { field: SortField; w?: number; children: React.ReactNode }) {
    const active = sort === field;
    return (
      <Table.Th
        style={{ width: w, fontWeight: 600, cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
        aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : undefined}
        onClick={() => toggleSort(field)}
      >
        <Group gap={2} wrap="nowrap">
          {children}
          {active ? (
            order === 'asc' ? (
              <IconChevronUp size={14} />
            ) : (
              <IconChevronDown size={14} />
            )
          ) : (
            <IconSelector size={14} opacity={0.35} />
          )}
        </Group>
      </Table.Th>
    );
  }

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
              if (msg.startsWith('此網址已建立過短網址：')) {
                const existingUrl = msg.replace('此網址已建立過短網址：', '').trim();
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
              placeholder="代碼、網址或備註（自動搜尋）"
              value={queryInput}
              onChange={(e) => setQueryInput(e.currentTarget.value)}
              size="md"
              radius="md"
            />
            <Select
              label="標籤"
              data={tagOptions}
              value={tagId ?? ''}
              onChange={(v) => updateParams({ tag: v && v !== '' ? v : null, page: null })}
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
              onChange={(v) => updateParams({ status: v && v !== 'all' ? v : null, page: null })}
              size="md"
              radius="md"
            />
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
        <Box pos="relative">
          <LoadingOverlay visible={loading && items.length > 0} zIndex={10} overlayProps={{ blur: 1 }} />
          <Table.ScrollContainer minWidth={1080}>
          <Table highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <SortableTh field="code" w={80}>代碼</SortableTh>
              <Table.Th style={{ width: '210px', fontWeight: 600 }}>短網址</Table.Th>
              <Table.Th style={{ fontWeight: 600 }}>原始網址</Table.Th>
              <Table.Th style={{ width: '120px', fontWeight: 600 }}>標籤</Table.Th>
              <SortableTh field="created_at" w={150}>建立時間</SortableTh>
              <SortableTh field="expires_at" w={150}>有效期限</SortableTh>
              <Table.Th style={{ width: '100px', fontWeight: 600 }}>狀態</Table.Th>
              <SortableTh field="click_count" w={110}>點擊次數</SortableTh>
              <Table.Th style={{ width: '100px' }}>操作</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loading && items.length === 0 ? (
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
                    <Group gap={4} wrap="nowrap">
                      <Text size="sm" style={{ wordBreak: 'break-all', flex: 1 }}>
                        {l.short_url}
                      </Text>
                      <CopyButton value={l.short_url} timeout={1500}>
                        {({ copied, copy }) => (
                          <Tooltip label={copied ? '已複製' : '複製短網址'} withArrow>
                            <ActionIcon
                              variant="subtle"
                              color={copied ? 'green' : 'blue'}
                              onClick={copy}
                              aria-label={`複製短網址 ${l.short_url}`}
                              size="md"
                            >
                              {copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                            </ActionIcon>
                          </Tooltip>
                        )}
                      </CopyButton>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <TargetCell url={l.original_url} />
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
                    <Text fw={600} size="sm" c="blue" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {l.click_count.toLocaleString()}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <Tooltip label="QR Code 產生器" withArrow>
                        <ActionIcon
                          variant="subtle"
                          color="blue"
                          onClick={() => setQrLink(l)}
                          aria-label={`${l.code} 的 QR Code`}
                          size="md"
                          radius="md"
                        >
                          <IconQrcode size={18} />
                        </ActionIcon>
                      </Tooltip>
                      {l.status === 'disabled' ? (
                        <Tooltip label="重新啟用" withArrow>
                          <ActionIcon
                            variant="subtle"
                            color="green"
                            onClick={() => confirmEnable(l.code)}
                            aria-label={`啟用 ${l.code}`}
                            size="md"
                            radius="md"
                          >
                            <IconCheck size={18} />
                          </ActionIcon>
                        </Tooltip>
                      ) : (
                        <>
                          {canEditExpiry(l) && (
                            <>
                              <Tooltip label="編輯原始網址" withArrow>
                                <ActionIcon
                                  variant="subtle"
                                  color="blue"
                                  onClick={() => openEditUrlModal(l)}
                                  aria-label={`編輯 ${l.code} 的原始網址`}
                                  size="md"
                                  radius="md"
                                >
                                  <IconPencil size={18} />
                                </ActionIcon>
                              </Tooltip>
                              <Tooltip label="編輯有效期限" withArrow>
                                <ActionIcon
                                  variant="subtle"
                                  color="blue"
                                  onClick={() => openEditExpiryModal(l)}
                                  aria-label={`編輯 ${l.code} 的有效期限`}
                                  size="md"
                                  radius="md"
                                >
                                  <IconCalendar size={18} />
                                </ActionIcon>
                              </Tooltip>
                            </>
                          )}
                          <Tooltip label="停用" withArrow>
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              onClick={() => confirmDisable(l.code)}
                              aria-label={`停用 ${l.code}`}
                              size="md"
                              radius="md"
                            >
                              <IconBan size={18} />
                            </ActionIcon>
                          </Tooltip>
                        </>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
          </Table>
          </Table.ScrollContainer>
        </Box>

        <Group justify="space-between" mt="xl" align="center">
          <Text size="sm" c="dimmed" fw={500}>
            共 {total} 筆短網址
          </Text>
          <Pagination
            value={page}
            onChange={(p) => updateParams({ page: p > 1 ? String(p) : null })}
            total={totalPages}
            size="md"
            radius="md"
          />
        </Group>
      </Card>
      <QrCodeDialog
        opened={qrLink !== null}
        onClose={() => setQrLink(null)}
        code={qrLink?.code ?? ''}
        shortUrl={qrLink?.short_url ?? ''}
        qrPin={qrLink?.qr_pin}
      />
    </Stack>
  );
}

