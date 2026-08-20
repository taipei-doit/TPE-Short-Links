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
  code: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  note: string | null;
  status: 'active' | 'disabled' | 'deleted';
  expires_at: string | null;
  created_at: string;
  is_expired: boolean;
  download_count: number;
  is_locked: boolean;
  uploaded_by: string;
  share_url: string;
};

/** Upload response. `pin` is shown once and never retrievable again. */
export type SharedFileCreated = SharedFile & { pin: string };

export type SharedFileList = {
  items: SharedFile[];
  total: number;
  limit: number;
  offset: number;
};

export type CreateLinkIn = {
  original_url: string;
  tag_id: number;
  expires_at: string | null;
  note: string | null;
  code?: string | null;
};

