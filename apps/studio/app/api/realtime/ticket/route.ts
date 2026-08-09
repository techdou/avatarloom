import { createHmac, randomBytes } from "node:crypto";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const TICKET_TTL_SECONDS = 60;

function sameOrigin(request: Request): boolean {
  const site = request.headers.get("sec-fetch-site");
  if (site === "cross-site") return false;
  const origin = request.headers.get("origin");
  return !origin || origin === new URL(request.url).origin;
}

export async function POST(request: Request): Promise<Response> {
  if (!sameOrigin(request)) {
    return Response.json({ detail: "Cross-origin ticket request rejected." }, { status: 403 });
  }

  const token = process.env.AVATARLOOM_API_TOKEN?.trim();
  if (!token) {
    const authDisabled = /^(1|true|yes)$/i.test(
      process.env.AVATARLOOM_AUTH_DISABLED?.trim() ?? ""
    );
    if (!authDisabled) {
      return Response.json(
        { detail: "WebSocket authentication is not configured." },
        { status: 503, headers: { "Cache-Control": "no-store" } }
      );
    }
    return Response.json(
      { ticket: null, expires_at: null },
      { headers: { "Cache-Control": "no-store" } }
    );
  }

  const exp = Math.floor(Date.now() / 1000) + TICKET_TTL_SECONDS;
  const payload = {
    aud: "avatarloom-ws",
    exp,
    nonce: randomBytes(16).toString("base64url"),
  };
  const encodedPayload = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = createHmac("sha256", token)
    .update(encodedPayload, "ascii")
    .digest("base64url");

  return Response.json(
    { ticket: `${encodedPayload}.${signature}`, expires_at: exp },
    { headers: { "Cache-Control": "no-store" } }
  );
}
