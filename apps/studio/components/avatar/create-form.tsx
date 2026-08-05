"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

export function CreateAvatarForm() {
  const router = useRouter();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [avatarBlock, setAvatarBlock] = useState("avatar.static");
  const [description, setDescription] = useState("");
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
      await apiFetch("/avatars", {
        method: "POST",
        body: JSON.stringify({
          id: id.trim(),
          project_id: "default",
          name: name.trim(),
          avatar_block: avatarBlock || undefined,
          description: description.trim() || undefined,
        }),
      });
      router.push(`/avatars/${id.trim()}`);
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
          placeholder="例如 customer-service"
        />
        <p className="text-xs text-fg-muted mt-1">唯一标识，创建后不可改</p>
      </div>
      <div>
        <label className="block text-sm mb-1">名称 *</label>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="例如 客服小妹"
        />
      </div>
      <div>
        <label className="block text-sm mb-1">Avatar Block</label>
        <select
          className="input"
          value={avatarBlock}
          onChange={(e) => setAvatarBlock(e.target.value)}
        >
          <option value="avatar.static">avatar.static（静态肖像）</option>
          <option value="avatar.mock">avatar.mock（占位 Mock）</option>
          <option value="avatar.musetalk">avatar.musetalk（MuseTalk 口型驱动，需 GPU）</option>
        </select>
      </div>
      <div>
        <label className="block text-sm mb-1">描述</label>
        <textarea
          className="input min-h-[60px]"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="这个 Avatar 的用途说明（可选）"
        />
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
