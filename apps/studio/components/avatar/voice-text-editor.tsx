"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

export function VoiceTextEditor({
  avatarId,
  initialText,
}: {
  avatarId: string;
  initialText: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const [text, setText] = useState(initialText);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await apiFetch(`/avatars/${avatarId}/voice-text`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      toast.success("语音文案已保存");
      router.refresh();
    } catch (e) {
      // apiFetch 非 2xx 抛 ApiError——此前无 catch 成 unhandled rejection，
      // 按钮复位但界面无提示，用户误以为保存成功
      toast.error(e instanceof Error ? e.message : String(e));
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
