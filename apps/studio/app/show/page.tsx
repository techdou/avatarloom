import { ShowcaseClient } from "@/components/playground/showcase-client";
import { DEFAULT_PERSONA_ID, DEFAULT_PROFILE_ID } from "@/lib/runtime-context";

/**
 * /show —— 独立移动端演示路由（无 sidebar / 配置 / 调试）。
 * Server Component：从 searchParams 读 profile / persona，传给 ShowcaseClient。
 * 该路由不在 (studio) 路由组内，因此不获得 AppShell，直接挂在 root layout 下。
 *
 * 示例：/show?persona=demo-assistant&profile=mock
 */
interface ShowPageProps {
  searchParams: { persona?: string; profile?: string };
}

export default function ShowPage({ searchParams }: ShowPageProps) {
  const profileId = searchParams.profile || DEFAULT_PROFILE_ID;
  const personaId = searchParams.persona || DEFAULT_PERSONA_ID;
  return <ShowcaseClient profileId={profileId} personaId={personaId} />;
}
