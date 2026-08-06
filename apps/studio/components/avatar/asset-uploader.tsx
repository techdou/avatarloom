"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { clsx } from "clsx";
import { Loader2, UploadCloud, CheckCircle2 } from "lucide-react";
import { apiUpload, type AssetKind } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

interface AssetUploaderProps {
  avatarId: string;
  kind: AssetKind;
  label: string;
  accept: string;
  hint: string;
  hasCurrent: boolean;
}

/**
 * 资产上传组件——拖拽/点击选文件，上传后刷新页面 + toast 反馈。
 *
 * 不做客户端预览（避免复杂状态管理）——上传成功后 router.refresh() 让服务端
 * 重新渲染带新资产的页面，同时 toast 提示用户结果。简单可靠。
 */
export function AssetUploader({
  avatarId,
  kind,
  label,
  accept,
  hint,
  hasCurrent,
}: AssetUploaderProps) {
  const router = useRouter();
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      await apiUpload(`/avatars/${avatarId}/assets`, file, { kind });
      toast.success(`${label}上传成功：${file.name}`);
      router.refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(`${label}上传失败：${msg}`);
    } finally {
      setUploading(false);
    }
  }

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    // 清空 value 允许重复上传同名文件
    e.target.value = "";
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }

  return (
    <div className="border border-border rounded-md p-3 dark:border-border">
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-sm font-medium">{label}</div>
          <div className="text-xs text-fg-muted dark:text-fg-muted">{hint}</div>
        </div>
        {hasCurrent && (
          <span className="badge badge-ok text-micro">
            <CheckCircle2 className="w-3 h-3" />
            已设置
          </span>
        )}
      </div>
      <div
        onClick={() => !uploading && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={clsx(
          "border-2 border-dashed rounded-md p-4 text-center transition-colors",
          dragOver ? "border-accent bg-accent-soft dark:bg-accent/15" : "border-border hover:border-accent/50",
          uploading ? "cursor-wait opacity-70" : "cursor-pointer",
          "dark:border-border dark:hover:border-accent/50"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          onChange={onInputChange}
          className="hidden"
        />
        {uploading ? (
          <div className="flex items-center justify-center gap-2 text-sm text-fg-muted dark:text-fg-muted">
            <Loader2 className="w-4 h-4 animate-spin text-accent" />
            上传中…
          </div>
        ) : (
          <div className="flex items-center justify-center gap-2 text-sm text-fg-muted dark:text-fg-muted">
            <UploadCloud className="w-4 h-4" />
            点击或拖拽文件到此处上传
          </div>
        )}
      </div>
      {error && (
        <div className="text-err text-xs mt-2">{error}</div>
      )}
    </div>
  );
}
