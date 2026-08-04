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

/**
 * Realtime Playground 客户端——完整音频交互。
 *
 * 流程：
 *   麦克风 → AudioWorklet → 16kHz PCM → ws 二进制上行
 *   ws 二进制下行（0x03=PCM 播放，0x01=Avatar JPEG）→ 音画同步显示
 *
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

  useEffect(() => {
    llmDeltaRef.current = llmDelta;
  }, [llmDelta]);

  // 清理
  useEffect(() => {
    return () => {
      recorderRef.current?.stop();
      playerRef.current?.close();
      wsRef.current?.close();
    };
  }, []);

  const handleFrame = useCallback((frame: AvatarFrame) => {
    const blob = frame.blob instanceof Blob ? frame.blob : new Blob([frame.blob], { type: "image/jpeg" });
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

    // 初始化播放器和同步器
    playerRef.current = new PcmPlayer({ sampleRate: 16000, audioDelayMs: 600 });
    avmuxRef.current = new AVMux({ audioDelayMs: 600 }, handleFrame);

    const wsUrl = `ws://${window.location.hostname}:8101/ws/realtime`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setConn("connected");
      ws.send(JSON.stringify({ type: "session.start", payload: { profile_id: "mock" } }));
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
        // 打断时清空播放和帧
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
      // TTS PCM16 chunk
      const pcm = new Int16Array(data, 2); // 跳过 tag 字节
      playerRef.current?.enqueue(pcm);
      setPlaying(true);
      setDebugInfo((d) => ({ ...d, audioChunks: d.audioChunks + 1 }));
    } else if (tag === 0x01) {
      // Avatar JPEG: tag(1) + subtag(1) + jpeg
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
          // 发二进制 PCM（无 tag 前缀）
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

  const stateBadge = {
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
      {/* 左：控制 */}
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
          <h3 className="mb-3">状态</h3>
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-fg-muted">会话状态</span>
            <span className={stateBadge}>{sessionState}</span>
          </div>
          {sessionIdRef.current && (
            <div className="text-xs text-fg-subtle font-mono truncate">{sessionIdRef.current}</div>
          )}
        </div>

        <div className="card">
          <h3 className="mb-3">音频</h3>
          <div className="space-y-2">
            <button
              onClick={toggleMic}
              disabled={conn !== "connected"}
              className={clsx("btn w-full", micActive && "btn-primary")}
            >
              {micActive ? "停止麦克风" : "开启麦克风"}
            </button>
            {playing && (
              <button onClick={interrupt} className="btn w-full text-err">
                打断
              </button>
            )}
            <div className="flex gap-2 text-xs text-fg-muted">
              <span className={clsx("flex items-center gap-1", micActive && "text-ok")}>
                <span className={clsx("w-1.5 h-1.5 rounded-full", micActive ? "bg-ok" : "bg-fg-subtle")} />
                麦克风
              </span>
              <span className={clsx("flex items-center gap-1", playing && "text-ok")}>
                <span className={clsx("w-1.5 h-1.5 rounded-full", playing ? "bg-ok" : "bg-fg-subtle")} />
                播放
              </span>
            </div>
          </div>
        </div>

        <div className="card">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={showDebug}
              onChange={(e) => setShowDebug(e.target.checked)}
              className="accent-accent"
            />
            Debug Overlay
          </label>
          {showDebug && (
            <div className="mt-3 text-xs font-mono space-y-1 text-fg-muted">
              <div>frames: {debugInfo.framesShown}</div>
              <div>audio chunks: {debugInfo.audioChunks}</div>
              <div>queue: {debugInfo.queueLen}</div>
            </div>
          )}
        </div>
      </div>

      {/* 中：Avatar */}
      <div className="col-span-1">
        <div className="card aspect-[16/10] flex items-center justify-center bg-bg-subtle relative overflow-hidden">
          {frameUrl ? (
            <img src={frameUrl} alt="avatar" className="w-full h-full object-cover" />
          ) : (
            <div className="text-fg-subtle text-sm">Avatar 显示区</div>
          )}
          {showDebug && (
            <div className="absolute top-2 left-2 text-xs font-mono bg-black/60 text-white px-2 py-1 rounded">
              {sessionState}
            </div>
          )}
        </div>
      </div>

      {/* 右：转写 */}
      <div className="col-span-1">
        <div className="card h-[600px] flex flex-col">
          <h3 className="mb-3">对话</h3>
          {error && <div className="text-err text-sm mb-2">{error}</div>}
          <div className="flex-1 overflow-auto space-y-3">
            {transcript.length === 0 && !llmDelta && (
              <div className="text-fg-muted text-sm text-center py-12">
                {conn === "connected" ? "开启麦克风开始对话" : "点击「连接」开始"}
              </div>
            )}
            {transcript.map((item, i) => (
              <div key={i} className={clsx("text-sm", item.role === "user" ? "text-fg" : "text-fg-muted")}>
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
