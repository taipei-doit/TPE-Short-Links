import type {
  Admin,
  CreateLinkIn,
  Link,
  LinkList,
  SharedFile,
  SharedFileCreated,
  SharedFileList,
  Tag,
} from './types';
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

/**
 * Download a file from an authenticated endpoint.
 *
 * These endpoints require an Authorization header, so they cannot be opened
 * directly via window.open()/<a href> — the browser would send no token and
 * get a 401. Fetch the bytes with the header, then save them from memory.
 */
async function downloadFile(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {};
  if (auth.currentUser) {
    const token = await auth.currentUser.getIdToken();
    headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE_URL}${path}`, { headers });

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

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

/**
 * Upload a file with progress reporting.
 *
 * Uses XMLHttpRequest rather than fetch because fetch gives no upload progress,
 * and a 25 MB file over an office connection needs a progress bar to not look
 * frozen. The browser sets the multipart boundary itself, so no content-type
 * header is set here.
 */
async function uploadWithProgress<T>(
  path: string,
  form: FormData,
  onProgress?: (percent: number) => void,
): Promise<T> {
  const token = auth.currentUser ? await auth.currentUser.getIdToken() : null;

  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}${path}`);
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(xhr.responseText);
      } catch {
        // ignore
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(parsed as T);
        return;
      }
      const detail = (parsed as { detail?: unknown } | null)?.detail;
      reject(new Error(typeof detail === 'string' ? detail : `上傳失敗（${xhr.status}）`));
    };

    xhr.onerror = () => reject(new Error('上傳失敗，請檢查網路連線'));
    xhr.onabort = () => reject(new Error('上傳已取消'));

    xhr.send(form);
  });
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
  exportLinksCsv: (params: {
    query?: string;
    tag_id?: number;
    status?: 'active' | 'disabled' | 'expired' | 'all';
  }) => {
    const sp = new URLSearchParams();
    if (params.query) sp.set('query', params.query);
    if (params.tag_id) sp.set('tag_id', String(params.tag_id));
    if (params.status) sp.set('status', params.status);
    const qs = sp.toString();
    return downloadFile(`/api/links/export${qs ? `?${qs}` : ''}`, 'short_links.csv');
  },
  downloadQrCode: (code: string) =>
    downloadFile(`/api/links/${encodeURIComponent(code)}/qrcode`, `qrcode_${code}.png`),
  listBlockedWords: () => apiFetch<string[]>('/api/blocked-words'),
  addBlockedWord: (word: string) => apiFetch<{ message: string; word: string }>(`/api/blocked-words?word=${encodeURIComponent(word)}`, { method: 'POST' }),
  deleteBlockedWord: (word: string) => apiFetch<{ message: string; word: string }>(`/api/blocked-words/${encodeURIComponent(word)}`, { method: 'DELETE' }),
  createTag: (name: string) => apiFetch<Tag>(`/api/tags?name=${encodeURIComponent(name)}`, { method: 'POST' }),
  deleteTag: (tagId: number) => apiFetch<{ message: string; tag_id: number }>(`/api/tags/${tagId}`, { method: 'DELETE' }),

  // PIN-protected file sharing.
  uploadSharedFile: (
    payload: { file: File; note?: string | null; expires_at?: string | null; pin?: string | null },
    onProgress?: (percent: number) => void,
  ) => {
    const form = new FormData();
    form.append('file', payload.file);
    if (payload.note) form.append('note', payload.note);
    if (payload.expires_at) form.append('expires_at', payload.expires_at);
    if (payload.pin) form.append('pin', payload.pin);
    return uploadWithProgress<SharedFileCreated>('/api/files', form, onProgress);
  },
  listSharedFiles: (params: {
    query?: string;
    status?: 'active' | 'disabled' | 'expired' | 'deleted' | 'all';
    limit?: number;
    offset?: number;
  }) => {
    const sp = new URLSearchParams();
    if (params.query) sp.set('query', params.query);
    if (params.status) sp.set('status', params.status);
    if (params.limit) sp.set('limit', String(params.limit));
    if (params.offset) sp.set('offset', String(params.offset));
    const qs = sp.toString();
    return apiFetch<SharedFileList>(`/api/files${qs ? `?${qs}` : ''}`);
  },
  updateSharedFile: (code: string, patch: { expires_at?: string | null; note?: string | null }) =>
    apiFetch<SharedFile>(`/api/files/${encodeURIComponent(code)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  /** Issue a new PIN. The previous one stops working immediately. */
  regenerateSharedFilePin: (code: string) =>
    apiFetch<{ code: string; pin: string }>(`/api/files/${encodeURIComponent(code)}/regenerate-pin`, {
      method: 'POST',
    }),
  disableSharedFile: (code: string) =>
    apiFetch<{ code: string; status: string }>(`/api/files/${encodeURIComponent(code)}/disable`, {
      method: 'POST',
    }),
  enableSharedFile: (code: string) =>
    apiFetch<{ code: string; status: string }>(`/api/files/${encodeURIComponent(code)}/enable`, {
      method: 'POST',
    }),
  /** Erase the stored bytes. The record stays for the audit trail. */
  deleteSharedFile: (code: string) =>
    apiFetch<{ message: string; code: string }>(`/api/files/${encodeURIComponent(code)}`, {
      method: 'DELETE',
    }),

  // Admins live in the application database and are served by the backend API.
  // (They used to be Cloud Functions backed by Firestore.)
  listAdmins: () => apiFetch<Admin[]>('/api/admins'),
  /** Create an admin, or update an existing one's name/title. */
  saveAdmin: (adminUser: Admin) =>
    apiFetch<Admin>('/api/admins', { method: 'POST', body: JSON.stringify(adminUser) }),
  removeAdmin: (email: string) =>
    apiFetch<{ message: string; email: string }>(`/api/admins/${encodeURIComponent(email)}`, {
      method: 'DELETE',
    }),
};

export { API_BASE_URL };

