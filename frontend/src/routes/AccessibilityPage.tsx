import { Divider, Group, Stack, Table, Text, Title } from '@mantine/core';

import { Crumbs } from '../components/Crumbs';
import { INK, SERIF_TC } from '../publicTheme';
import { EmblemStripe } from './LandingPage';

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <Title
      order={2}
      style={{ fontFamily: SERIF_TC, color: INK, fontSize: '1.45rem', fontWeight: 700 }}
    >
      {children}
    </Title>
  );
}

const ACCESS_KEYS = [
  { key: 'Alt + U', area: '上方功能區塊', desc: '網站標題與主要功能選單' },
  { key: 'Alt + C', area: '中央內容區塊', desc: '本頁的主要內容' },
  { key: 'Alt + Z', area: '下方功能區塊', desc: '頁尾聲明與相關連結' },
];

export function AccessibilityPage() {
  return (
    <Stack gap={48} style={{ maxWidth: '40em', margin: '0 auto' }}>
      <Crumbs current="無障礙聲明" />
      <Stack gap="md">
        <Text size="sm" fw={600} c="dark.4" style={{ letterSpacing: 4 }}>
          臺北市政府資訊局
        </Text>
        <Title
          order={1}
          style={{
            fontFamily: SERIF_TC,
            color: INK,
            fontWeight: 700,
            fontSize: 'clamp(1.8rem, 5vw, 2.5rem)',
            lineHeight: 1.35,
            letterSpacing: 2,
          }}
        >
          無障礙聲明
        </Title>
        <EmblemStripe width={168} />
        <Text size="md" c="dark.6" style={{ lineHeight: 1.9 }}>
          本網站依「網站無障礙規範」設計，致力使所有使用者——包含使用螢幕報讀軟體、僅以鍵盤操作或有其他輔助需求的朋友——都能順利查核與使用
          url.taipei 的短網址服務。
        </Text>
      </Stack>

      <Stack gap="md">
        <SectionTitle>快速鍵（Access Keys）設定</SectionTitle>
        <Divider color="gray.3" />
        <Text size="sm" c="dark.6" style={{ lineHeight: 1.9 }}>
          本網站的主要區塊均設有定位點（:::）與快速鍵。Windows 各瀏覽器多以 Alt
          加上代碼操作（Firefox 為 Shift + Alt），macOS 則為 Control + Option 加上代碼。
        </Text>
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: 140, fontWeight: 600 }}>快速鍵</Table.Th>
              <Table.Th style={{ width: 160, fontWeight: 600 }}>區塊</Table.Th>
              <Table.Th style={{ fontWeight: 600 }}>內容</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {ACCESS_KEYS.map((row) => (
              <Table.Tr key={row.key}>
                <Table.Td>
                  <Text size="sm" fw={600} style={{ fontFamily: 'monospace' }}>
                    {row.key}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{row.area}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dark.6">
                    {row.desc}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>

      <Stack gap="md">
        <SectionTitle>鍵盤操作</SectionTitle>
        <Divider color="gray.3" />
        <Stack gap="xs">
          <Text size="sm" c="dark.6" style={{ lineHeight: 1.9 }}>
            本網站所有功能皆可僅以鍵盤完成：以 Tab／Shift + Tab 在項目間移動，Enter
            執行連結或按鈕，方向鍵操作下拉選單，Esc 關閉對話視窗。鍵盤焦點所在的項目會以明顯的外框標示。
          </Text>
        </Stack>
      </Stack>

      <Stack gap="md">
        <SectionTitle>適用範圍與聯絡方式</SectionTitle>
        <Divider color="gray.3" />
        <Group align="flex-start" gap="sm" wrap="nowrap">
          <Text fw={700} style={{ fontFamily: SERIF_TC, color: INK, flex: 'none', lineHeight: 1.9 }}>
            一、
          </Text>
          <Text size="sm" c="dark.6" style={{ lineHeight: 1.9 }}>
            本聲明適用於 url.taipei 之公開頁面（服務首頁、短網址查核與本頁）。
          </Text>
        </Group>
        <Group align="flex-start" gap="sm" wrap="nowrap">
          <Text fw={700} style={{ fontFamily: SERIF_TC, color: INK, flex: 'none', lineHeight: 1.9 }}>
            二、
          </Text>
          <Text size="sm" c="dark.6" style={{ lineHeight: 1.9 }}>
            若您在使用本網站時遭遇任何無障礙相關的困難，或有改善建議，歡迎透過臺北市民當家熱線
            1999 反映，本府將儘速改善。
          </Text>
        </Group>
      </Stack>
    </Stack>
  );
}
