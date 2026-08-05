"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

/**
 * 创建 Persona 表单——参考 CreateAvatarForm 的模式。
 * Persona 与 Avatar 解耦：prompt 是核心字段，avatar_id 可选关联。
 */
export function CreatePersonaForm() {
  const router = useRouter();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!id.trim() || !name.trim()) {
      setError("ID 和名称必填");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch("/personas", {
        method: "POST",
        body: JSON.stringify({
          id: id.trim(),
          name: name.trim(),
          label: label.trim() || undefined,
          prompt: prompt.trim(),
        }),
      });
      router.push(`/personas/${id.trim()}`);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label className="block text-sm mb-1">ID *</label>
        <input
          className="input font-mono"
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="例如 friendly-assistant"
        />
        <p className="text-xs text-fg-muted mt-1">唯一标识，创建后不可改</p>
      </div>
      <div>
        <label className="block text-sm mb-1">名称 *</label>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="例如 客服小灵"
        />
      </div>
      <div>
        <label className="block text-sm mb-1">标签</label>
        <input
          className="input"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="例如 正式、活泼（可选）"
        />
      </div>
      <div>
        <label className="block text-sm mb-1">系统提示词</label>
        <textarea
          className="input min-h-[140px]"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="你是 AvatarLoom 的演示助手，语气亲切、回答简洁……"
        />
        <p className="text-xs text-fg-muted mt-1">
          定义数字人的性格、语气与回复风格。可后续编辑。
        </p>
      </div>
      {error && <div className="text-err text-sm">{error}</div>}
      <div className="flex gap-2">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting || !id.trim() || !name.trim()}
        >
          {submitting ? "创建中…" : "创建"}
        </button>
        <button
          type="button"
          onClick={() => router.back()}
          className="btn"
        >
          取消
        </button>
      </div>
    </form>
  );
}
