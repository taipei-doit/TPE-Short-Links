import { ActionIcon, Button, Group, Stack, Table, Text, Tooltip } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle, IconWorldSearch } from '@tabler/icons-react';
import dayjs from 'dayjs';

import { api } from '../api/client';
import type { DomainInfo, DomainStatus } from '../api/types';

/** 網域註冊狀態的最小共同形狀：建立頁的預查結果與列表裡的短網址都符合。 */
export type DomainLike = {
  name: string | null;
  status: DomainStatus | null;
  expires_at: string | null;
  checked_at: string | null;
  detail?: string;
  registered_at?: string | null;
  registrar?: string;
  nameservers?: string;
  suspect?: boolean;
  suspect_detail?: string;
};

/** 到期前多少天內用警示色提醒（網域續約通常在到期前一兩個月辦）。 */
const WARN_DAYS = 60;

export function domainCapDate(d: DomainLike | null | undefined): Date | null {
  if (!d || d.status !== 'ok' || !d.expires_at) return null;
  return new Date(d.expires_at);
}

const fmtDate = (v: string | null | undefined) => (v ? dayjs(v).format('YYYY-MM-DD') : '—');

/**
 * 網域註冊狀態的一句話。`compact` 給列表用：欄位窄，網域名稱上一行已經看得到，
 * 只留「註冊至 日期」；完整版給建立頁與提示用。疑似易主永遠最優先、紅色。
 */
export function domainSummary(
  d: DomainLike | null | undefined,
  compact = false,
): { text: string; color: string } {
  if (!d || d.status === null) return { text: compact ? '網域：尚未查詢' : '網域註冊期限：尚未查詢', color: 'dimmed' };
  const name = d.name ?? '';
  if (d.suspect) return { text: compact ? '網域疑似已易主，待確認' : `網域 ${name} 疑似已易主，待確認`, color: 'red' };
  const who = compact ? '' : `網域 ${name} `;
  switch (d.status) {
    case 'ok': {
      const cap = dayjs(d.expires_at);
      const daysLeft = cap.diff(dayjs(), 'day');
      if (daysLeft < 0) return { text: `${who}註冊已於 ${cap.format('YYYY-MM-DD')} 到期`, color: 'red' };
      if (daysLeft <= WARN_DAYS)
        return { text: `${who}註冊至 ${cap.format('YYYY-MM-DD')}（剩 ${daysLeft} 天）`, color: 'orange' };
      return { text: `${who}註冊至 ${cap.format('YYYY-MM-DD')}`, color: 'dimmed' };
    }
    case 'unknown':
      return { text: compact ? '網域未公開到期日' : `網域 ${name}：註冊機構未公開到期日`, color: 'dimmed' };
    case 'error':
      return { text: compact ? '網域暫時查不到' : `網域 ${name}：暫時查不到註冊資料`, color: 'orange' };
    case 'not_applicable':
      return { text: compact ? '不適用（IP 位址）' : '不適用網域註冊查詢（IP 位址）', color: 'dimmed' };
    default:
      return { text: compact ? '網域：尚未查詢' : '網域註冊期限：尚未查詢', color: 'dimmed' };
  }
}

/** 滑過時給管理員看的完整登記資料：誰註冊、何時註冊、註冊商、DNS、上次查詢。 */
function domainTooltip(d: DomainLike | null | undefined): string {
  if (!d) return '';
  return [
    d.suspect && d.suspect_detail ? `⚠ ${d.suspect_detail}` : null,
    domainSummary(d, false).text,
    d.registered_at ? `註冊日期 ${fmtDate(d.registered_at)}` : null,
    d.registrar ? `註冊商 ${d.registrar}` : null,
    d.nameservers ? `DNS ${d.nameservers}` : null,
    d.detail,
    d.checked_at ? `上次查詢 ${dayjs(d.checked_at).format('YYYY-MM-DD HH:mm')}` : null,
  ]
    .filter(Boolean)
    .join('\n');
}

/** 一行網域狀態＋刷新鈕；列表每列與建立頁都用它，長相一致。文字可換行，不截斷。 */
export function DomainStatusLine({
  domain,
  onRefresh,
  onConfirm,
  refreshing = false,
  size = 'xs',
  compact = false,
}: {
  domain: DomainLike | null | undefined;
  onRefresh?: () => void;
  /** 疑似易主時顯示「確認」鈕，交給呼叫端開確認視窗。 */
  onConfirm?: () => void;
  refreshing?: boolean;
  size?: 'xs' | 'sm';
  compact?: boolean;
}) {
  const { text, color } = domainSummary(domain, compact);
  const tooltip = domainTooltip(domain);
  return (
    <Group gap={4} wrap="nowrap" align="flex-start">
      <Tooltip label={tooltip} withArrow multiline maw={420} style={{ whiteSpace: 'pre-line' }} disabled={!tooltip}>
        <Text size={size} c={color} fw={domain?.suspect ? 600 : undefined} style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>
          {domain?.suspect ? '⚠ ' : ''}
          {text}
        </Text>
      </Tooltip>
      {domain?.suspect && onConfirm ? (
        <Button size="compact-xs" color="red" variant="outline" onClick={onConfirm} style={{ flexShrink: 0 }}>
          檢視並確認
        </Button>
      ) : null}
      {onRefresh ? (
        <Tooltip label="重新查詢網域註冊有效期（只更新上限，不會改動短網址的到期日）" withArrow>
          <ActionIcon
            variant="subtle"
            color="blue"
            size="sm"
            loading={refreshing}
            onClick={onRefresh}
            aria-label={`重新查詢 ${domain?.name ?? '網域'} 的註冊有效期`}
            style={{ flexShrink: 0 }}
          >
            <IconWorldSearch size={14} />
          </ActionIcon>
        </Tooltip>
      ) : null}
    </Group>
  );
}

function DiffRow({ label, before, after }: { label: string; before: string; after: string }) {
  const changed = before !== after;
  return (
    <Table.Tr>
      <Table.Td fw={600} style={{ whiteSpace: 'nowrap' }}>{label}</Table.Td>
      <Table.Td style={{ overflowWrap: 'anywhere' }}>{before || '—'}</Table.Td>
      <Table.Td c={changed ? 'red' : undefined} fw={changed ? 600 : undefined} style={{ overflowWrap: 'anywhere' }}>
        {after || '—'}
      </Table.Td>
    </Table.Tr>
  );
}

/**
 * 疑似易主的確認視窗：把「後台原本記錄」與「這次查到」並排，差異標紅，
 * 讓管理員看清楚再決定。按下確認才會採用新資料、解除封鎖。
 */
export function openDomainConfirmModal(d: DomainInfo, onDone: () => void) {
  modals.openConfirmModal({
    title: `網域 ${d.name} 疑似已易主`,
    size: 'lg',
    children: (
      <Stack gap="sm">
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <IconAlertTriangle size={20} color="var(--mantine-color-red-7)" style={{ flexShrink: 0, marginTop: 2 }} />
          <Text size="sm" fw={600} c="red.8">
            {d.suspect_detail}
          </Text>
        </Group>
        <Text size="sm">
          RDAP 只會說明「目前這筆登記到什麼時候」，不會說明登記人是誰。網域到期未續約、被第三方重新註冊時，
          註冊日期會變成最近的日期；原機關續約則註冊日期不變。系統因此把這次查到的資料擱置，
          {' '}<Text span fw={600}>在你確認之前，不能建立或改指向這個網域的短網址</Text>。
        </Text>
        <Table withTableBorder withColumnBorders fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: 90 }}></Table.Th>
              <Table.Th>後台原本記錄</Table.Th>
              <Table.Th>這次查到</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {d.suspect_dropped ? (
              <Table.Tr>
                <Table.Td fw={600}>登記</Table.Td>
                <Table.Td>有（見下列）</Table.Td>
                <Table.Td c="red" fw={600}>註冊機構查無此網域</Table.Td>
              </Table.Tr>
            ) : null}
            <DiffRow label="註冊日期" before={fmtDate(d.registered_at)} after={fmtDate(d.suspect_registered_at)} />
            <DiffRow label="到期日" before={fmtDate(d.expires_at)} after={fmtDate(d.suspect_expires_at)} />
            <DiffRow label="註冊商" before={d.registrar} after={d.suspect_registrar} />
            <DiffRow label="DNS" before={d.nameservers} after={d.suspect_nameservers} />
          </Table.Tbody>
        </Table>
        <Text size="xs" c="dimmed">
          建議先向該網域的管理單位確認續約或轉移情形，或直接開啟該網站查看內容是否仍為原機關所有。
          {d.suspect_at ? ` 首次偵測到變更：${dayjs(d.suspect_at).format('YYYY-MM-DD HH:mm')}。` : ''}
          確認後會記錄確認人與時間。
        </Text>
      </Stack>
    ),
    labels: { confirm: '確認此網域仍為本機關所有', cancel: '先不處理' },
    confirmProps: { color: 'red' },
    onConfirm: async () => {
      try {
        await api.confirmDomain(d.name ?? '');
        notifications.show({ color: 'green', message: `已確認網域 ${d.name}，採用新的登記資料` });
        onDone();
      } catch (e) {
        notifications.show({ color: 'red', message: e instanceof Error ? e.message : '確認失敗' });
      }
    },
  });
}
