import type { CreateLinkIn, Link, LinkList, Tag } from './types';
import { auth } from '../firebase';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000';

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'content-type': 'application/json',
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (auth.currentUser) {
    const token = await auth.currentUser.getIdToken();
    headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === 'string') detail = data.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  return (await res.json()) as T;
}

export const api = {
  getTags: () => apiFetch<Tag[]>('/api/tags'),
  createLink: (payload: CreateLinkIn) =>
    apiFetch<Link>('/api/links', { method: 'POST', body: JSON.stringify(payload) }),
  listLinks: (params: {
    query?: string;
    tag_id?: number;
    status?: 'active' | 'disabled' | 'expired' | 'all';
    limit?: number;
    offset?: number;
  }) => {
    const sp = new URLSearchParams();
    if (params.query) sp.set('query', params.query);
    if (params.tag_id) sp.set('tag_id', String(params.tag_id));
    if (params.status) sp.set('status', params.status);
    if (params.limit) sp.set('limit', String(params.limit));
    if (params.offset) sp.set('offset', String(params.offset));
    const qs = sp.toString();
    return apiFetch<LinkList>(`/api/links${qs ? `?${qs}` : ''}`);
  },
  disableLink: (code: string) => apiFetch<{ code: string; status: string }>(`/api/links/${code}/disable`, { method: 'POST' }),
  enableLink: (code: string) => apiFetch<{ code: string; status: string }>(`/api/links/${code}/enable`, { method: 'POST' }),
  updateLinkExpiry: (code: string, expires_at: string | null) =>
    apiFetch<Link>(`/api/links/${code}`, {
      method: 'PATCH',
      body: JSON.stringify({ expires_at }),
    }),
  updateLinkUrl: (code: string, original_url: string) =>
    apiFetch<Link>(`/api/links/${code}`, {
      method: 'PATCH',
      body: JSON.stringify({ original_url }),
    }),
  getQrCodeUrl: (code: string) => `${API_BASE_URL}/api/links/${code}/qrcode`,
  listBlockedWords: () => apiFetch<string[]>('/api/blocked-words'),
  addBlockedWord: (word: string) => apiFetch<{ message: string; word: string }>(`/api/blocked-words?word=${encodeURIComponent(word)}`, { method: 'POST' }),
  deleteBlockedWord: (word: string) => apiFetch<{ message: string; word: string }>(`/api/blocked-words/${encodeURIComponent(word)}`, { method: 'DELETE' }),
  createTag: (name: string) => apiFetch<Tag>(`/api/tags?name=${encodeURIComponent(name)}`, { method: 'POST' }),
  deleteTag: (tagId: number) => apiFetch<{ message: string; tag_id: number }>(`/api/tags/${tagId}`, { method: 'DELETE' }),

  listAdmins: async (): Promise<string[]> => {
    const { getFunctions, httpsCallable } = await import('firebase/functions');
    const fn = getFunctions(auth.app);
    const list = httpsCallable<{ idToken?: string }, { emails: string[] }>(fn, 'listAdmins');
    const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : undefined;
    const res = await list(idToken ? { idToken } : {});
    return Array.isArray(res.data?.emails) ? res.data.emails : [];
  },
  addAdmin: async (email: string): Promise<void> => {
    const { getFunctions, httpsCallable } = await import('firebase/functions');
    const fn = getFunctions(auth.app);
    const add = httpsCallable<{ email: string; idToken?: string }, { email: string }>(fn, 'addAdmin');
    const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : undefined;
    await add(idToken ? { email, idToken } : { email });
  },
  removeAdmin: async (email: string): Promise<void> => {
    const { getFunctions, httpsCallable } = await import('firebase/functions');
    const fn = getFunctions(auth.app);
    const remove = httpsCallable<{ email: string; idToken?: string }, { email: string }>(fn, 'removeAdmin');
    const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : undefined;
    await remove(idToken ? { email, idToken } : { email });
  },
};

export { API_BASE_URL };

