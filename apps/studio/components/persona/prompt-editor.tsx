"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

/**
 * Persona 编辑器——修改 label / prompt（PATCH /personas/{id}）。
 * 与 VoiceTextEditor 同模式：保存成功 router.refresh() 让服务端重取。
 */
export function PersonaEditor({
  personaId,
  initialLabel,
  initialPrompt,
}: {
  personaId: string;
  initialLabel: string;
  initialPrompt: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const [label, setLabel] = useState(initialLabel);
  const [prompt, setPrompt] = useState(initialPrompt);
  const [saving, setSaving] = useState(false);

  const dirty = label !== initialLabel || prompt !== initialPrompt;

  async function save() {
    setSaving(true);
    try {
      await apiFetch(`/personas/${personaId}`, {
        method: "PATCH",
        body: JSON.stringify({
          label: label.trim() || null,
          prompt,
        }),
      });
      toast.success("人设已保存");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3">
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
          className="input min-h-[200px] text-sm font-mono"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="定义数字人的性格、语气与回复风格……"
        />
        <p className="text-xs text-fg-muted mt-1">
          保存后下个会话生效（进行中的对话不热更新）。
        </p>
      </div>
      <button
        onClick={save}
        disabled={saving || !dirty}
        className="btn btn-primary text-xs"
      >
        {saving ? "保存中…" : "保存修改"}
      </button>
    </div>
  );
}
