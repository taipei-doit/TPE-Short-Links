import { Button, Card, Stack, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';

import { useAuth } from '../auth/AuthContext';

export function LoginPage() {
  const { requestLoginLink } = useAuth();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    try {
      await requestLoginLink(email.trim());
      setSent(true);
      notifications.show({
        color: 'green',
        message: '登入連結已寄出，請查收電子郵件。',
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : '登入連結寄送失敗';
      notifications.show({ color: 'red', message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card
      shadow="md"
      radius="md"
      p="xl"
      style={{ maxWidth: 420, margin: '2rem auto' }}
    >
      <Stack gap="md">
        <Title order={3}>管理員登入</Title>
        <Text size="sm" c="dimmed">
          請輸入管理員電子郵件，系統將寄送一次性登入連結給您。
        </Text>
        {sent ? (
          <Text size="sm" c="green">
            請至信箱點擊登入連結完成登入，本頁面可直接關閉。
          </Text>
        ) : (
          <form onSubmit={handleSubmit}>
            <Stack gap="md">
              <TextInput
                label="電子郵件"
                type="email"
                placeholder="admin@example.com"
                value={email}
                onChange={(e) => setEmail(e.currentTarget.value)}
                required
                autoComplete="email"
              />
              <Button type="submit" loading={loading} fullWidth>
                寄送登入連結
              </Button>
            </Stack>
          </form>
        )}
      </Stack>
    </Card>
  );
}
