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

// 类型定义（和后端 schemas 对齐——手工维护，避免代码生成复杂度）
export interface Project {
  id: string;
  name: string;
  description: string | null;
  status?: string;
  created_at: string;
  updated_at: string;
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
