import { proxyApiRequest } from "@/lib/server/api-proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface RouteContext {
  params: { path: string[] };
}

function handler(request: Request, context: RouteContext) {
  return proxyApiRequest(request, "control", context.params.path);
}

export const GET = handler;
export const HEAD = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const OPTIONS = handler;
