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
    // #region agent log
    fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H1',location:'api/client.ts:listAdmins:start',message:'Calling listAdmins',data:{firebaseProjectId:(auth.app.options as any)?.projectId ?? null},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    try {
      const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : undefined;
      const res = await list(idToken ? { idToken } : {});
      const emails = Array.isArray(res.data?.emails) ? res.data.emails : [];
      const domains = emails
        .map((e) => (typeof e === 'string' && e.includes('@') ? e.split('@')[1] : ''))
        .filter(Boolean);
      const domainCounts = domains.reduce<Record<string, number>>((acc, d) => {
        acc[d] = (acc[d] ?? 0) + 1;
        return acc;
      }, {});
      // #region agent log
      fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H2',location:'api/client.ts:listAdmins:success',message:'listAdmins returned',data:{count:emails.length,domainCounts},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      return emails;
    } catch (e: any) {
      // #region agent log
      fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H1',location:'api/client.ts:listAdmins:error',message:'listAdmins threw',data:{name:e?.name ?? null,code:e?.code ?? null,message:typeof e?.message==='string'?e.message:String(e)},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      throw e;
    }
  },
  addAdmin: async (email: string): Promise<void> => {
    const { getFunctions, httpsCallable } = await import('firebase/functions');
    const fn = getFunctions(auth.app);
    const add = httpsCallable<{ email: string; idToken?: string }, { email: string }>(fn, 'addAdmin');
    const domain = typeof email === 'string' && email.includes('@') ? email.split('@')[1] : null;
    // #region agent log
    fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H3',location:'api/client.ts:addAdmin:start',message:'Calling addAdmin',data:{emailDomain:domain},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    try {
      const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : undefined;
      await add(idToken ? { email, idToken } : { email });
      // #region agent log
      fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H3',location:'api/client.ts:addAdmin:success',message:'addAdmin success',data:{emailDomain:domain},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
    } catch (e: any) {
      // #region agent log
      fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H3',location:'api/client.ts:addAdmin:error',message:'addAdmin threw',data:{name:e?.name ?? null,code:e?.code ?? null,message:typeof e?.message==='string'?e.message:String(e)},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      throw e;
    }
  },
  removeAdmin: async (email: string): Promise<void> => {
    const { getFunctions, httpsCallable } = await import('firebase/functions');
    const fn = getFunctions(auth.app);
    const remove = httpsCallable<{ email: string; idToken?: string }, { email: string }>(fn, 'removeAdmin');
    const domain = typeof email === 'string' && email.includes('@') ? email.split('@')[1] : null;
    // #region agent log
    fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H4',location:'api/client.ts:removeAdmin:start',message:'Calling removeAdmin',data:{emailDomain:domain},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    try {
      const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : undefined;
      await remove(idToken ? { email, idToken } : { email });
      // #region agent log
      fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H4',location:'api/client.ts:removeAdmin:success',message:'removeAdmin success',data:{emailDomain:domain},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
    } catch (e: any) {
      // #region agent log
      fetch('http://127.0.0.1:7245/ingest/8f8a3f0e-1f4c-4e1e-9e8e-8bee3dcb50dc',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1c1ee1'},body:JSON.stringify({sessionId:'1c1ee1',runId:'admins-debug',hypothesisId:'H4',location:'api/client.ts:removeAdmin:error',message:'removeAdmin threw',data:{name:e?.name ?? null,code:e?.code ?? null,message:typeof e?.message==='string'?e.message:String(e)},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      throw e;
    }
  },
};

export { API_BASE_URL };

