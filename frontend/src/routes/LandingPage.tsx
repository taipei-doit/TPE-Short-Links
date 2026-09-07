import { Anchor, Box, Button, Divider, Group, Stack, Text, Title } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { Link } from 'react-router-dom';

import { EMBLEM_COLORS, INK, SERIF_TC } from '../publicTheme';

/** 市徽四色簽名色條：整頁唯一的一筆亮色。 */
export function EmblemStripe({ width = 200 }: { width?: number }) {
  return (
    <Group gap={0} style={{ width, borderRadius: 2, overflow: 'hidden' }} aria-hidden>
      {EMBLEM_COLORS.map((c) => (
        <Box key={c} style={{ flex: 1, height: 4, background: c }} />
      ))}
    </Group>
  );
}

/** 條文式段落：政府聲明的原生形式，「一、二、三」是真正的條次而非裝飾。 */
function Clause({ no, children }: { no: string; children: React.ReactNode }) {
  return (
    <Group align="flex-start" gap="sm" wrap="nowrap">
      <Text fw={700} style={{ fontFamily: SERIF_TC, color: INK, flex: 'none', lineHeight: 1.9 }}>
        {no}、
      </Text>
      <Text size="md" c="dark.6" style={{ lineHeight: 1.9 }}>
        {children}
      </Text>
    </Group>
  );
}

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

export function LandingPage() {
  return (
    <Stack gap={56} style={{ maxWidth: '40em', margin: '0 auto' }}>
      {/* 銜名＋大標：公文的開頭 */}
      <Stack gap="md" pt="md">
        <Text size="sm" fw={600} c="dark.4" style={{ letterSpacing: 4 }}>
          臺北市政府資訊局
        </Text>
        <Title
          order={1}
          style={{
            fontFamily: SERIF_TC,
            color: INK,
            fontWeight: 700,
            fontSize: 'clamp(2rem, 5.5vw, 3rem)',
            lineHeight: 1.35,
            letterSpacing: 2,
          }}
        >
          臺北市政府官方短網址
        </Title>
        <Group gap="md" align="center">
          <Text fw={700} size="xl" style={{ color: INK, letterSpacing: 1 }}>
            url.taipei
          </Text>
          <EmblemStripe width={168} />
        </Group>
        <Text size="md" c="dark.6" style={{ lineHeight: 1.9, maxWidth: '38em' }}>
          凡是以 url.taipei 開頭的連結與 QR
          Code，都由臺北市政府各機關建立、經本府控管，用於市政宣導、活動通知與便民服務。
          收到這樣的連結，您可以先在查核頁確認它將前往哪個網站，再決定是否開啟。
        </Text>
        <Group mt={4}>
          <Button
            component={Link}
            to="/check"
            size="lg"
            radius="md"
            leftSection={<IconSearch size={20} />}
            style={{ fontWeight: 700, minHeight: 48 }}
          >
            查核短網址
          </Button>
        </Group>
      </Stack>

      {/* 三項承諾：條文式 */}
      <Stack gap="md">
        <SectionTitle>這項服務向您承諾</SectionTitle>
        <Divider color="gray.3" />
        <Stack gap="sm">
          <Clause no="一">
            本服務由臺北市政府資訊局自行建置與維運，url.taipei
            網域為臺北市政府所有，並非商業或第三方短網址服務。
          </Clause>
          <Clause no="二">
            短網址僅限市府機關建立，目的網址全程受本府控管；失效或不存在的連結一律導向官方說明頁，不會轉往任何其他網站。
          </Clause>
          <Clause no="三">
            代碼一經使用即永久封存、不再重複配發——您以前掃過的
            url.taipei 連結，不會在失效後被其他人接手使用。
          </Clause>
        </Stack>
      </Stack>

      {/* 查核入口：左界線帶狀區 */}
      <Box
        style={{
          background: '#F1F6FA',
          borderLeft: `3px solid ${INK}`,
          padding: '1.5rem 1.75rem',
          borderRadius: '0 var(--mantine-radius-md) var(--mantine-radius-md) 0',
        }}
      >
        <Stack gap={6}>
          <Text fw={700} size="lg" style={{ fontFamily: SERIF_TC, color: INK }}>
            收到可疑連結？先查再點
          </Text>
          <Text size="sm" c="dark.6" style={{ lineHeight: 1.9 }}>
            在查核頁輸入短網址或代碼，即可確認該連結是否為本府所發、以及它將前往的網站。
            查無資料的代碼代表本府從未發出，請提高警覺、切勿開啟。
          </Text>
          <Group mt={6}>
            <Button component={Link} to="/check" radius="md" style={{ minHeight: 44 }}>
              前往短網址查核
            </Button>
          </Group>
        </Stack>
      </Box>

      {/* 隱私權宣告 */}
      <Stack gap="md" id="privacy">
        <SectionTitle>隱私權宣告</SectionTitle>
        <Divider color="gray.3" />
        <Stack gap="sm">
          <Clause no="一">
            本服務於短網址轉址時，僅累計各連結之點擊次數作為流量統計，不蒐集、不識別個別使用者之身分。
          </Clause>
          <Clause no="二">
            基於資訊安全與稽核目的，系統保留必要之連線紀錄（如來源 IP
            位址與存取時間），僅用於資安事件調查與服務維運，不作行銷或個人剖繪之用。
          </Clause>
          <Clause no="三">
            本頁與查核頁不使用追蹤性 Cookie；查核頁之查詢內容不與查詢者之身分連結留存。
          </Clause>
          <Clause no="四">
            短網址轉向之目的網站由各該網站自行營運，其個人資料蒐集與保護措施，請參閱該網站之隱私權政策。
          </Clause>
        </Stack>
      </Stack>

      {/* 聯絡 */}
      <Stack gap="md">
        <SectionTitle>聯絡我們</SectionTitle>
        <Divider color="gray.3" />
        <Text size="md" c="dark.6" style={{ lineHeight: 1.9 }}>
          本服務由
          <Anchor href="https://doit.gov.taipei" target="_blank" rel="noopener" fw={600} c="brand.8">
            臺北市政府資訊局
          </Anchor>
          維運。若您發現可疑的 url.taipei 連結，或對本服務有任何疑問，歡迎透過臺北市民當家熱線
          1999 反映，本府將儘速處理。更多市政資訊請參閱
          <Anchor href="https://www.gov.taipei" target="_blank" rel="noopener" fw={600} c="brand.8">
            臺北市政府全球資訊網
          </Anchor>
          。
        </Text>
      </Stack>
    </Stack>
  );
}
