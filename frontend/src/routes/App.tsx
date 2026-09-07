import { AppShell, Burger, Button, Container, Drawer, Group, Stack, Text } from '@mantine/core';
import { Suspense, lazy, useEffect, useState } from 'react';
import { IconFileUpload, IconLink, IconListSearch, IconLogout, IconShield, IconTags, IconUsers } from '@tabler/icons-react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
// 公開頁（聲明、查核、無障礙）要最快畫出來，維持同步載入；
// 管理端與 QR 產生器按需載入，公開頁首屏不必下載整個後台。
import { AccessibilityPage } from './AccessibilityPage';
import { CheckPage } from './CheckPage';
import { LandingPage } from './LandingPage';

const AdminsPage = lazy(() => import('./AdminsPage').then((m) => ({ default: m.AdminsPage })));
const BlockedWordsPage = lazy(() => import('./BlockedWordsPage').then((m) => ({ default: m.BlockedWordsPage })));
const CreatePage = lazy(() => import('./CreatePage').then((m) => ({ default: m.CreatePage })));
const FilesPage = lazy(() => import('./FilesPage').then((m) => ({ default: m.FilesPage })));
const LoginPage = lazy(() => import('./LoginPage').then((m) => ({ default: m.LoginPage })));
const ManagePage = lazy(() => import('./ManagePage').then((m) => ({ default: m.ManagePage })));
const QrStudioPage = lazy(() => import('./QrStudioPage').then((m) => ({ default: m.QrStudioPage })));
const TagsPage = lazy(() => import('./TagsPage').then((m) => ({ default: m.TagsPage })));

const routeFallback = <div style={{ padding: '2rem', textAlign: 'center' }}>載入中…</div>;

/** 各頁專屬的 <title>：無障礙檢核要求每頁標題須描述該頁主題。 */
const PAGE_TITLES: Array<[prefix: string, name: string]> = [
  ['/check', '短網址查核'],
  ['/accessibility', '無障礙聲明'],
  ['/qr', 'QR Code 產生器'],
  ['/create', '建立短網址'],
  ['/manage', '管理短網址'],
  ['/files', '檔案分享'],
  ['/tags', '標籤管理'],
  ['/blocked-words', '封鎖字詞管理'],
  ['/admins', '管理員'],
  ['/login', '管理員登入'],
];

export function App() {
  const location = useLocation();
  const { user, loading, signOut } = useAuth();
  const [navOpened, setNavOpened] = useState(false);

  useEffect(() => {
    const hit = PAGE_TITLES.find(
      ([p]) => location.pathname === p || location.pathname.startsWith(`${p}/`),
    );
    document.title = hit ? `${hit[1]}｜臺北市短網址服務` : '臺北市短網址服務';
  }, [location.pathname]);

  // 這些路由「免登入」（查核與聲明頁對民眾公開；QR 產生器則憑 PIN 供機關使用），
  // 不等待登入狀態載入。根路徑只在對外網域（url.taipei，經後端代理）當服務聲明頁；
  // 管理網域的根路徑仍走登入導向。
  const isPublicHost = window.location.hostname === 'url.taipei';
  const isLanding = location.pathname === '/' && isPublicHost;
  const isPublicPage =
    isLanding ||
    ['/qr', '/check', '/accessibility'].some(
      (p) => location.pathname === p || location.pathname.startsWith(`${p}/`),
    );

  const navItems = [
    { path: '/create', label: '建立短網址', icon: IconLink },
    { path: '/manage', label: '管理短網址', icon: IconListSearch },
    { path: '/files', label: '檔案分享', icon: IconFileUpload },
    { path: '/tags', label: '標籤管理', icon: IconTags },
    { path: '/blocked-words', label: '封鎖字詞', icon: IconShield },
    { path: '/admins', label: '管理員', icon: IconUsers },
  ];

  return (
    <AppShell
      header={{ height: 72 }}
      padding="lg"
      styles={{
        main: {
          // 公開頁走紙感白底；管理端維持原本的灰藍漸層。
          background: isPublicPage ? '#FAFBFC' : 'linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%)',
          minHeight: '100vh',
        },
        header: {
          background: 'linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%)',
          borderBottom: '2px solid var(--mantine-color-gray-2)',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.08)',
        },
      }}
    >
      <AppShell.Header>
        {/* 跳到主要內容必須是整頁第一個可聚焦連結（GN1240100E），
            之後才是三區塊導盲磚與快速鍵 Alt+U / Alt+C / Alt+Z */}
        <a className="access-key-link" href="#main-block" title="跳到主要內容">
          跳到主要內容
        </a>
        <a className="access-key-link" href="#header-block" id="AU" accessKey="U" title="上方功能區塊">
          :::
        </a>
        <Container h="100%" size="lg" id="header-block">
          <Group h="100%" justify="space-between" align="center" gap="xl">
            {/* 站名是品牌識別不是內容標題：不用 h 標籤，
                否則每頁第一個標題都是 h3、跳過 h1，過不了無障礙檢測。 */}
            <Text
              component="span"
              style={{
                margin: 0,
                fontWeight: 700,
                fontSize: '1.4rem',
                background: 'linear-gradient(135deg, var(--mantine-color-blue-7) 0%, var(--mantine-color-blue-9) 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              臺北市短網址服務
            </Text>
            <Group
              component="nav"
              aria-label="主要功能選單"
              gap="xs"
              align="center"
              wrap="nowrap"
              visibleFrom="lg"
            >
              {user && navItems.map((item) => {
                const Icon = item.icon;
                const isActive = location.pathname === item.path;
                return (
                  <Button
                    key={item.path}
                    component={Link}
                    to={item.path}
                    leftSection={<Icon size={18} />}
                    variant={isActive ? 'filled' : 'subtle'}
                    size="sm"
                    radius="md"
                    style={{
                      fontWeight: isActive ? 600 : 500,
                      background: isActive
                        ? 'linear-gradient(135deg, var(--mantine-color-blue-6) 0%, var(--mantine-color-blue-7) 100%)'
                        : 'transparent',
                      color: isActive ? 'white' : 'var(--mantine-color-gray-7)',
                      border: isActive ? 'none' : '1px solid transparent',
                      transition: 'all 0.2s ease',
                    }}
                    styles={{
                      root: {
                        '&:hover': {
                          background: isActive
                            ? 'linear-gradient(135deg, var(--mantine-color-blue-7) 0%, var(--mantine-color-blue-8) 100%)'
                            : 'var(--mantine-color-gray-1)',
                          transform: 'translateY(-1px)',
                        },
                      },
                    }}
                  >
                    {item.label}
                  </Button>
                );
              })}
              {user && (
                <Button
                  variant="subtle"
                  color="gray"
                  leftSection={<IconLogout size={18} />}
                  size="sm"
                  radius="md"
                  onClick={() => signOut()}
                >
                  登出
                </Button>
              )}
            </Group>
            {user && (
              <Burger
                opened={navOpened}
                onClick={() => setNavOpened((o) => !o)}
                hiddenFrom="lg"
                size="sm"
                aria-label="開啟功能選單"
              />
            )}
          </Group>
        </Container>
      </AppShell.Header>
      {user && (
        <Drawer
          opened={navOpened}
          onClose={() => setNavOpened(false)}
          title="功能選單"
          padding="md"
          size="xs"
          hiddenFrom="lg"
        >
          <Stack gap="xs">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <Button
                  key={item.path}
                  component={Link}
                  to={item.path}
                  leftSection={<Icon size={18} />}
                  variant={location.pathname === item.path ? 'light' : 'subtle'}
                  justify="flex-start"
                  fullWidth
                  radius="md"
                  onClick={() => setNavOpened(false)}
                >
                  {item.label}
                </Button>
              );
            })}
            <Button
              variant="subtle"
              color="gray"
              leftSection={<IconLogout size={18} />}
              justify="flex-start"
              fullWidth
              radius="md"
              onClick={() => {
                setNavOpened(false);
                signOut();
              }}
            >
              登出
            </Button>
          </Stack>
        </Drawer>
      )}
      <AppShell.Main>
        <a className="access-key-link" href="#main-block" id="AC" accessKey="C" title="中央內容區塊">
          :::
        </a>
        <Container size="lg" py="xl" id="main-block" tabIndex={-1} style={{ outline: 'none' }}>
          <Suspense fallback={routeFallback}>
          {isPublicPage ? (
            <>
              <Routes>
                <Route path="/" element={<LandingPage />} />
                <Route path="/qr/*" element={<QrStudioPage />} />
                <Route path="/check/*" element={<CheckPage />} />
                <Route path="/accessibility" element={<AccessibilityPage />} />
              </Routes>
              <Group
                component="footer"
                id="footer-block"
                justify="space-between"
                mt={64}
                pt="md"
                pb="md"
                style={{
                  borderTop: '1px solid var(--mantine-color-gray-3)',
                  maxWidth: '40em',
                  margin: '64px auto 0',
                  position: 'relative',
                }}
              >
                <a className="access-key-link" href="#footer-block" id="AZ" accessKey="Z" title="下方功能區塊">
                  :::
                </a>
                <Text
                  size="xs"
                  c="dimmed"
                  component="a"
                  href="https://doit.gov.taipei"
                  target="_blank"
                  rel="noopener"
                  style={{ textDecoration: 'none' }}
                >
                  © 臺北市政府資訊局
                </Text>
                <Group gap="lg">
                  {isPublicHost && (
                    <>
                      <Text
                        size="xs"
                        c="dimmed"
                        component={Link}
                        to="/"
                        style={{ textDecoration: 'none' }}
                      >
                        服務聲明與隱私權宣告
                      </Text>
                      <Text
                        size="xs"
                        c="dimmed"
                        component={Link}
                        to="/check"
                        style={{ textDecoration: 'none' }}
                      >
                        短網址查核
                      </Text>
                      <Text
                        size="xs"
                        c="dimmed"
                        component={Link}
                        to="/accessibility"
                        style={{ textDecoration: 'none' }}
                      >
                        無障礙聲明
                      </Text>
                    </>
                  )}
                  <Text
                    size="xs"
                    c="dimmed"
                    component="a"
                    href="https://www.gov.taipei"
                    target="_blank"
                    rel="noopener"
                    style={{ textDecoration: 'none' }}
                  >
                    臺北市政府全球資訊網
                  </Text>
                </Group>
              </Group>
            </>
          ) : loading ? (
            <div style={{ padding: '2rem', textAlign: 'center' }}>載入中…</div>
          ) : !user ? (
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="*" element={<Navigate to="/login" replace />} />
            </Routes>
          ) : (
            <Routes>
              <Route path="/login" element={<Navigate to="/create" replace />} />
              <Route path="/create" element={<CreatePage />} />
              <Route path="/manage" element={<ManagePage />} />
              <Route path="/files" element={<FilesPage />} />
              <Route path="/tags" element={<TagsPage />} />
              <Route path="/blocked-words" element={<BlockedWordsPage />} />
              <Route path="/admins" element={<AdminsPage />} />
              <Route path="*" element={<Navigate to="/create" replace />} />
            </Routes>
          )}
          </Suspense>
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}

