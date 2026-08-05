"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { clsx } from "clsx";
import { MicrophoneRecorder } from "@/lib/audio/recorder";
import { PcmPlayer } from "@/lib/audio/player";
import { AVMux, type AvatarFrame } from "@/lib/audio/sync";

type ConnState = "disconnected" | "connecting" | "connected" | "error";

interface TranscriptItem {
  role: "user" | "assistant";
  text: string;
  ts: number;
}

const STATE_META: Record<string, { label: string; badge: string }> = {
  idle: { label: "待机", badge: "" },
  listening: { label: "聆听中", badge: "badge-ok" },
  transcribing: { label: "识别中", badge: "badge-warn" },
  thinking: { label: "思考中", badge: "badge-accent" },
  speaking: { label: "回复中", badge: "badge-ok" },
  interrupting: { label: "打断", badge: "badge-err" },
  error: { label: "异常", badge: "badge-err" },
};

/**
 * Realtime Playground —— 简洁对话式 Avatar 界面。
 * 流程：麦克风 → AudioWorklet → 16kHz PCM → ws 上行；
 *       ws 二进制下行（0x03=PCM 播放，0x01=Avatar JPEG）→ 音画同步显示。
 * 音频是主时钟：PcmPlayer 用 AudioContext.currentTime 调度，AVMux 按节奏消费帧。
 */
export function PlaygroundClient() {
  const [conn, setConn] = useState<ConnState>("disconnected");
  const [sessionState, setSessionState] = useState<string>("idle");
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [llmDelta, setLlmDelta] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [micActive, setMicActive] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [debugInfo, setDebugInfo] = useState({ framesShown: 0, audioChunks: 0, queueLen: 0 });
  const [showDebug, setShowDebug] = useState(false);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const recorderRef = useRef<MicrophoneRecorder | null>(null);
  const playerRef = useRef<PcmPlayer | null>(null);
  const avmuxRef = useRef<AVMux | null>(null);
  const llmDeltaRef = useRef("");
  const chatRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    llmDeltaRef.current = llmDelta;
  }, [llmDelta]);

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
  }, [transcript, llmDelta]);

  useEffect(() => {
    return () => {
      recorderRef.current?.stop();
      playerRef.current?.close();
      wsRef.current?.close();
    };
  }, []);

  const handleFrame = useCallback((frame: AvatarFrame) => {
    const blob =
      frame.blob instanceof Blob ? frame.blob : new Blob([frame.blob], { type: "image/jpeg" });
    const url = URL.createObjectURL(blob);
    setFrameUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return url;
    });
    setDebugInfo((d) => ({ ...d, framesShown: d.framesShown + 1 }));
  }, []);

  async function connect() {
    setConn("connecting");
    setError(null);

    playerRef.current = new PcmPlayer({ sampleRate: 16000, audioDelayMs: 600 });
    avmuxRef.current = new AVMux({ audioDelayMs: 600 }, handleFrame);

    const wsUrl = `ws://${window.location.hostname}:8101/ws/realtime`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setConn("connected");
      ws.send(
        JSON.stringify({
          type: "session.start",
          payload: { profile_id: "autodl-best" },
        })
      );
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          handleMessage(JSON.parse(ev.data));
        } catch {
          /* ignore */
        }
      } else if (ev.data instanceof ArrayBuffer) {
        handleBinary(ev.data);
      }
    };
    ws.onerror = () => {
      setConn("error");
      setError("WebSocket 连接失败——确认 Runtime Gateway 已启动（端口 8101）");
    };
    ws.onclose = () => {
      setConn("disconnected");
      setSessionState("idle");
      setMicActive(false);
    };
  }

  function disconnect() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setMicActive(false);
    wsRef.current?.send(JSON.stringify({ type: "session.stop" }));
    wsRef.current?.close();
    wsRef.current = null;
    setConn("disconnected");
    playerRef.current?.close();
    playerRef.current = null;
  }

  function handleMessage(msg: { type: string; payload?: Record<string, unknown> }) {
    switch (msg.type) {
      case "session.started":
        sessionIdRef.current = (msg.payload?.session_id as string) || null;
        setSessionState((msg.payload?.state as string) || "idle");
        break;
      case "session.state_changed":
        setSessionState((msg.payload?.to as string) || "idle");
        if (msg.payload?.to === "interrupting") {
          playerRef.current?.interrupt();
          avmuxRef.current?.interrupt();
        }
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
        const full = (msg.payload?.full_text as string) || llmDeltaRef.current;
        if (full) {
          setTranscript((prev) => [...prev, { role: "assistant", text: full, ts: Date.now() }]);
        }
        setLlmDelta("");
        break;
      }
      case "tts.audio.delta":
        // 元数据——实际 PCM 在二进制消息里
        break;
      case "response.done":
        setPlaying(false);
        break;
      case "error":
        setError((msg.payload?.message as string) || "unknown error");
        break;
    }
  }

  function handleBinary(data: ArrayBuffer) {
    const view = new Uint8Array(data);
    if (view.length === 0) return;
    const tag = view[0];

    if (tag === 0x03) {
      const pcm = new Int16Array(data, 2);
      playerRef.current?.enqueue(pcm);
      setPlaying(true);
      setDebugInfo((d) => ({ ...d, audioChunks: d.audioChunks + 1 }));
    } else if (tag === 0x01) {
      const subtag = view[1] ?? 0;
      const jpeg = data.slice(2);
      avmuxRef.current?.pushFrame({
        blob: jpeg,
        tag: subtag === 0x01 ? "speech" : "idle",
      });
      setDebugInfo((d) => ({ ...d, queueLen: avmuxRef.current?.queueLength ?? 0 }));
    }
  }

  async function toggleMic() {
    if (micActive) {
      recorderRef.current?.stop();
      recorderRef.current = null;
      setMicActive(false);
    } else {
      if (!wsRef.current || conn !== "connected") return;
      recorderRef.current = new MicrophoneRecorder({
        targetSampleRate: 16000,
        onChunk: (pcm) => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(pcm.buffer);
          }
        },
        onError: (e) => setError(`麦克风错误：${e.message}`),
      });
      await recorderRef.current.start();
      setMicActive(true);
    }
  }

  function interrupt() {
    wsRef.current?.send(JSON.stringify({ type: "audio.interrupt" }));
    playerRef.current?.interrupt();
    avmuxRef.current?.interrupt();
  }

  const stateMeta = STATE_META[sessionState] || STATE_META.idle;
  const connDot = {
    connected: "bg-ok",
    connecting: "bg-warn animate-pulse",
    error: "bg-err",
    disconnected: "bg-fg-subtle",
  }[conn];

  return (
    <div className="flex flex-col gap-4 h-[calc(100vh-8rem)]">
      {/* 顶部连接条 */}
      <div className="card flex items-center justify-between gap-3 py-3">
        <div className="flex items-center gap-3">
          <span className={clsx("w-2.5 h-2.5 rounded-full", connDot)} />
          <div>
            <div className="text-sm font-medium leading-none">
              {conn === "connected" ? "已连接 Runtime Gateway" : conn === "connecting" ? "连接中…" : conn === "error" ? "连接失败" : "未连接"}
            </div>
            <div className="text-[11px] text-fg-muted mt-1 font-mono">
              autodl-best · DeepSeek + VoxCPM2 + MuseTalk
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={clsx("badge", stateMeta.badge)}>{stateMeta.label}</span>
          {conn === "connected" ? (
            <button onClick={disconnect} className="btn btn-sm btn-danger">
              断开
            </button>
          ) : (
            <button onClick={connect} className="btn btn-sm btn-primary" disabled={conn === "connecting"}>
              {conn === "connecting" ? "连接中…" : "连接"}
            </button>
          )}
        </div>
      </div>

      {/* 主区：角色 + 对话 */}
      <div className="grid grid-cols-1 md:grid-cols-[minmax(280px,340px)_1fr] gap-4 flex-1 min-h-0">
        {/* Avatar 角色卡片 */}
        <div className="card flex flex-col overflow-hidden p-0">
          <div className="relative flex-1 min-h-0 bg-bg-subtle flex items-center justify-center overflow-hidden">
            {frameUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={frameUrl} alt="avatar" className="w-full h-full object-cover" />
            ) : (
              <div className="text-center text-fg-subtle">
                <div className="w-14 h-14 mx-auto rounded-full bg-border/60 flex items-center justify-center mb-2">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-7 h-7">
                    <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM5 21a7 7 0 0 1 14 0" strokeLinecap="round" />
                  </svg>
                </div>
                <div className="text-xs">等待角色画面…</div>
              </div>
            )}
            {showDebug && (
              <div className="absolute top-2 left-2 text-[10px] font-mono bg-black/60 text-white px-2 py-1 rounded-md">
                {sessionState} · 帧 {debugInfo.framesShown}
              </div>
            )}
          </div>
          <div className="px-4 py-3 border-t border-border flex items-center justify-between">
            <div>
              <div className="text-sm font-medium">小灵 · Demo Assistant</div>
              <div className="text-[11px] text-fg-muted mt-0.5">
                {micActive ? "正在聆听…" : playing ? "正在回复…" : "待机"}
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <span className={clsx("flex items-center gap-1 text-[11px]", micActive ? "text-ok" : "text-fg-subtle")}>
                <span className={clsx("w-1.5 h-1.5 rounded-full", micActive ? "bg-ok animate-pulse" : "bg-fg-subtle")} />
                麦
              </span>
              <span className={clsx("flex items-center gap-1 text-[11px]", playing ? "text-ok" : "text-fg-subtle")}>
                <span className={clsx("w-1.5 h-1.5 rounded-full", playing ? "bg-ok" : "bg-fg-subtle")} />
                播
              </span>
            </div>
          </div>
        </div>

        {/* 对话面板 */}
        <div className="card flex flex-col p-0 min-h-0">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <div className="text-sm font-medium">对话</div>
            {sessionIdRef.current && (
              <div className="text-[10px] font-mono text-fg-subtle truncate max-w-[260px]">
                {sessionIdRef.current}
              </div>
            )}
          </div>

          <div ref={chatRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
            {error && (
              <div className="rounded-lg border border-err/30 bg-err/5 text-err text-xs px-3 py-2">
                {error}
              </div>
            )}
            {transcript.length === 0 && !llmDelta && (
              <div className="h-full flex flex-col items-center justify-center text-fg-subtle text-sm">
                <div className="w-12 h-12 rounded-full bg-accent-soft text-accent flex items-center justify-center mb-3">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-6 h-6">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div className="text-xs">
                  {conn === "connected" ? "点击下方麦克风，开始语音对话" : "先连接 Gateway，再开启麦克风"}
                </div>
              </div>
            )}
            {transcript.map((item, i) => (
              <div key={i} className={clsx("flex", item.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={clsx(
                    "max-w-[78%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-card",
                    item.role === "user"
                      ? "bg-accent-soft text-fg rounded-br-md"
                      : "bg-white border border-border rounded-bl-md"
                  )}
                >
                  <div className="text-[10px] text-fg-subtle mb-1">
                    {item.role === "user" ? "你" : "小灵"}
                  </div>
                  <div className="whitespace-pre-wrap break-words">{item.text}</div>
                </div>
              </div>
            ))}
            {llmDelta && (
              <div className="flex justify-start">
                <div className="max-w-[78%] rounded-2xl rounded-bl-md bg-white border border-border px-3.5 py-2.5 text-sm leading-relaxed shadow-card">
                  <div className="text-[10px] text-fg-subtle mb-1">小灵 · 思考中</div>
                  <div className="whitespace-pre-wrap break-words">
                    {llmDelta}
                    <span className="inline-block w-1.5 h-3.5 bg-accent ml-0.5 align-middle animate-pulse" />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* 底部控制条 */}
          <div className="px-4 py-3 border-t border-border flex items-center gap-2">
            <button
              onClick={toggleMic}
              disabled={conn !== "connected"}
              className={clsx(
                "inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all active:scale-[0.98]",
                micActive
                  ? "bg-err/10 text-err border border-err/30"
                  : "bg-accent text-white border border-accent shadow-accent disabled:opacity-40"
              )}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-4 h-4">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {micActive ? "停止麦克风" : "开始说话"}
            </button>
            {playing && (
              <button onClick={interrupt} className="btn btn-danger">
                打断
              </button>
            )}
            <div className="ml-auto flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-fg-muted cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showDebug}
                  onChange={(e) => setShowDebug(e.target.checked)}
                  className="accent-accent w-3.5 h-3.5"
                />
                Debug
              </label>
              {showDebug && (
                <span className="text-[10px] font-mono text-fg-subtle">
                  {debugInfo.framesShown}f · {debugInfo.audioChunks}a · q{debugInfo.queueLen}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
