/**
 * Control API 客户端。
 *
 * Token 来源矩阵：
 * - 浏览器路径（window defined）：走 Next rewrite（/api/control -> 127.0.0.1:8100）。
 *   后端配置 AVATARLOOM_API_TOKEN 时，由 middleware.ts 在服务端注入 Authorization
 *   （token 只存在于 Next server env，不进浏览器 bundle）。
 * - SSR 路径（window undefined）：直连 Control API 绝对地址，读服务端专用密钥
 *   CONTROL_API_TOKEN 注入 Bearer。生产配 AVATARLOOM_API_TOKEN 后，缺这个会让
 *   所有 SSR 页面 401。
 *   注意：不要用 NEXT_PUBLIC_ 前缀——会打进客户端 bundle 泄漏。
 */

/** API 错误类——带 status 与精简 detail，调用方可按 e.message 渲染或 e instanceof ApiError 精细处理。 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(prefix: string, status: number, detail: string) {
    super(`${prefix} ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const MAX_DETAIL_LEN = 200;

/** detail 截断，避免把整个后端响应体（含 env 变量名、配置开关等）塞进错误 message 泄漏到 UI。 */
function trimDetail(raw: string): string {
  const t = raw.trim();
  return t.length > MAX_DETAIL_LEN ? t.slice(0, MAX_DETAIL_LEN) + "…" : t;
}

/** 浏览器走 Next rewrite（/api/control -> 8100/api）；SSR 直连 Control API 绝对地址。 */
const API_BASE = "/api/control";
const SERVER_API_BASE =
  process.env.CONTROL_API_BASE ?? "http://127.0.0.1:8100/api";
const GATEWAY_API_BASE = "/api/realtime";
const SERVER_GATEWAY_BASE =
  process.env.RUNTIME_GATEWAY_BASE ?? "http://127.0.0.1:8101/api";

function fetchBase(): string {
  return typeof window === "undefined" ? SERVER_API_BASE : API_BASE;
}

function gatewayFetchBase(): string {
  return typeof window === "undefined" ? SERVER_GATEWAY_BASE : GATEWAY_API_BASE;
}

/** SSR 时返回各后端的 Authorization header；浏览器返回空对象（同源代理由 middleware 注入）。 */
function ssrAuthHeaders(token?: string): Record<string, string> {
  if (typeof window !== "undefined") return {};
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${fetchBase()}${path}`, {
    // Next.js SSR fetch 默认 force-cache（结果持久化进 .next，进程重启也在）——
    // 列表/详情数据必须显式 no-store，否则 DB 更新后页面一直渲染旧缓存
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...ssrAuthHeaders(process.env.CONTROL_API_TOKEN),
      ...(init?.headers || {}),
    },
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new ApiError("API", r.status, trimDetail(detail));
  }
  return r.json() as Promise<T>;
}

/** Runtime Gateway 客户端（浏览器 /api/realtime/* → 8101/api/*；SSR 直连 + GATEWAY_API_TOKEN）。 */
export async function gatewayFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${gatewayFetchBase()}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...ssrAuthHeaders(process.env.GATEWAY_API_TOKEN),
      ...(init?.headers || {}),
    },
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new ApiError("Gateway", r.status, trimDetail(detail));
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
  const r = await fetch(`${fetchBase()}${path}`, {
    method: "POST",
    body: form,
    headers: { ...ssrAuthHeaders(process.env.CONTROL_API_TOKEN) },
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new ApiError("Upload", r.status, trimDetail(detail));
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
  settings: Record<string, unknown> | null;
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
  config_schema: Record<string, unknown> | null;
  install_extras: string[] | null;
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

/** Gateway 侧 RuntimeProfile（yaml 概要）——运行时真实装配来源（gateway /api/profiles）。 */
export interface GatewayProfile {
  id: string;
  name: string;
  description: string | null;
  blocks: Record<string, { id?: string; deployment?: string }>;
  memory: Record<string, unknown> | null;
}

export interface GatewayProfilesResponse {
  profiles: GatewayProfile[];
  default: string;
}
