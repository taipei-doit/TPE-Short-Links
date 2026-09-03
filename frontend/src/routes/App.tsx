import { AppShell, Button, Container, Group, Title } from '@mantine/core';
import { IconFileUpload, IconLink, IconListSearch, IconLogout, IconShield, IconTags, IconUsers } from '@tabler/icons-react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { AdminsPage } from './AdminsPage';
import { BlockedWordsPage } from './BlockedWordsPage';
import { CreatePage } from './CreatePage';
import { FilesPage } from './FilesPage';
import { LoginPage } from './LoginPage';
import { ManagePage } from './ManagePage';
import { QrStudioPage } from './QrStudioPage';
import { TagsPage } from './TagsPage';

export function App() {
  const location = useLocation();
  const { user, loading, signOut } = useAuth();

  // QR 產生器是公開頁面，不需要登入，也不等待登入狀態載入。
  const isQrStudio = location.pathname === '/qr' || location.pathname.startsWith('/qr/');

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
          background: 'linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%)',
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
        <Container h="100%" size="lg">
          <Group h="100%" justify="space-between" align="center" gap="xl">
            <Title
              order={3}
              style={{
                margin: 0,
                fontWeight: 700,
                background: 'linear-gradient(135deg, var(--mantine-color-blue-7) 0%, var(--mantine-color-blue-9) 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              臺北市短網址服務
            </Title>
            <Group gap="xs" align="center" wrap="nowrap">
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
          </Group>
        </Container>
      </AppShell.Header>
      <AppShell.Main>
        <Container size="lg" py="xl">
          {isQrStudio ? (
            <Routes>
              <Route path="/qr/*" element={<QrStudioPage />} />
            </Routes>
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
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}

