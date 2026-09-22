export type Admin = {
  email: string;
  name: string;
  title: string;
};

export type Tag = {
  id: number;
  name: string;
  is_active: boolean;
};

export type Link = {
  id: number;
  code: string;
  original_url: string;
  tag_id: number;
  tag_name: string;
  expires_at: string | null;
  note: string | null;
  status: 'active' | 'disabled' | 'expired';
  created_at: string;
  is_expired: boolean;
  short_url: string;
  click_count: number;
  /** QR 產生器的 4 碼解鎖 PIN，管理員轉知局處用 */
  qr_pin: string;
  /** 目標網址的可註冊網域（gov.taipei 而非 doit.gov.taipei）；未查詢過為 null */
  domain_name: string | null;
  domain_status: DomainStatus | null;
  domain_expires_at: string | null;
  domain_checked_at: string | null;
  /** 到期日（或永久有效）超過網域註冊到期日；永久有效不擋只警示，明確填的日期超過則建立時就會被擋 */
  exceeds_domain_expiry: boolean;
};

/** ok＝查到到期日；unknown＝註冊機構不公開（gov.tw 等）；error＝暫時查不到；not_applicable＝IP 位址等 */
export type DomainStatus = 'ok' | 'unknown' | 'error' | 'not_applicable';

export type DomainInfo = {
  name: string | null;
  status: DomainStatus;
  expires_at: string | null;
  checked_at: string | null;
  detail: string;
};

export type DomainRefreshResult = {
  domain: DomainInfo;
  /** 同網域中到期日超過註冊期限的短網址數（只提醒，不會被改） */
  over_cap_links: number;
  link: Link;
};

export type LinkList = {
  items: Link[];
  total: number;
  limit: number;
  offset: number;
};

export type SharedFile = {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: 'active' | 'deleted';
  sort_order: number;
  download_count: number;
  created_at: string;
};

/** One share link and PIN, holding any number of files. */
export type FileShare = {
  id: number;
  code: string;
  note: string | null;
  status: 'active' | 'disabled' | 'deleted';
  expires_at: string | null;
  created_at: string;
  is_expired: boolean;
  is_locked: boolean;
  uploaded_by: string;
  share_url: string;
  files: SharedFile[];
  file_count: number;
  total_bytes: number;
  download_count: number;
};

/** Creation response. `pin` is shown once and never retrievable again. */
export type FileShareCreated = FileShare & { pin: string };

export type FileShareList = {
  items: FileShare[];
  total: number;
  limit: number;
  offset: number;
};

/**
 * Where to send a file's bytes.
 *
 * `resumable` means straight to object storage — the only way past Cloud Run's
 * 32 MiB request limit. `proxy` means through the backend.
 */
export type UploadSession = {
  mode: 'resumable' | 'proxy';
  upload_url: string;
  upload_token: string;
  storage_path: string;
};

export type CreateLinkIn = {
  original_url: string;
  tag_id: number;
  expires_at: string | null;
  note: string | null;
  code?: string | null;
};

