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
      <div className="page-header">
        <div>
          <h1 className="page-title">数字人形象</h1>
          <p className="page-desc">形象资产——独立于人设管理。上传肖像、Idle 视频、音色参考。</p>
        </div>
        <Link href="/avatars/new" className="btn btn-primary">新建</Link>
      </div>

      {error && (
        <div className="rounded-xl border border-err/30 bg-err/5 text-err text-sm px-4 py-3 mb-4">
          Control API 连接失败：{error}。请确认 control-api 服务已启动（默认端口 8100）。
        </div>
      )}

      {avatars.length === 0 && !error ? (
        <div className="card text-center text-fg-muted py-16">
          <div className="w-12 h-12 mx-auto rounded-full bg-accent-soft text-accent flex items-center justify-center mb-3">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-6 h-6">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" strokeLinecap="round" />
            </svg>
          </div>
          <div className="text-base mb-1.5">暂无 Avatar</div>
          <p className="text-sm mb-4">创建一个数字人形象，上传肖像图，独立于人设管理。</p>
          <Link href="/avatars/new" className="btn btn-primary">创建第一个 Avatar</Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {avatars.map((av) => (
            <Link
              key={av.id}
              href={`/avatars/${av.id}`}
              className="card card-hover overflow-hidden p-0 group"
            >
              <div className="aspect-[4/3] bg-bg-subtle flex items-center justify-center overflow-hidden">
                {av.portrait_path ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={avatarPortraitUrl(av.id)}
                    alt={av.name}
                    className="w-full h-full object-cover transition-transform group-hover:scale-[1.03]"
                  />
                ) : (
                  <div className="text-fg-subtle text-xs">无肖像</div>
                )}
              </div>
              <div className="p-3.5">
                <div className="font-medium text-sm truncate">{av.name}</div>
                <div className="flex items-center gap-1.5 mt-1.5">
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
