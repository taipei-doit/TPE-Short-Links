import {
  ActionIcon,
  Button,
  Card,
  Group,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { Admin } from '../api/types';

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

function EditAdminForm({
  admin,
  onSave,
  onCancel,
}: {
  admin: Admin;
  onSave: (next: Admin) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(admin.name);
  const [title, setTitle] = useState(admin.title);
  const [saving, setSaving] = useState(false);

  return (
    <Stack gap="md">
      <TextInput label="電子郵件" value={admin.email} disabled />
      <TextInput
        label="姓名"
        placeholder="王小明"
        value={name}
        maxLength={100}
        onChange={(e) => setName(e.currentTarget.value)}
        data-autofocus
      />
      <TextInput
        label="職稱"
        placeholder="資訊室 科員"
        value={title}
        maxLength={100}
        onChange={(e) => setTitle(e.currentTarget.value)}
      />
      <Group justify="flex-end" gap="sm">
        <Button variant="default" onClick={onCancel}>
          取消
        </Button>
        <Button
          loading={saving}
          onClick={async () => {
            setSaving(true);
            await onSave({ email: admin.email, name: name.trim(), title: title.trim() });
            setSaving(false);
          }}
        >
          儲存
        </Button>
      </Group>
    </Stack>
  );
}

export function AdminsPage() {
  const [admins, setAdmins] = useState<Admin[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [newEmail, setNewEmail] = useState('');
  const [newName, setNewName] = useState('');
  const [newTitle, setNewTitle] = useState('');

  async function load() {
    setLoading(true);
    try {
      const data = await api.listAdmins();
      setAdmins(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : '載入失敗';
      notifications.show({ color: 'red', message: msg });
      console.error('Error loading admins:', e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleAdd() {
    const email = newEmail.trim().toLowerCase();
    if (!email) {
      notifications.show({ color: 'red', message: '請輸入電子郵件' });
      return;
    }
    if (!isValidEmail(email)) {
      notifications.show({ color: 'red', message: '請輸入有效的電子郵件地址' });
      return;
    }

    setSaving(true);
    try {
      await api.saveAdmin({ email, name: newName.trim(), title: newTitle.trim() });
      setNewEmail('');
      setNewName('');
      setNewTitle('');
      notifications.show({ color: 'green', message: '管理員已新增' });
      load();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '新增失敗';
      notifications.show({ color: 'red', message: msg });
    } finally {
      setSaving(false);
    }
  }

  function openEditModal(admin: Admin) {
    modals.open({
      title: '編輯管理員資料',
      size: 'md',
      children: (
        <EditAdminForm
          admin={admin}
          onSave={async (next) => {
            try {
              await api.saveAdmin(next);
              notifications.show({ color: 'green', message: '管理員資料已更新' });
              modals.closeAll();
              load();
            } catch (e) {
              const msg = e instanceof Error ? e.message : '更新失敗';
              notifications.show({ color: 'red', message: msg });
            }
          }}
          onCancel={() => modals.closeAll()}
        />
      ),
    });
  }

  function confirmRemove(admin: Admin) {
    modals.openConfirmModal({
      title: '移除管理員？',
      children: (
        <Text size="sm">
          將移除{' '}
          <Text span fw={600}>
            {admin.name ? `${admin.name}（${admin.email}）` : admin.email}
          </Text>
          ，該帳號將無法再登入管理介面。
        </Text>
      ),
      labels: { confirm: '移除', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.removeAdmin(admin.email);
          notifications.show({ color: 'green', message: '管理員已移除' });
          load();
        } catch (e) {
          const msg = e instanceof Error ? e.message : '移除失敗';
          notifications.show({ color: 'red', message: msg });
        }
      },
    });
  }

  const cardStyle = {
    boxShadow: '0 2px 12px rgba(0, 0, 0, 0.1)',
    background: 'white',
    border: '1px solid var(--mantine-color-gray-2)',
  };

  return (
    <Stack gap="xl">
      <div>
        <Title order={1} style={{ marginBottom: '8px', fontWeight: 700 }}>
          管理員
        </Title>
        <Text c="dimmed" size="sm">
          可申請登入連結的管理員清單，可在此新增、編輯或移除。姓名與職稱為選填，供內部辨識聯絡人之用。
        </Text>
      </div>

      <Card withBorder padding="xl" radius="md" style={cardStyle}>
        <Stack gap="md">
          <Group align="flex-end" grow>
            <TextInput
              label="電子郵件"
              placeholder="admin@gov.taipei"
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.currentTarget.value)}
              size="md"
              radius="md"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAdd();
              }}
            />
            <TextInput
              label="姓名"
              placeholder="王小明"
              value={newName}
              maxLength={100}
              onChange={(e) => setNewName(e.currentTarget.value)}
              size="md"
              radius="md"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAdd();
              }}
            />
            <TextInput
              label="職稱"
              placeholder="資訊室 科員"
              value={newTitle}
              maxLength={100}
              onChange={(e) => setNewTitle(e.currentTarget.value)}
              size="md"
              radius="md"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAdd();
              }}
            />
          </Group>
          <Group justify="flex-end">
            <Button
              leftSection={<IconPlus size={18} />}
              onClick={handleAdd}
              loading={saving}
              disabled={!newEmail.trim() || !isValidEmail(newEmail.trim())}
              size="md"
              radius="md"
              style={{
                background: 'linear-gradient(135deg, var(--mantine-color-blue-6) 0%, var(--mantine-color-blue-7) 100%)',
                fontWeight: 600,
              }}
            >
              新增管理員
            </Button>
          </Group>
        </Stack>
      </Card>

      <Card withBorder padding="xl" radius="md" style={cardStyle}>
        <Table highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ fontWeight: 600 }}>電子郵件</Table.Th>
              <Table.Th style={{ width: 160, fontWeight: 600 }}>姓名</Table.Th>
              <Table.Th style={{ width: 220, fontWeight: 600 }}>職稱</Table.Th>
              <Table.Th style={{ width: 110 }}>操作</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loading ? (
              <Table.Tr>
                <Table.Td colSpan={4}>
                  <Text c="dimmed" size="sm" ta="center" py="xl">
                    載入中…
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : admins.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={4}>
                  <Text c="dimmed" size="sm" ta="center" py="xl">
                    尚無管理員，請在上方新增。
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              admins.map((a) => (
                <Table.Tr key={a.email}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {a.email}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {a.name ? (
                      <Text size="sm">{a.name}</Text>
                    ) : (
                      <Text size="sm" c="dimmed">
                        —
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {a.title ? (
                      <Text size="sm">{a.title}</Text>
                    ) : (
                      <Text size="sm" c="dimmed">
                        —
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <ActionIcon
                        variant="subtle"
                        color="blue"
                        onClick={() => openEditModal(a)}
                        aria-label="編輯管理員資料"
                        size="md"
                        radius="md"
                      >
                        <IconPencil size={18} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        onClick={() => confirmRemove(a)}
                        aria-label="移除管理員"
                        size="md"
                        radius="md"
                      >
                        <IconTrash size={18} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
