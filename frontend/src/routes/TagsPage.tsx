import {
  ActionIcon,
  Badge,
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
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { Tag } from '../api/types';

export function TagsPage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(false);
  const [newTag, setNewTag] = useState('');

  async function load() {
    setLoading(true);
    try {
      const data = await api.getTags();
      setTags(data);
      if (data.length === 0) {
        notifications.show({
          color: 'yellow',
          message: '尚無標籤資料，系統會自動從 tags.txt 同步標籤。',
        });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '載入失敗';
      notifications.show({ color: 'red', message: msg });
      console.error('Error loading tags:', e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleAdd() {
    const trimmed = newTag.trim();
    if (!trimmed) {
      notifications.show({ color: 'red', message: '標籤名稱不可為空白' });
      return;
    }

    try {
      await api.createTag(trimmed);
      setNewTag('');
      notifications.show({ color: 'green', message: '標籤已新增' });
      load();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '新增失敗';
      notifications.show({ color: 'red', message: msg });
    }
  }

  async function handleDelete(tag: Tag) {
    modals.openConfirmModal({
      title: '刪除標籤？',
      children: (
        <Text size="sm">
          將停用標籤 <Text span fw={600}>{tag.name}</Text>。仍有短網址使用中的標籤無法刪除。
        </Text>
      ),
      labels: { confirm: '刪除', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.deleteTag(tag.id);
          notifications.show({ color: 'green', message: '標籤已刪除' });
          load();
        } catch (e) {
          const msg = e instanceof Error ? e.message : '刪除失敗';
          notifications.show({ color: 'red', message: msg });
        }
      },
    });
  }

  return (
    <Stack gap="xl">
      <div>
        <Title order={1} style={{ marginBottom: '8px', fontWeight: 700 }}>
          標籤管理
        </Title>
        <Text c="dimmed" size="sm">
          新增或移除用來分類短網址的標籤。來自{' '}
          <Text span fw={600} style={{ fontFamily: 'monospace' }}>
            tags.txt
          </Text>{' '}
          的標籤會自動同步至資料庫。
        </Text>
      </div>

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
          <Group align="flex-end" wrap="nowrap">
            <TextInput
              label="新增標籤"
              placeholder="請輸入標籤名稱"
              value={newTag}
              onChange={(e) => setNewTag(e.currentTarget.value)}
              maxLength={64}
              size="md"
              radius="md"
              style={{ flex: 1 }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleAdd();
                }
              }}
            />
            <Button
              leftSection={<IconPlus size={18} />}
              onClick={handleAdd}
              disabled={!newTag.trim()}
              size="md"
              radius="md"
              style={{
                background: 'linear-gradient(135deg, var(--mantine-color-blue-6) 0%, var(--mantine-color-blue-7) 100%)',
                fontWeight: 600,
              }}
            >
              新增
            </Button>
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
        <Table highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ fontWeight: 600 }}>標籤名稱</Table.Th>
              <Table.Th style={{ width: '100px', fontWeight: 600 }}>狀態</Table.Th>
              <Table.Th style={{ width: '100px' }}></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loading ? (
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Text c="dimmed" size="sm" ta="center" py="xl">
                    載入中…
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : tags.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Text c="dimmed" size="sm" ta="center" py="xl">
                    尚無標籤
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              tags.map((tag) => (
                <Table.Tr key={tag.id}>
                  <Table.Td>
                    <Text fw={600} size="sm">
                      {tag.name}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={tag.is_active ? 'green' : 'gray'} size="sm">
                      {tag.is_active ? '啟用中' : '已停用'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      onClick={() => handleDelete(tag)}
                      disabled={!tag.is_active}
                      aria-label="刪除"
                      size="md"
                      radius="md"
                    >
                      <IconTrash size={18} />
                    </ActionIcon>
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
