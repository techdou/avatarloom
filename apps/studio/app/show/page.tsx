import { ShowcaseClient } from "@/components/playground/showcase-client";

/**
 * /show —— 独立移动端演示路由（无 sidebar / 配置 / 调试）。
 * Server Component：从 searchParams 读 profile / persona，传给 ShowcaseClient。
 * 该路由不在 (studio) 路由组内，因此不获得 AppShell，直接挂在 root layout 下。
 *
 * 示例：/show?persona=demo-assistant&profile=autodl-best
 */
interface ShowPageProps {
  searchParams: { persona?: string; profile?: string };
}

export default function ShowPage({ searchParams }: ShowPageProps) {
  const profileId = searchParams.profile || "mock";
  const personaId = searchParams.persona || "demo-assistant";
  return <ShowcaseClient profileId={profileId} personaId={personaId} />;
}
