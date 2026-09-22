import { ActionIcon, Group, Text, Tooltip } from '@mantine/core';
import { IconWorldSearch } from '@tabler/icons-react';
import dayjs from 'dayjs';

import type { DomainStatus } from '../api/types';

/** 網域註冊狀態的最小共同形狀：建立頁的預查結果與列表裡的短網址都符合。 */
export type DomainLike = {
  name: string | null;
  status: DomainStatus | null;
  expires_at: string | null;
  checked_at: string | null;
  detail?: string;
};

/** 到期前多少天內用警示色提醒（網域續約通常在到期前一兩個月辦）。 */
const WARN_DAYS = 60;

export function domainCapDate(d: DomainLike | null | undefined): Date | null {
  if (!d || d.status !== 'ok' || !d.expires_at) return null;
  return new Date(d.expires_at);
}

export function domainSummary(d: DomainLike | null | undefined): { text: string; color: string } {
  if (!d || d.status === null) return { text: '網域註冊期限：尚未查詢', color: 'dimmed' };
  const name = d.name ?? '';
  switch (d.status) {
    case 'ok': {
      const cap = dayjs(d.expires_at);
      const daysLeft = cap.diff(dayjs(), 'day');
      if (daysLeft < 0) return { text: `網域 ${name} 註冊已於 ${cap.format('YYYY-MM-DD')} 到期`, color: 'red' };
      if (daysLeft <= WARN_DAYS)
        return { text: `網域 ${name} 註冊至 ${cap.format('YYYY-MM-DD')}（剩 ${daysLeft} 天）`, color: 'orange' };
      return { text: `網域 ${name} 註冊至 ${cap.format('YYYY-MM-DD')}`, color: 'dimmed' };
    }
    case 'unknown':
      return { text: `網域 ${name}：註冊機構未公開到期日`, color: 'dimmed' };
    case 'error':
      return { text: `網域 ${name}：暫時查不到註冊資料`, color: 'orange' };
    case 'not_applicable':
      return { text: '不適用網域註冊查詢（IP 位址）', color: 'dimmed' };
    default:
      return { text: '網域註冊期限：尚未查詢', color: 'dimmed' };
  }
}

/** 一行網域狀態＋刷新鈕；列表每列與建立頁都用它，長相一致。 */
export function DomainStatusLine({
  domain,
  onRefresh,
  refreshing = false,
  size = 'xs',
}: {
  domain: DomainLike | null | undefined;
  onRefresh?: () => void;
  refreshing?: boolean;
  size?: 'xs' | 'sm';
}) {
  const { text, color } = domainSummary(domain);
  const tooltip = [
    domain?.detail,
    domain?.checked_at ? `上次查詢 ${dayjs(domain.checked_at).format('YYYY-MM-DD HH:mm')}` : null,
  ]
    .filter(Boolean)
    .join('；');
  return (
    <Group gap={4} wrap="nowrap">
      <Tooltip label={tooltip || text} withArrow multiline maw={360} disabled={!tooltip}>
        <Text size={size} c={color} lineClamp={1}>
          {text}
        </Text>
      </Tooltip>
      {onRefresh ? (
        <Tooltip label="重新查詢網域註冊有效期（只更新上限，不會改動短網址的到期日）" withArrow>
          <ActionIcon
            variant="subtle"
            color="blue"
            size="sm"
            loading={refreshing}
            onClick={onRefresh}
            aria-label={`重新查詢 ${domain?.name ?? '網域'} 的註冊有效期`}
          >
            <IconWorldSearch size={14} />
          </ActionIcon>
        </Tooltip>
      ) : null}
    </Group>
  );
}
