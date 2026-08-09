/** Control API 客户端。 */

/** 浏览器走 Next rewrite（/api/control -> 8100/api）；SSR 直连 Control API 绝对地址。 */
const API_BASE = "/api/control";
const SERVER_API_BASE =
  process.env.CONTROL_API_BASE ?? "http://127.0.0.1:8100/api";
const GATEWAY_API_BASE = "/api/realtime";

function fetchBase(): string {
  return typeof window === "undefined" ? SERVER_API_BASE : API_BASE;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${fetchBase()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`API ${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

/** Runtime Gateway 客户端（/api/realtime/* → 8101/api/*）。 */
export async function gatewayFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${GATEWAY_API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`Gateway ${r.status}: ${detail}`);
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
  const r = await fetch(`${fetchBase()}${path}`, { method: "POST", body: form });
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

/** Run 的性能指标——和 runtime/recorder/metrics.py 对齐。 */
export interface RunMetrics {
  first_text_ms?: number | null;
  first_audio_ms?: number | null;
  first_frame_ms?: number | null;
  total_duration_ms?: number | null;
  interruptions?: number;
  degradations?: number;
  errors?: number;
  cancelled?: boolean;
  user_audio_samples?: number;
  assistant_audio_samples?: number;
  avatar_frames?: number;
  block_versions?: Record<string, string>;
  degraded_blocks?: Record<string, string>;
  [key: string]: unknown;
}

export interface Artifact {
  id: string;
  run_id: string;
  kind: string;
  path: string;
  mime_type: string | null;
  size_bytes: number | null;
  extra_metadata: Record<string, unknown> | null;
  created_at: string;
}

/** Block 健康明细（gateway /api/health/blocks）。 */
export interface BlockHealth {
  category: string;
  block_id: string | null;
  deployment: string | null;
  status: "healthy" | "degraded" | "unhealthy" | "not_ready" | "absent" | string;
  detail: string;
  latency_ms: number | null;
}

export interface BlockHealthReport {
  active: boolean;
  profile_id: string | null;
  degraded: Record<string, string>;
  blocks: BlockHealth[];
}

/** 记忆条目（gateway /api/memory）。 */
export interface MemoryEntry {
  id: string | null;
  text: string;
  hash?: string | null;
}

export interface MemoryListResponse {
  active: boolean;
  persona_id: string | null;
  items: MemoryEntry[];
}
