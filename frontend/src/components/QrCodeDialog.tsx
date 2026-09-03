import { ActionIcon, Button, CopyButton, Group, Modal, Stack, Text, Tooltip } from '@mantine/core';
import { IconCheck, IconCopy, IconExternalLink } from '@tabler/icons-react';
import { useMemo } from 'react';
import { Link } from 'react-router-dom';

/** QR 產生器的公開網址一律用正式網域，貼給局處不會露出 web.app。 */
const STUDIO_BASE = 'https://url.taipei/qr';

function CopyRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
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

export interface QrCodeDialogProps {
  opened: boolean;
  onClose: () => void;
  /** 短碼（顯示用） */
  code: string;
  /** 完整短網址，用來推導產生器路徑 */
  shortUrl: string;
  /** 短網址的 QR 解鎖 PIN；檔案分享沒有（用分享本身的下載 PIN） */
  qrPin?: string;
}

/**
 * 管理端的 QR 按鈕不再直接產圖：改成把「產生器網址 + PIN」交給承辦，
 * 由局處自己到公開產生器挑樣式。已登入的管理員開產生器會自動解鎖。
 */
export function QrCodeDialog({ opened, onClose, code, shortUrl, qrPin }: QrCodeDialogProps) {
  const studioPath = useMemo(() => {
    try {
      const p = new URL(shortUrl).pathname.replace(/^\/+/, '');
      return /^(f\/)?[A-Za-z0-9_-]{1,32}$/.test(p) ? p : null;
    } catch {
      return null;
    }
  }, [shortUrl]);

  if (!studioPath) return null;
  const studioUrl = `${STUDIO_BASE}/${studioPath}`;
  const combined = qrPin
    ? `QR Code 產生器：${studioUrl}\nPIN 碼：${qrPin}`
    : `QR Code 產生器：${studioUrl}`;

  return (
    <Modal opened={opened} onClose={onClose} title={`產生 QR Code（${code}）`} size="lg" radius="md" centered>
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          請將以下網址與 PIN 碼提供給需要產製 QR Code 的機關同仁。開啟網址、輸入 PIN
          後即可挑選樣式並下載；您目前已登入，直接開啟不需輸入 PIN。
        </Text>
        <CopyRow label="QR Code 產生器網址" value={studioUrl} />
        {qrPin ? (
          <CopyRow label="PIN 碼" value={qrPin} mono />
        ) : (
          <Text size="sm" c="dimmed">
            這是檔案分享連結：產生器的 PIN 就是該分享的下載 PIN 碼（建立或重新產生時顯示的那組）。
          </Text>
        )}
        <Group justify="space-between">
          <CopyButton value={combined} timeout={2000}>
            {({ copied, copy }) => (
              <Button
                variant="light"
                color={copied ? 'green' : 'blue'}
                leftSection={copied ? <IconCheck size={18} /> : <IconCopy size={18} />}
                onClick={copy}
              >
                {copied ? '已複製' : qrPin ? '一併複製網址與 PIN 碼' : '複製網址'}
              </Button>
            )}
          </CopyButton>
          <Group gap="sm">
            <Button variant="default" onClick={onClose}>
              關閉
            </Button>
            <Button
              component={Link}
              to={`/qr/${studioPath}`}
              leftSection={<IconExternalLink size={18} />}
              onClick={onClose}
            >
              開啟產生器
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
