"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { apiFetch, type Asset } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

/**
 * 资产列表（可删除）——DELETE /assets/{id}。
 * 删除 portrait/idle_video/voice_ref 类资产时后端会自动清掉 Avatar 当前引用。
 */
export function AssetList({ assets }: { assets: Asset[] }) {
  const router = useRouter();
  const toast = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);

  async function remove(asset: Asset) {
    setBusyId(asset.id);
    try {
      await apiFetch(`/assets/${asset.id}`, { method: "DELETE" });
      toast.success(`已删除：${asset.name}`);
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-1 max-h-48 overflow-auto">
      {assets.map((a) => (
        <div key={a.id} className="group flex items-center justify-between text-xs py-1">
          <span className="truncate flex-1">{a.name}</span>
          <span className="badge text-micro ml-2">{a.kind}</span>
          <button
            type="button"
            onClick={() => remove(a)}
            disabled={busyId === a.id}
            className="ml-2 text-fg-subtle hover:text-err disabled:opacity-50 shrink-0"
            title="删除此资产（若为当前引用会同时解除 Avatar 绑定）"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
