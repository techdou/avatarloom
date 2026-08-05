/** Control API 客户端。 */

const API_BASE = "/api/control";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`API ${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

/** 文件上传（multipart/form-data）——不要设 Content-Type，浏览器自动加 boundary。 */
export async function apiUpload<T>(
  path: string,
  file: File,
  fields: Record<string, string> = {}
): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  form.append("file", file);
  const r = await fetch(`${API_BASE}${path}`, { method: "POST", body: form });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`Upload ${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

/** 文件下载 URL 构造（img/video/audio src 用）。 */
export function assetFileUrl(assetId: string): string {
  return `${API_BASE}/assets/${assetId}/file`;
}

/** Avatar 当前肖像图 URL（前端 <img src> 直接用）。 */
export function avatarPortraitUrl(avatarId: string): string {
  return `${API_BASE}/avatars/${avatarId}/portrait`;
}

/** Avatar 当前 idle 视频 URL。 */
export function avatarIdleVideoUrl(avatarId: string): string {
  return `${API_BASE}/avatars/${avatarId}/idle-video`;
}

/** Avatar 当前音色参考音频 URL。 */
export function avatarVoiceRefUrl(avatarId: string): string {
  return `${API_BASE}/avatars/${avatarId}/voice-ref`;
}

// ---------------------------------------------------------------------------
// 类型定义（和后端 schemas 对齐）
// ---------------------------------------------------------------------------

export interface Project {
  id: string;
  name: string;
  description: string | null;
  status?: string;
  created_at: string;
  updated_at: string;
}

export interface Avatar {
  id: string;
  project_id: string;
  name: string;
  persona_id: string | null;
  profile_id: string | null;
  status: string;
  portrait_path: string | null;
  idle_video_path: string | null;
  voice_ref_path: string | null;
  voice_ref_text: string | null;
  avatar_block: string | null;
  description: string | null;
  extra_assets: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export type AssetKind =
  | "portrait"
  | "idle_video"
  | "voice_ref"
  | "image"
  | "video"
  | "audio"
  | "other";

export interface Asset {
  id: string;
  kind: string;
  name: string;
  path: string;
  mime_type: string | null;
  size_bytes: number | null;
  avatar_id: string | null;
  extra_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface Persona {
  id: string;
  name: string;
  label: string | null;
  version: string;
  prompt: string;
  package_path: string | null;
  voice_ref: Record<string, unknown> | null;
  avatar_ref: Record<string, unknown> | null;
  avatar_id: string | null;
  behavior: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface BlockDefinition {
  id: string;
  name: string;
  category: string;
  version: string;
  runtime_type: string;
  entrypoint: string | null;
  capabilities: Record<string, unknown> | null;
  resources: Record<string, unknown> | null;
  inputs: string[] | null;
  outputs: string[] | null;
  created_at: string;
}

export interface RuntimeProfile {
  id: string;
  name: string;
  blocks: Record<string, unknown>;
  sync: Record<string, unknown> | null;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface Session {
  id: string;
  avatar_id: string | null;
  profile_id: string | null;
  persona_id: string | null;
  status: string;
  started_at: string;
  ended_at: string | null;
}

export interface Run {
  id: string;
  session_id: string;
  profile_id: string | null;
  persona_id: string | null;
  status: string;
  metrics: Record<string, unknown> | null;
  run_dir: string | null;
  user_text: string;
  assistant_text: string;
  started_at: string;
  ended_at: string | null;
}
