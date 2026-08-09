export interface WsTicketResponse {
  ticket: string | null;
  expires_at: number | null;
}

/** 连接 Gateway 前从同域 Next 服务端获取短期 WS 凭证。 */
export async function requestWsTicket(): Promise<string | null> {
  const response = await fetch("/api/realtime/ticket", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`WS 鉴权凭证获取失败（${response.status}）：${detail}`);
  }
  const result = (await response.json()) as WsTicketResponse;
  return result.ticket;
}
