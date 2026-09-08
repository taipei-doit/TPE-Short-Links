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
  Tooltip,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconPlus, IconSearch, IconTrash } from '@tabler/icons-react';
import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';

const LETTERS = ['0-9', ...'abcdefghijklmnopqrstuvwxyz'.split('')];

function letterOf(word: string): string {
  return /^[0-9]/.test(word) ? '0-9' : word[0];
}

export function BlockedWordsPage() {
  const [words, setWords] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [newWord, setNewWord] = useState('');
  const [letter, setLetter] = useState('a');
  const [search, setSearch] = useState('');

  async function load() {
    setLoading(true);
    try {
      const data = await api.listBlockedWords();
      setWords(data);
      if (data.length === 0) {
        notifications.show({
          color: 'yellow',
          message: '尚無封鎖字詞，請確認資料庫種子（blocked_words.txt 遷移）是否已執行。',
        });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '載入失敗';
      notifications.show({ color: 'red', message: msg });
      console.error('Error loading blocked words:', e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const groups = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const l of LETTERS) map.set(l, []);
    for (const w of words) {
      const bucket = map.get(letterOf(w));
      if (bucket) bucket.push(w);
    }
    return map;
  }, [words]);

  const searching = search.trim().length > 0;
  const visible = useMemo(() => {
    if (searching) {
      const q = search.trim().toLowerCase();
      return words.filter((w) => w.includes(q));
    }
    return groups.get(letter) ?? [];
  }, [words, groups, letter, search, searching]);

  async function handleAdd() {
    const trimmed = newWord.trim().toLowerCase();
    if (!trimmed || trimmed.length > 6) {
      notifications.show({ color: 'red', message: '字詞長度須為 1–6 個字元' });
      return;
    }

    try {
      await api.addBlockedWord(trimmed);
      setNewWord('');
      setLetter(letterOf(trimmed));
      setSearch('');
      notifications.show({ color: 'green', message: '字詞已新增' });
      load();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '新增失敗';
      notifications.show({ color: 'red', message: msg });
    }
  }

  function handleDelete(word: string) {
    modals.openConfirmModal({
      title: '移除封鎖字詞？',
      children: (
        <Text size="sm">
          將移除{' '}
          <Text span fw={600} style={{ fontFamily: 'monospace' }}>
            {word}
          </Text>
          ，之後自動產生的代碼將不再避開這個字詞。
        </Text>
      ),
      labels: { confirm: '移除', cancel: '取消' },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await api.deleteBlockedWord(word);
          notifications.show({ color: 'green', message: '字詞已移除' });
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
          封鎖字詞管理
        </Title>
        <Text c="dimmed" size="sm">
          自動產生的短網址（4 碼）與檔案分享（6 碼）代碼會避開這些字詞；3
          個字元以上的字詞才會參與封鎖比對。初始清單由 blocked_words.txt 經資料庫遷移種入，共{' '}
          {words.length.toLocaleString()} 筆。
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
              label="新增字詞"
              placeholder="請輸入字詞（1–6 個字元）"
              value={newWord}
              onChange={(e) => setNewWord(e.currentTarget.value.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 6))}
              maxLength={6}
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
              disabled={!newWord.trim() || newWord.trim().length > 6}
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
        <Stack gap="md">
          <TextInput
            label="搜尋字詞"
            placeholder="輸入英數字即時篩選全部字詞"
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value.toLowerCase().replace(/[^a-z0-9]/g, ''))}
            leftSection={<IconSearch size={16} />}
            size="md"
            radius="md"
          />
          {!searching && (
            <Group gap={6} component="nav" aria-label="依字母瀏覽封鎖字詞">
              {LETTERS.map((l) => {
                const count = groups.get(l)?.length ?? 0;
                const active = l === letter;
                return (
                  <Button
                    key={l}
                    size="compact-sm"
                    radius="md"
                    variant={active ? 'filled' : 'light'}
                    color={active ? 'brand' : 'gray'}
                    disabled={count === 0}
                    onClick={() => setLetter(l)}
                    aria-pressed={active}
                    styles={{ label: { fontFamily: 'monospace' } }}
                  >
                    {l.toUpperCase()}
                    <Text span size="xs" ml={4} c={active ? 'gray.2' : 'dimmed'}>
                      {count}
                    </Text>
                  </Button>
                );
              })}
            </Group>
          )}
          <Text c="dimmed" size="sm">
            {searching
              ? `搜尋「${search}」：${visible.length} 筆`
              : `${letter.toUpperCase()} 開頭：${visible.length} 筆`}
          </Text>
          <Table highlightOnHover withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ fontWeight: 600 }}>字詞</Table.Th>
                <Table.Th style={{ width: '120px', fontWeight: 600 }}>是否封鎖代碼</Table.Th>
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
              ) : visible.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={3}>
                    <Text c="dimmed" size="sm" ta="center" py="xl">
                      {searching ? '沒有符合搜尋的字詞' : '此分類尚無字詞'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                visible.map((word) => {
                  const blocksCodes = word.length >= 3;
                  return (
                    <Table.Tr key={word}>
                      <Table.Td>
                        <Text fw={600} size="sm" style={{ fontFamily: 'monospace' }}>
                          {word}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge color={blocksCodes ? 'red' : 'gray'} size="sm" variant="light">
                          {blocksCodes ? '是' : '否'}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Tooltip label="移除字詞" withArrow>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            onClick={() => handleDelete(word)}
                            aria-label={`移除封鎖字詞 ${word}`}
                            size="md"
                            radius="md"
                          >
                            <IconTrash size={18} />
                          </ActionIcon>
                        </Tooltip>
                      </Table.Td>
                    </Table.Tr>
                  );
                })
              )}
            </Table.Tbody>
          </Table>
        </Stack>
      </Card>
    </Stack>
  );
}
