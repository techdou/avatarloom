import Link from "next/link";
import { notFound } from "next/navigation";
import {
  apiFetch,
  avatarIdleVideoUrl,
  avatarPortraitUrl,
  avatarVoiceRefUrl,
  type Asset,
  type Avatar,
} from "@/lib/api";
import { AssetUploader } from "@/components/avatar/asset-uploader";
import { VoiceTextEditor } from "@/components/avatar/voice-text-editor";

interface PageProps {
  params: { id: string };
}

async function getAvatar(id: string): Promise<Avatar | null> {
  try {
    return await apiFetch<Avatar>(`/avatars/${id}`);
  } catch {
    return null;
  }
}

async function getAssets(id: string): Promise<Asset[]> {
  try {
    return await apiFetch<Asset[]>(`/avatars/${id}/assets`);
  } catch {
    return [];
  }
}

export default async function AvatarDetailPage({ params }: PageProps) {
  const avatar = await getAvatar(params.id);
  if (!avatar) {
    notFound();
  }
  const assets = await getAssets(params.id);

  return (
    <div>
      {/* 顶部导航 */}
      <div className="flex items-center gap-3 mb-6 text-sm">
        <Link href="/avatars" className="text-fg-muted hover:text-fg">← Avatars</Link>
        <span className="text-fg-subtle">/</span>
        <span className="font-medium">{avatar.name}</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左：信息 */}
        <div className="space-y-4">
          <div className="card">
            <h3 className="mb-3">基本信息</h3>
            <dl className="text-sm space-y-2">
              <InfoRow label="ID" value={<code className="text-xs">{avatar.id}</code>} />
              <InfoRow label="名称" value={avatar.name} />
              <InfoRow label="状态" value={
                <span className={`badge text-xs ${avatar.status === "active" ? "badge-ok" : ""}`}>
                  {avatar.status}
                </span>
              } />
              <InfoRow label="Block" value={
                <code className="text-xs">{avatar.avatar_block || "—"}</code>
              } />
            </dl>
            {avatar.description && (
              <div className="mt-3 pt-3 border-t border-border">
                <div className="text-xs text-fg-muted mb-1">描述</div>
                <div className="text-sm">{avatar.description}</div>
              </div>
            )}
          </div>

          {/* 音色参考文本 */}
          <div className="card">
            <h3 className="mb-2">音色参考文本</h3>
            <p className="text-xs text-fg-muted mb-3">
              TTS 用——克隆音色时逐字朗读的参考文本。
            </p>
            <VoiceTextEditor
              avatarId={avatar.id}
              initialText={avatar.voice_ref_text || ""}
            />
          </div>
        </div>

        {/* 中：预览 */}
        <div className="space-y-4">
          <div className="card">
            <h3 className="mb-3">肖像预览</h3>
            <div className="aspect-[4/3] bg-bg-subtle rounded-md overflow-hidden flex items-center justify-center">
              {avatar.portrait_path ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={avatarPortraitUrl(avatar.id)}
                  alt={avatar.name}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="text-fg-subtle text-sm">未上传肖像图</div>
              )}
            </div>
          </div>

          <div className="card">
            <h3 className="mb-3">Idle 待机视频</h3>
            {avatar.idle_video_path ? (
              <video
                src={avatarIdleVideoUrl(avatar.id)}
                controls
                loop
                muted
                autoPlay
                className="w-full rounded-md"
              />
            ) : (
              <div className="aspect-video bg-bg-subtle rounded-md flex items-center justify-center text-fg-subtle text-sm">
                未上传 idle 视频
              </div>
            )}
          </div>

          <div className="card">
            <h3 className="mb-3">音色参考</h3>
            {avatar.voice_ref_path ? (
              <div>
                <audio src={avatarVoiceRefUrl(avatar.id)} controls className="w-full" />
              </div>
            ) : (
              <div className="py-6 text-center text-fg-subtle text-sm">
                未上传音色参考音频
              </div>
            )}
          </div>
        </div>

        {/* 右：上传 */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-fg-muted">资产上传</h3>
          <AssetUploader
            avatarId={avatar.id}
            kind="portrait"
            label="肖像图"
            accept="image/png,image/jpeg"
            hint="PNG/JPG，建议 1280×720"
            hasCurrent={!!avatar.portrait_path}
          />
          <AssetUploader
            avatarId={avatar.id}
            kind="idle_video"
            label="Idle 待机视频"
            accept="video/mp4,video/webm"
            hint="MP4/WebM，25fps 微动循环"
            hasCurrent={!!avatar.idle_video_path}
          />
          <AssetUploader
            avatarId={avatar.id}
            kind="voice_ref"
            label="音色参考音频"
            accept="audio/wav,audio/mpeg"
            hint="WAV/MP3，5-15 秒清晰人声"
            hasCurrent={!!avatar.voice_ref_path}
          />

          {/* 已上传资产历史 */}
          {assets.length > 0 && (
            <div className="mt-4 pt-4 border-t border-border">
              <div className="text-xs text-fg-muted mb-2">所有资产（{assets.length}）</div>
              <div className="space-y-1 max-h-48 overflow-auto">
                {assets.map((a) => (
                  <div key={a.id} className="flex items-center justify-between text-xs py-1">
                    <span className="truncate flex-1">{a.name}</span>
                    <span className="badge text-[10px] ml-2">{a.kind}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center">
      <dt className="text-fg-muted">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
