import Link from "next/link";
import { ImageOff } from "lucide-react";
import { apiFetch, avatarPortraitUrl, type Avatar } from "@/lib/api";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";

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
        <div className="mb-4">
          <ErrorBanner error={error} hint="请确认 control-api 服务已启动（默认端口 8100）" />
        </div>
      )}

      {avatars.length === 0 && !error ? (
        <EmptyState
          icon={<ImageOff className="w-5 h-5" />}
          title="暂无数字人形象"
          description="创建一个数字人形象，上传肖像图，独立于人设管理。"
          action={{ label: "创建第一个 Avatar", href: "/avatars/new" }}
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {avatars.map((av) => (
            <Link
              key={av.id}
              href={`/avatars/${av.id}`}
              className="card card-hover overflow-hidden p-0 group"
            >
              <div className="aspect-[5/4] bg-bg-subtle flex items-center justify-center overflow-hidden dark:bg-bg-subtle-dark">
                {av.portrait_path ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={avatarPortraitUrl(av.id)}
                    alt={av.name}
                    className="w-full h-full object-cover transition-transform group-hover:scale-[1.03]"
                  />
                ) : (
                  <div className="flex flex-col items-center gap-1 text-fg-subtle">
                    <ImageOff className="w-5 h-5" />
                    <span className="text-xs">无肖像</span>
                  </div>
                )}
              </div>
              <div className="p-3.5">
                <div className="font-medium text-sm truncate">{av.name}</div>
                <div className="flex items-center gap-1.5 mt-1.5">
                  <span className={`badge text-micro ${av.status === "active" ? "badge-ok" : ""}`}>
                    {av.status}
                  </span>
                  {av.avatar_block && (
                    <span className="badge text-micro font-mono">{av.avatar_block}</span>
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
