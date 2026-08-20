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

