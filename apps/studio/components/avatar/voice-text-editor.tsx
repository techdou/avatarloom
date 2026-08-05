"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

export function VoiceTextEditor({
  avatarId,
  initialText,
}: {
  avatarId: string;
  initialText: string;
}) {
  const router = useRouter();
  const [text, setText] = useState(initialText);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await apiFetch(`/avatars/${avatarId}/voice-text`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      router.refresh();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <textarea
        className="input min-h-[80px] text-sm"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="例如：大家好，我是 AvatarLoom 的演示助手，很高兴认识你。"
      />
      <button
        onClick={save}
        disabled={saving || text === initialText}
        className="btn btn-primary mt-2 w-full text-xs"
      >
        {saving ? "保存中…" : "保存"}
      </button>
    </div>
  );
}
