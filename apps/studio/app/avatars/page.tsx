import Link from "next/link";
import { apiFetch, avatarPortraitUrl, type Avatar } from "@/lib/api";

async function getAvatars(): Promise<{ avatars: Avatar[]; error: string | null }> {
  try {
    const avatars = await apiFetch<Avatar[]>("/avatars");
    return { avatars, error: null };
  } catch (e) {
    return { avatars: [], error: e instanceof Error ? e.message : String(e) };
  }
}

export default async function AvatarsPage() {
  const { avatars, error } = await getAvatars();

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1>Avatars</h1>
          <p className="text-sm text-fg-muted mt-1">
            数字人形象资产——独立于人设管理。上传肖像、idle 视频、音色参考。
          </p>
        </div>
        <Link href="/avatars/new" className="btn btn-primary">新建</Link>
      </div>

      {error && (
        <div className="card border-err/40 text-err text-sm mb-4">
          Control API 连接失败：{error}。请确认 control-api 服务已启动（端口 8100）。
        </div>
      )}

      {avatars.length === 0 && !error ? (
        <div className="card text-center text-fg-muted py-16">
          <div className="text-base mb-2">暂无 Avatar</div>
          <p className="text-sm mb-4">创建一个数字人形象，上传肖像图，独立于人设管理。</p>
          <Link href="/avatars/new" className="btn btn-primary">创建第一个 Avatar</Link>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {avatars.map((av) => (
            <Link
              key={av.id}
              href={`/avatars/${av.id}`}
              className="card hover:border-accent transition-colors overflow-hidden p-0"
            >
              {/* 肖像缩略图 */}
              <div className="aspect-[4/3] bg-bg-subtle flex items-center justify-center overflow-hidden">
                {av.portrait_path ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={avatarPortraitUrl(av.id)}
                    alt={av.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="text-fg-subtle text-xs">无肖像</div>
                )}
              </div>
              {/* 信息 */}
              <div className="p-3">
                <div className="font-medium text-sm truncate">{av.name}</div>
                <div className="flex items-center gap-1 mt-1">
                  <span className={`badge text-[10px] ${av.status === "active" ? "badge-ok" : ""}`}>
                    {av.status}
                  </span>
                  {av.avatar_block && (
                    <span className="badge text-[10px] font-mono">{av.avatar_block}</span>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
