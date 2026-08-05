"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { clsx } from "clsx";
import { Mic, Square, Power, AlertCircle } from "lucide-react";
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
    const el = chatRef.current;
    // jsdom / 某些环境没有 scrollTo——guard 一下避免渲染期抛错
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
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
    void playerRef.current.resume();

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
      void playerRef.current?.resume();
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
          <div className="relative flex-1 min-h-0 bg-bg-subtle flex items-center justify-center overflow-hidden dark:bg-[#131318]">
            {frameUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={frameUrl} alt="avatar" className="w-full h-full object-cover" />
            ) : conn === "disconnected" || conn === "error" ? (
              // 未连接：有质感的引导态（大尺寸立绘占位 + 醒目 CTA）
              <WelcomePane conn={conn} error={error} onConnect={connect} />
            ) : (
              // 已连接但还没收到帧：精致占位 + 待机文案
              <PendingAvatar />
            )}
            {showDebug && (
              <div className="absolute top-2 left-2 text-[10px] font-mono bg-black/60 text-white px-2 py-1 rounded-md">
                {sessionState} · 帧 {debugInfo.framesShown}
              </div>
            )}
          </div>
          <div className="px-4 py-3 border-t border-border flex items-center justify-between dark:border-border">
            <div>
              <div className="text-sm font-medium">小灵 · Demo Assistant</div>
              <div className="text-[11px] text-fg-muted mt-0.5 dark:text-fg-muted">
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
              <div className="h-full flex flex-col items-center justify-center text-center text-fg-subtle px-6">
                <div className={clsx(
                  "w-14 h-14 rounded-2xl flex items-center justify-center mb-3 transition-colors",
                  conn === "connected"
                    ? "bg-accent-soft text-accent dark:bg-accent/15"
                    : "bg-border/40 text-fg-subtle"
                )}>
                  <Mic className="w-6 h-6" />
                </div>
                <div className="text-sm font-medium text-fg-muted dark:text-fg-muted mb-1">
                  {conn === "connected" ? "准备就绪" : "等待连接"}
                </div>
                <div className="text-xs">
                  {conn === "connected"
                    ? "点击下方麦克风按钮，开始语音对话。讲话时数字人会实时听写并回复。"
                    : "先连接 Runtime Gateway，再开启麦克风。"}
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
          <div className="px-4 py-3 border-t border-border flex items-center gap-2 dark:border-border">
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
              {micActive ? <Square className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
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

// ---------------------------------------------------------------------------
// 视觉占位子组件（纯展示，不参与数据流）
// ---------------------------------------------------------------------------

/** 未连接引导态：精致立绘占位 + 连接 CTA。 */
function WelcomePane({
  conn,
  error,
  onConnect,
}: {
  conn: ConnState;
  error: string | null;
  onConnect: () => void;
}) {
  const connecting = conn === "connecting";
  return (
    <div className="relative w-full h-full flex flex-col items-center justify-center px-6 py-8 text-center">
      {/* 背景：靛蓝径向光晕（克制，单一主色） */}
      <div
        aria-hidden
        className="absolute inset-0 opacity-[0.55] dark:opacity-40"
        style={{
          background:
            "radial-gradient(120% 90% at 50% 18%, rgba(79,70,229,0.14), rgba(79,70,229,0) 60%)",
        }}
      />
      {/* 大尺寸立绘占位 SVG */}
      <div className="relative mb-5">
        <div className="absolute -inset-6 rounded-full bg-accent/10 blur-2xl" aria-hidden />
        <AvatarPortrait />
      </div>

      <div className="relative max-w-xs">
        <div className="text-base font-semibold tracking-tight text-fg dark:text-[#ededf2]">
          实时数字人 · 小灵
        </div>
        <p className="text-xs text-fg-muted mt-1.5 leading-relaxed dark:text-fg-muted">
          连接 Runtime Gateway 即可开启低延迟语音对话。
          音频为主时钟，口型与表情自动同步。
        </p>

        {/* 能力 chips */}
        <div className="flex flex-wrap items-center justify-center gap-1.5 mt-3">
          <span className="badge badge-accent text-[10px]">DeepSeek LLM</span>
          <span className="badge text-[10px]">VoxCPM2 TTS</span>
          <span className="badge text-[10px]">MuseTalk</span>
        </div>

        <button
          type="button"
          onClick={onConnect}
          disabled={connecting}
          className="btn btn-primary w-full mt-4"
        >
          <Power className="w-4 h-4" />
          {connecting ? "连接中…" : "连接并开始"}
        </button>

        {error ? (
          <div className="mt-2.5 flex items-start gap-1.5 text-[11px] text-err text-left">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-snug">{error}</span>
          </div>
        ) : (
          <div className="mt-2.5 text-[11px] text-fg-subtle">
            需要本地 Runtime Gateway 监听 <code className="font-mono">:8101</code>
          </div>
        )}
      </div>
    </div>
  );
}

/** 已连接、等待第一帧的精致占位。 */
function PendingAvatar() {
  return (
    <div className="relative w-full h-full flex flex-col items-center justify-center">
      <div className="relative">
        <div className="absolute -inset-3 rounded-full bg-accent/10 blur-xl animate-pulse" aria-hidden />
        <AvatarPortrait dimmed />
      </div>
      <div className="mt-4 text-xs text-fg-muted dark:text-fg-muted flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
        等待角色画面…
      </div>
    </div>
  );
}

/** 复用的精致立绘 SVG——靛蓝单色调，无依赖外部资源。 */
function AvatarPortrait({ dimmed = false }: { dimmed?: boolean }) {
  return (
    <div
      className={clsx(
        "relative w-24 h-24 rounded-full overflow-hidden ring-1 ring-border shadow-card",
        dimmed && "opacity-70"
      )}
    >
      <svg viewBox="0 0 96 96" className="w-full h-full" aria-hidden>
        <defs>
          <linearGradient id="al-bg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#eef2ff" />
            <stop offset="100%" stopColor="#e0e7ff" />
          </linearGradient>
          <linearGradient id="al-fg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#4f46e5" />
            <stop offset="100%" stopColor="#4338ca" />
          </linearGradient>
        </defs>
        {/* 背景圆 */}
        <rect width="96" height="96" fill="url(#al-bg)" />
        {/* 头 */}
        <circle cx="48" cy="38" r="14" fill="url(#al-fg)" />
        {/* 肩 */}
        <path
          d="M20 84c0-13.255 12.536-24 28-24s28 10.745 28 24v12H20V84z"
          fill="url(#al-fg)"
        />
        {/* 高光眼/嘴占位（极淡） */}
        <circle cx="43" cy="37" r="1.6" fill="#ffffff" opacity="0.85" />
        <circle cx="53" cy="37" r="1.6" fill="#ffffff" opacity="0.85" />
      </svg>
    </div>
  );
}
