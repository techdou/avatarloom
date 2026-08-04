"use client";

import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";

type ConnState = "disconnected" | "connecting" | "connected" | "error";

interface TranscriptItem {
  role: "user" | "assistant";
  text: string;
  ts: number;
}

/**
 * Realtime Playground 客户端。
 *
 * 阶段 4：WS 连接 + session.start + 状态/转写显示骨架。
 * 阶段 5：AudioWorklet 采集 + PCM 播放 + 音画同步。
 */
export function PlaygroundClient() {
  const [conn, setConn] = useState<ConnState>("disconnected");
  const [sessionState, setSessionState] = useState<string>("idle");
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [llmDelta, setLlmDelta] = useState("");
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  // WS 消息处理
  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  async function connect() {
    setConn("connecting");
    setError(null);
    // 确定 ws url——开发环境同源，生产环境需配
    const wsUrl = `ws://${window.location.hostname}:8101/ws/realtime`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setConn("connected");
      ws.send(JSON.stringify({ type: "session.start", payload: { profile_id: "mock" } }));
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return; // 二进制阶段 5 处理
      try {
        const msg = JSON.parse(ev.data);
        handleMessage(msg);
      } catch {
        // ignore
      }
    };
    ws.onerror = () => {
      setConn("error");
      setError("WebSocket 连接失败——确认 Runtime Gateway 已启动（端口 8101）");
    };
    ws.onclose = () => {
      setConn("disconnected");
      setSessionState("idle");
    };
  }

  function disconnect() {
    wsRef.current?.send(JSON.stringify({ type: "session.stop" }));
    wsRef.current?.close();
    wsRef.current = null;
    setConn("disconnected");
  }

  function handleMessage(msg: { type: string; payload?: Record<string, unknown> }) {
    switch (msg.type) {
      case "session.started":
        sessionIdRef.current = (msg.payload?.session_id as string) || null;
        setSessionState((msg.payload?.state as string) || "idle");
        break;
      case "session.state_changed":
        setSessionState((msg.payload?.to as string) || "idle");
        break;
      case "transcript.completed": {
        const text = (msg.payload?.text as string) || "";
        if (text) {
          setTranscript((prev) => [...prev, { role: "user", text, ts: Date.now() }]);
          setLlmDelta("");
        }
        break;
      }
      case "llm.text.delta": {
        const t = (msg.payload?.text as string) || "";
        setLlmDelta((prev) => prev + t);
        break;
      }
      case "llm.text.done": {
        const full = (msg.payload?.full_text as string) || llmDelta;
        if (full) {
          setTranscript((prev) => [...prev, { role: "assistant", text: full, ts: Date.now() }]);
        }
        setLlmDelta("");
        break;
      }
      case "error":
        setError((msg.payload?.message as string) || "unknown error");
        break;
    }
  }

  const stateColor = {
    idle: "badge",
    listening: "badge badge-ok",
    transcribing: "badge badge-warn",
    thinking: "badge badge-warn",
    speaking: "badge badge-ok",
    interrupting: "badge badge-err",
    error: "badge badge-err",
  }[sessionState] || "badge";

  return (
    <div className="grid grid-cols-3 gap-4">
      {/* 左：状态 + 控制 */}
      <div className="col-span-1 space-y-4">
        <div className="card">
          <h3 className="mb-3">连接</h3>
          <div className="flex items-center gap-2 mb-3">
            <span className={clsx(
              "w-2 h-2 rounded-full",
              conn === "connected" ? "bg-ok" : conn === "connecting" ? "bg-warn" : conn === "error" ? "bg-err" : "bg-fg-subtle"
            )} />
            <span className="text-sm">{conn}</span>
          </div>
          {conn === "connected" ? (
            <button onClick={disconnect} className="btn w-full">断开</button>
          ) : (
            <button onClick={connect} className="btn btn-primary w-full" disabled={conn === "connecting"}>
              {conn === "connecting" ? "连接中…" : "连接"}
            </button>
          )}
        </div>

        <div className="card">
          <h3 className="mb-3">状态机</h3>
          <div className="flex items-center justify-between">
            <span className="text-sm text-fg-muted">当前</span>
            <span className={stateColor}>{sessionState}</span>
          </div>
          {sessionIdRef.current && (
            <div className="text-xs text-fg-subtle mt-2 font-mono">{sessionIdRef.current}</div>
          )}
        </div>

        <div className="card">
          <h3 className="mb-2">音频</h3>
          <p className="text-xs text-fg-muted">
            阶段 5 实装麦克风采集与 PCM 播放。当前显示文字交互。
          </p>
        </div>
      </div>

      {/* 右：转写 */}
      <div className="col-span-2">
        <div className="card h-[600px] flex flex-col">
          <h3 className="mb-3">对话</h3>
          {error && <div className="text-err text-sm mb-2">{error}</div>}
          <div className="flex-1 overflow-auto space-y-3">
            {transcript.length === 0 && !llmDelta && (
              <div className="text-fg-muted text-sm text-center py-12">
                {conn === "connected" ? "对话会显示在这里" : "点击「连接」开始"}
              </div>
            )}
            {transcript.map((item, i) => (
              <div key={i} className={clsx(
                "text-sm",
                item.role === "user" ? "text-fg" : "text-fg-muted"
              )}>
                <span className="text-xs text-fg-subtle mr-2">
                  {item.role === "user" ? "用户" : "助手"}
                </span>
                {item.text}
              </div>
            ))}
            {llmDelta && (
              <div className="text-sm text-fg-muted">
                <span className="text-xs text-fg-subtle mr-2">助手</span>
                {llmDelta}
                <span className="inline-block w-1 h-4 bg-accent ml-0.5 animate-pulse" />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
