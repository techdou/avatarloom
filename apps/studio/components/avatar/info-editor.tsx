"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

/**
 * Avatar 信息编辑——PATCH /avatars/{id}（name / description / avatar_block）。
 */
export function AvatarInfoEditor({
  avatarId,
  initialName,
  initialDescription,
  initialAvatarBlock,
}: {
  avatarId: string;
  initialName: string;
  initialDescription: string;
  initialAvatarBlock: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
  const [avatarBlock, setAvatarBlock] = useState(initialAvatarBlock);
  const [saving, setSaving] = useState(false);

  const dirty =
    name !== initialName ||
    description !== initialDescription ||
    avatarBlock !== initialAvatarBlock;

  async function save() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await apiFetch(`/avatars/${avatarId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() || null,
          avatar_block: avatarBlock || null,
        }),
      });
      toast.success("Avatar 信息已保存");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 mt-3 pt-3 border-t border-border">
      <div>
        <label className="block text-sm mb-1">名称</label>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="block text-sm mb-1">Avatar Block</label>
        <select
          className="input"
          value={avatarBlock}
          onChange={(e) => setAvatarBlock(e.target.value)}
        >
          <option value="">（未指定）</option>
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
        />
      </div>
      <button onClick={save} disabled={saving || !dirty || !name.trim()} className="btn btn-primary text-xs">
        {saving ? "保存中…" : "保存修改"}
      </button>
    </div>
  );
}
