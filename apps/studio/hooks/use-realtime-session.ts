"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MicrophoneRecorder } from "@/lib/audio/recorder";
import { PcmPlayer } from "@/lib/audio/player";
import { AVMux, type AvatarFrame } from "@/lib/audio/sync";

export type ConnState = "disconnected" | "connecting" | "connected" | "error";

/** 会话状态 → 徽章文案/样式。渲染层共享，避免重复定义。 */
export const STATE_META_FALLBACK: Record<string, { label: string; badge: string }> = {
  idle: { label: "待机", badge: "" },
  listening: { label: "聆听中", badge: "badge-ok" },
  transcribing: { label: "识别中", badge: "badge-warn" },
  thinking: { label: "思考中", badge: "badge-accent" },
  speaking: { label: "回复中", badge: "badge-ok" },
  interrupting: { label: "打断", badge: "badge-err" },
  error: { label: "异常", badge: "badge-err" },
};

export interface TranscriptItem {
  role: "user" | "assistant";
  text: string;
  ts: number;
}

/** 关键里程碑时间戳（相对 session 开始）。debug drawer / showcase 字幕用。 */
export interface SessionTiming {
  /** transcript.completed 时刻（用户说完）。作为 t0 基准。 */
  transcriptTs: number | null;
  /** llm.text.delta 首次时刻 */
  firstDeltaTs: number | null;
  /** 首个二进制 PCM（0x03）时刻 */
  firstPcmTs: number | null;
  /** 首个二进制 JPEG（0x01）时刻 */
  firstFrameTs: number | null;
}

export interface DebugInfo {
  framesShown: number;
  audioChunks: number;
  queueLen: number;
  framesSent: number; // 摄像头截帧上行次数（vision）
}

export interface UseRealtimeSessionArgs {
  profileId: string;
  personaId: string;
  /** true 时挂载即自动连接（showcase 用）。默认 false。 */
  autoConnect?: boolean;
}

export interface RealtimeSession {
  conn: ConnState;
  sessionState: string;
  sessionId: string | null;
  transcript: TranscriptItem[];
  llmDelta: string;
  frameUrl: string | null;
  micActive: boolean;
  playing: boolean;
  error: string | null;
  debugInfo: DebugInfo;
  timing: SessionTiming;
  connect: () => Promise<void>;
  disconnect: () => void;
  toggleMic: () => Promise<void>;
  interrupt: () => void;
  captureAndSendFrame: () => Promise<void>;
}

/**
 * 实时会话核心 hook——WebSocket 连接/断开/消息处理/二进制解析、PcmPlayer + AVMux +
 * MicrophoneRecorder 生命周期管理全部集中在此。渲染层（PlaygroundClient / ShowcaseClient）
 * 只消费返回值，不再直接持有 ws/audio ref。
 *
 * 音频是主时钟：PcmPlayer 用 AudioContext.currentTime 调度，AVMux 按节奏消费帧。
 * 二进制协议：首字节 tag，0x03=PCM（offset 2 起 Int16），0x01=Avatar JPEG（subtag 在 byte[1]）。
 *
 * profile/persona 变更不会自动重连——调用方应 disconnect() 再 connect()。
 * autoConnect=true 时，挂载 + profile/persona 就绪即连一次；卸载自动清理。
 */
export function useRealtimeSession({
  profileId,
  personaId,
  autoConnect = false,
}: UseRealtimeSessionArgs): RealtimeSession {
  const [conn, setConn] = useState<ConnState>("disconnected");
  const [sessionState, setSessionState] = useState<string>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [llmDelta, setLlmDelta] = useState("");
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [micActive, setMicActive] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<DebugInfo>({
    framesShown: 0,
    audioChunks: 0,
    queueLen: 0,
    framesSent: 0,
  });
  const [timing, setTiming] = useState<SessionTiming>({
    transcriptTs: null,
    firstDeltaTs: null,
    firstPcmTs: null,
    firstFrameTs: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MicrophoneRecorder | null>(null);
  const playerRef = useRef<PcmPlayer | null>(null);
  const avmuxRef = useRef<AVMux | null>(null);
  const llmDeltaRef = useRef("");

  // 最新 profile/persona，避免 connect 闭包陈旧
  const profileRef = useRef(profileId);
  const personaRef = useRef(personaId);
  useEffect(() => {
    profileRef.current = profileId;
  }, [profileId]);
  useEffect(() => {
    personaRef.current = personaId;
  }, [personaId]);

  const handleFrame = useCallback((frame: AvatarFrame) => {
    const blob =
      frame.blob instanceof Blob ? frame.blob : new Blob([frame.blob], { type: "image/jpeg" });
    const url = URL.createObjectURL(blob);
    setFrameUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return url;
    });
    setDebugInfo((d) => ({ ...d, framesShown: d.framesShown + 1 }));
    setTiming((t) => (t.firstFrameTs == null ? { ...t, firstFrameTs: Date.now() } : t));
  }, []);

  /**
   * 摄像头截帧上行（0x02 + JPEG）。一次性取流：截完即停，不常驻摄像头。
   * 供"看看我"按钮与下行 vision.request 触发。
   */
  const captureAndSendFrame = useCallback(async () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    let track: MediaStreamTrack | null = null;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480 },
        audio: false,
      });
      track = stream.getVideoTracks()[0];
      const video = document.createElement("video");
      video.srcObject = stream;
      // 等首帧就绪（超时兜底 1.5s）
      await new Promise<void>((resolve) => {
        video.onloadedmetadata = () => resolve();
        setTimeout(resolve, 1500);
      });
      await video.play();
      await new Promise((r) => setTimeout(r, 100));
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      canvas.getContext("2d")?.drawImage(video, 0, 0);
      const jpegB64 = canvas.toDataURL("image/jpeg", 0.8).split(",")[1] ?? "";
      if (!jpegB64) return;
      const jpeg = Uint8Array.from(atob(jpegB64), (c) => c.charCodeAt(0));
      const frame = new Uint8Array(1 + jpeg.length);
      frame[0] = 0x02; // TAG_CAMERA_FRAME
      frame.set(jpeg, 1);
      ws.send(frame.buffer);
      setDebugInfo((d) => ({ ...d, framesSent: d.framesSent + 1 }));
    } catch (e) {
      setError(`摄像头不可用：${(e as Error).message}`);
    } finally {
      track?.stop();
    }
  }, []);

  const handleMessage = useCallback(
    (msg: { type: string; payload?: Record<string, unknown> }) => {
      switch (msg.type) {
        case "session.started":
          setSessionId((msg.payload?.session_id as string) || null);
          setSessionState((msg.payload?.state as string) || "idle");
          // 重置 timing 基准
          setTiming({
            transcriptTs: null,
            firstDeltaTs: null,
            firstPcmTs: null,
            firstFrameTs: null,
          });
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
          setTiming((t) => (t.transcriptTs == null ? { ...t, transcriptTs: Date.now() } : t));
          break;
        }
        case "llm.text.delta": {
          const t = (msg.payload?.text as string) || "";
          setLlmDelta((prev) => prev + t);
          setTiming((tm) =>
            tm.firstDeltaTs == null ? { ...tm, firstDeltaTs: Date.now() } : tm
          );
          break;
        }
        case "llm.text.done": {
          const full = (msg.payload?.full_text as string) || llmDeltaRef.current;
          if (full) {
            setTranscript((prev) => [
              ...prev,
              { role: "assistant", text: full, ts: Date.now() },
            ]);
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
        case "vision.request":
          // 后端触发词命中 → 自动截帧上行
          void captureAndSendFrame();
          break;
        case "vision.result": {
          const desc = (msg.payload?.description as string) || "";
          if (desc) {
            setTranscript((prev) => [
              ...prev,
              { role: "assistant", text: `【视觉】${desc}`, ts: Date.now() },
            ]);
          }
          break;
        }
        case "error":
          setError((msg.payload?.message as string) || "unknown error");
          break;
      }
    },
    [captureAndSendFrame]
  );

  const handleBinary = useCallback((data: ArrayBuffer) => {
    const view = new Uint8Array(data);
    if (view.length === 0) return;
    const tag = view[0];

    if (tag === 0x03) {
      const pcm = new Int16Array(data, 2);
      playerRef.current?.enqueue(pcm);
      setPlaying(true);
      setDebugInfo((d) => ({ ...d, audioChunks: d.audioChunks + 1 }));
      setTiming((t) => (t.firstPcmTs == null ? { ...t, firstPcmTs: Date.now() } : t));
    } else if (tag === 0x01) {
      const subtag = view[1] ?? 0;
      const jpeg = data.slice(2);
      avmuxRef.current?.pushFrame({
        blob: jpeg,
        tag: subtag === 0x01 ? "speech" : "idle",
      });
      setDebugInfo((d) => ({ ...d, queueLen: avmuxRef.current?.queueLength ?? 0 }));
    }
  }, []);

  const connect = useCallback(async () => {
    setConn("connecting");
    setError(null);

    playerRef.current = new PcmPlayer({ sampleRate: 16000, audioDelayMs: 600 });
    // 音频主时钟驱动视频（对齐 VoxEMW）：AVMux 从 PcmPlayer 读播放位置
    avmuxRef.current = new AVMux(
      {
        audioDelayMs: 600,
        fps: 25,
        getAudioTime: () => playerRef.current?.currentTime ?? 0,
      },
      handleFrame
    );
    void playerRef.current.resume();

    // WS 端口推导（优先级从高到低）：
    // 1. URL 参数 ?wsPort=xxxxx（显式指定）
    // 2. NEXT_PUBLIC_WS_PORT 环境变量（build 时注入）
    // 3. 隧道自动推导：页面端口 > 10000 时，WS 端口 = 页面端口 + 5101
    //    （隧道映射规律：studio 13000→3000，gateway 18101→8101，偏移 5101）
    // 4. 默认 8101（与 gateway 直连）
    const pagePort = window.location.port;
    const urlWsPort = new URLSearchParams(window.location.search).get("wsPort");
    const tunnelWsPort = parseInt(pagePort) > 10000 ? String(parseInt(pagePort) + 5101) : null;
    const wsPort = urlWsPort || process.env.NEXT_PUBLIC_WS_PORT || tunnelWsPort || "8101";
    const wsUrl = `ws://${window.location.hostname}:${wsPort}/ws/realtime`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setConn("connected");
      ws.send(
        JSON.stringify({
          type: "session.start",
          payload: {
            profile_id: profileRef.current,
            persona_id: personaRef.current,
          },
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
  }, [handleFrame, handleMessage, handleBinary]);

  const disconnect = useCallback(() => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setMicActive(false);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "session.stop" }));
      } catch {
        // 关闭中/连接已断——忽略
      }
    }
    ws?.close();
    wsRef.current = null;
    setConn("disconnected");
    playerRef.current?.close();
    playerRef.current = null;
    avmuxRef.current?.interrupt();
    avmuxRef.current = null;
  }, []);

  const toggleMic = useCallback(async () => {
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
  }, [micActive, conn]);

  const interrupt = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "audio.interrupt" }));
    playerRef.current?.interrupt();
    avmuxRef.current?.interrupt();
  }, []);

  // llmDelta 同步到 ref（llm.text.done 兜底用）
  useEffect(() => {
    llmDeltaRef.current = llmDelta;
  }, [llmDelta]);

  // 卸载清理
  useEffect(() => {
    return () => {
      recorderRef.current?.stop();
      playerRef.current?.close();
      wsRef.current?.close();
    };
  }, []);

  // autoConnect：挂载即连。仅触发一次，profile/persona 变化不自动重连（避免打断会话）。
  useEffect(() => {
    if (!autoConnect) return;
    if (!profileId) return;
    let cancelled = false;
    void (async () => {
      try {
        await connect();
      } catch {
        /* connect 内部已处理 error 状态 */
      }
    })();
    return () => {
      cancelled = true;
      void cancelled;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    conn,
    sessionState,
    sessionId,
    transcript,
    llmDelta,
    frameUrl,
    micActive,
    playing,
    error,
    debugInfo,
    timing,
    connect,
    disconnect,
    toggleMic,
    interrupt,
    captureAndSendFrame,
  };
}
