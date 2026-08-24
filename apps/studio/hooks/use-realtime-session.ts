"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { MicrophoneRecorder } from "@/lib/audio/recorder";
import { PcmPlayer } from "@/lib/audio/player";
import { AVMux, type AvatarFrame } from "@/lib/audio/sync";
import { buildPcmUplinkFrame, buildCameraUplinkFrame } from "@/lib/frames";
import {
  sessionRuntimeReducer,
  summarizeEvent,
  INITIAL_RUNTIME,
  type RoundTiming,
  type SessionEvent,
} from "@/lib/events";

export type ConnState = "disconnected" | "connecting" | "connected" | "error";

/** 隧道端口显式映射（README「端口约定」唯一权威）：页面端口 → gateway WS 端口。 */
const TUNNEL_WS_PORT: Record<string, string> = { "27300": "27811" };

/**
 * 半双工防回授（默认开）：数字人播放期间暂停麦克风上行。外放时扬声器
 * 声音进麦克风会触发 VAD 误判（打断/垃圾转写）；戴耳机不受影响。
 * NEXT_PUBLIC_HALF_DUPLEX=0 恢复全双工（保留语音实时打断）。
 */
const HALF_DUPLEX = process.env.NEXT_PUBLIC_HALF_DUPLEX !== "0";

/**
 * 浏览器 WS 鉴权 token。只通过首条 auth 消息传递，不放进 URL。
 * 注意：NEXT_PUBLIC_* 会在构建期打入客户端 bundle——这是共享密钥模型，
 * 仅适用于受控单用户隧道；多用户部署应改为运行时注入（SSR / 独立 auth 接口）。
 */
const WS_AUTH_TOKEN = process.env.NEXT_PUBLIC_WS_TOKEN ?? "";

/** 推导 WS 地址（纯函数，挂载即算）：
 * 1. URL 参数 ?wsPort=xxxxx；2. NEXT_PUBLIC_WS_PORT env；
 * 3. 隧道映射（TUNNEL_WS_PORT 表，兜底 页面端口+5101）；4. 默认 27811。
 * https 页面自动 wss。仅在浏览器环境调用。 */
export function computeWsUrl(): string {
  const pagePort = window.location.port;
  const urlWsPort = new URLSearchParams(window.location.search).get("wsPort");
  const tunnelWsPort =
    TUNNEL_WS_PORT[pagePort] ??
    (parseInt(pagePort) > 10000 ? String(parseInt(pagePort) + 5101) : null);
  const wsPort = urlWsPort || process.env.NEXT_PUBLIC_WS_PORT || tunnelWsPort || "27811";
  const wsProto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${wsProto}://${window.location.hostname}:${wsPort}/ws/realtime`;
}

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
  /** vision = 视觉工具结果（独立样式，AL-P2-009）；缺省为普通对话。 */
  kind?: "message" | "vision";
}

/** 关键里程碑时间戳（相对本轮 t0 = transcript.completed）。类型沿用旧名以兼容渲染层。 */
export type SessionTiming = RoundTiming;

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
  /** 最近一段渲染完成 mp4 的回放入口（video.ready 后可重播；新一轮清空） */
  replay: { url: string; version: number } | null;
  debugInfo: DebugInfo;
  timing: SessionTiming;
  /** 实际连接的 WS 地址（推导完成后可知）——WelcomePane 显示用，避免静态文案误导。 */
  wsUrl: string | null;
  /** 下行 JSON 事件滚动记录（ring buffer 200 条）——调试面板事件流数据源。 */
  events: SessionEvent[];
  /** 最近一次 run.started 时刻（payload 不带 run_id，仅作展示锚点）。 */
  lastRunAt: number | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  toggleMic: () => Promise<void>;
  interrupt: () => void;
  captureAndSendFrame: () => Promise<void>;
  /** 当前麦克风音量（0-1）。供 UI 波形轮询，麦克风未开时返回 0。 */
  getMicLevel: () => number;
}

/**
 * 实时会话核心 hook——WebSocket 连接/断开/消息处理/二进制解析、PcmPlayer + AVMux +
 * MicrophoneRecorder 生命周期管理全部集中在此。渲染层（PlaygroundClient / ShowcaseClient）
 * 只消费返回值，不再直接持有 ws/audio ref。
 *
 * 状态分组（见 docs/11 §3）：conn/error 连接组 useState；sessionState/sessionId/timing/events
 * 会话运行时组 useReducer（lib/events.ts 纯函数，可单测）；transcript/frameUrl/debugInfo
 * 高频渲染组 useState。
 *
 * 音频是主时钟：PcmPlayer 用 AudioContext.currentTime 调度，AVMux 按节奏消费帧。
 * 二进制协议：上行 0x00+PCM16 / 0x02+JPEG；下行 0x03=PCM（offset 2 起 Int16），
 * 0x01=Avatar JPEG（subtag 在 byte[1]）。
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
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [llmDelta, setLlmDelta] = useState("");
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [micActive, setMicActive] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** 最近一段渲染完成 mp4 的回放 URL（avatar.video.ready 下发；新一轮开始清空） */
  const [replay, setReplay] = useState<{ url: string; version: number } | null>(null);
  const replayVersionRef = useRef(0);
  const [wsUrlState, setWsUrlState] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<DebugInfo>({
    framesShown: 0,
    audioChunks: 0,
    queueLen: 0,
    framesSent: 0,
  });
  // 热路径计数走 ref 累积 + 500ms 低频 flush——每帧/每音频 chunk 直接 setState
  // 会让 ControlBar（memo 也挡不住：debugInfo 是变化 prop）每秒重渲染 ~25 次
  const debugRef = useRef<DebugInfo>({
    framesShown: 0,
    audioChunks: 0,
    queueLen: 0,
    framesSent: 0,
  });
  const debugDirtyRef = useRef(false);
  const bumpDebug = useCallback((key: "framesShown" | "audioChunks" | "framesSent") => {
    debugRef.current = { ...debugRef.current, [key]: debugRef.current[key] + 1 };
    debugDirtyRef.current = true;
  }, []);
  const setDebugQueueLen = useCallback((v: number) => {
    debugRef.current = { ...debugRef.current, queueLen: v };
    debugDirtyRef.current = true;
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!debugDirtyRef.current) return;
      debugDirtyRef.current = false;
      setDebugInfo({ ...debugRef.current });
    }, 500);
    return () => window.clearInterval(timer);
  }, []);
  // 会话运行时：sessionState / sessionId / timing / events / lastRunAt（联动强，归 reducer）
  const [runtime, dispatch] = useReducer(sessionRuntimeReducer, INITIAL_RUNTIME);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MicrophoneRecorder | null>(null);
  const playerRef = useRef<PcmPlayer | null>(null);
  const avmuxRef = useRef<AVMux | null>(null);
  const llmDeltaRef = useRef("");
  // 断线重连：intentional 标记主动断开；connectRef 打破 onclose → connect 的自引用
  const reconnectRef = useRef({ attempts: 0, intentional: false, timer: 0 });
  const connectRef = useRef<(() => Promise<void>) | null>(null);
  // 心跳定时器（AL-P2-007）
  const pingTimerRef = useRef(0);
  // needVideoBase（VoxEMW 语义）：下一个音频 delta 是新 response 起点。
  // 初始 true（首回复必锚）；response.done / 打断后置位，首块 PCM 判定后清除。
  const needVideoBaseRef = useRef(true);

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
    bumpDebug("framesShown");
    // 首帧以"实际显示"时刻计（比到达时刻更接近用户感知）
    dispatch({ kind: "milestone", key: "firstFrameTs", ts: Date.now() });
  }, [bumpDebug]);

  /**
   * 摄像头截帧上行（0x02 + JPEG）。一次性取流：截完即停，不常驻摄像头。
   * 供"看看我"按钮与下行 vision.request 触发。
   * 截帧失败时上行 vision.frame_error——后端同轮 Vision 等待立即降级，不必等超时。
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
      // 等元数据（超时兜底 1.5s）
      await new Promise<void>((resolve) => {
        video.onloadedmetadata = () => resolve();
        setTimeout(resolve, 1500);
      });
      await video.play();
      // 等真实首帧渲染完成再截——play 后固定 sleep 100ms 在 Windows 上常不够，
      // 摄像头首帧未就绪时 drawImage 画出空帧，Vision 模型对空图产生幻觉描述
      // （"齿轮加载图标"类输出）。requestVideoFrameCallback 保证一帧已可抓。
      await new Promise<void>((resolve) => {
        const timeout = setTimeout(resolve, 2500);
        if (typeof video.requestVideoFrameCallback === "function") {
          video.requestVideoFrameCallback(() => {
            clearTimeout(timeout);
            resolve();
          });
        } else {
          const check = () => {
            if (video.readyState >= 2) {
              clearTimeout(timeout);
              resolve();
            } else {
              setTimeout(check, 50);
            }
          };
          check();
        }
      });
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      canvas.getContext("2d")?.drawImage(video, 0, 0);
      const jpegB64 = canvas.toDataURL("image/jpeg", 0.8).split(",")[1] ?? "";
      if (!jpegB64) return;
      const jpeg = Uint8Array.from(atob(jpegB64), (c) => c.charCodeAt(0));
      const frame = buildCameraUplinkFrame(jpeg);
      if (!frame) return;
      // 中间经授权弹窗 + 等真实首帧（可挂数秒），发送前复查连接——
      // 断线后 send 抛 InvalidStateError 会被误报成"摄像头不可用"
      if (ws !== wsRef.current || ws.readyState !== WebSocket.OPEN) return;
      ws.send(frame);
      bumpDebug("framesSent");
    } catch (e) {
      setError(`摄像头不可用：${(e as Error).message}`);
      // 通知后端截帧失败——同轮 Vision 等待立即降级，不必等超时
      try {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: "vision.frame_error",
              payload: { reason: String((e as Error).message || e) },
            })
          );
        }
      } catch {
        /* 发送失败忽略 */
      }
    } finally {
      track?.stop();
    }
  }, [bumpDebug]);

  const handleMessage = useCallback(
    (msg: { type: string; payload?: Record<string, unknown> }) => {
      const ts = Date.now();
      switch (msg.type) {
        case "session.started": {
          dispatch({
            kind: "sessionStarted",
            sessionId: (msg.payload?.session_id as string) || "",
            state: (msg.payload?.state as string) || "idle",
            ts,
          });
          // 降级可见：block 装配失败走 fallback（如 TTS OOM → tts.mock 440Hz 正弦波）
          // 前端明确提示，避免用户只听到"电流声"却不知原因
          const degraded = msg.payload?.degraded as Record<string, string> | undefined;
          if (degraded && Object.keys(degraded).length > 0) {
            const detail = Object.entries(degraded)
              .map(([cat, fb]) => `${cat} → ${fb}`)
              .join(", ");
            console.warn(`[AvatarLoom] block 降级: ${detail}`);
          }
          break;
        }
        case "session.state_changed": {
          const to = (msg.payload?.to as string) || "idle";
          dispatch({ kind: "stateChanged", to, ts });
          if (to === "interrupting") {
            // 打断（VoxEMW needVideoBase 置位）：下一音频 delta 走锚定判定；
            // PcmPlayer.interrupt 已把基准预重置到新时刻，连播分支会保持它
            needVideoBaseRef.current = true;
            playerRef.current?.interrupt();
            avmuxRef.current?.interrupt();
          }
          break;
        }
        case "transcript.completed": {
          const text = (msg.payload?.text as string) || "";
          // AL-P1-005：orchestrator 重发副本只记事件流，不重复渲染气泡、不重锚 t0
          const reEmitted = msg.payload?.re_emitted === true;
          const summary = summarizeEvent(msg.type, msg.payload) ?? "";
          dispatch({ kind: "event", type: msg.type, summary, ts, reEmitted });
          if (!reEmitted && text) {
            setTranscript((prev) => [...prev, { role: "user", text, ts }]);
            setLlmDelta("");
          }
          break;
        }
        case "llm.text.delta": {
          // 高频：不进事件流，只锁里程碑
          const t = (msg.payload?.text as string) || "";
          setLlmDelta((prev) => prev + t);
          dispatch({ kind: "milestone", key: "firstDeltaTs", ts });
          break;
        }
        case "llm.text.done": {
          const full = (msg.payload?.full_text as string) || llmDeltaRef.current;
          dispatch({
            kind: "event",
            type: msg.type,
            summary: summarizeEvent(msg.type, msg.payload) ?? "",
            ts,
          });
          if (full) {
            setTranscript((prev) => [
              ...prev,
              { role: "assistant", text: full, ts },
            ]);
          }
          setLlmDelta("");
          break;
        }
        case "tts.audio.delta":
          // 元数据——实际 PCM 在二进制消息里；高频不进事件流
          break;
        case "run.started":
        case "tts.audio.completed":
        case "persona.changed":
        case "response.done":
        case "vision.request": {
          const summary = summarizeEvent(msg.type, msg.payload) ?? "";
          dispatch({ kind: "event", type: msg.type, summary, ts });
          if (msg.type === "response.done") {
            // response 结束（VoxEMW needVideoBase 置位）：
            // 下一段 response 的首个 PCM 将走常规/连播锚定判定
            needVideoBaseRef.current = true;
            setPlaying(false);
          }
          if (msg.type === "vision.request") void captureAndSendFrame();
          if (msg.type === "run.started") {
            // 新一轮回复开始——上一段的回放入口让位给实时画面
            setReplay(null);
          }
          break;
        }
        case "avatar.video.ready": {
          // mp4 渲染完成（本轮 PCM 已播完，属事后产物）——登记回放入口
          dispatch({
            kind: "event",
            type: msg.type,
            summary: summarizeEvent(msg.type, msg.payload) ?? "",
            ts,
          });
          const url = msg.payload?.url as string | undefined;
          if (url) {
            replayVersionRef.current += 1;
            setReplay({ url, version: replayVersionRef.current });
          }
          break;
        }
        case "vision.result": {
          const desc = (msg.payload?.description as string) || "";
          dispatch({
            kind: "event",
            type: msg.type,
            summary: summarizeEvent(msg.type, msg.payload) ?? "",
            ts,
          });
          if (desc) {
            // 视觉工具结果：kind=vision 独立样式，不伪装成 persona 正式回复（AL-P2-009）
            setTranscript((prev) => [
              ...prev,
              { role: "assistant", text: desc, ts, kind: "vision" },
            ]);
          }
          break;
        }
        case "error": {
          const message = (msg.payload?.message as string) || "unknown error";
          dispatch({
            kind: "event",
            type: msg.type,
            summary: summarizeEvent(msg.type, msg.payload) ?? message,
            ts,
          });
          setError(message);
          break;
        }
        default: {
          // 未显式覆盖的事件（session.closed / response.started / 未来新增）：
          // 至少进调试事件流——summarizeEvent 对高频/心跳类返回 null 自动过滤
          const summary = summarizeEvent(msg.type, msg.payload);
          if (summary !== null) {
            dispatch({ kind: "event", type: msg.type, summary, ts });
          }
          break;
        }
      }
    },
    [captureAndSendFrame]
  );

  const handleBinary = useCallback((data: ArrayBuffer) => {
    const view = new Uint8Array(data);
    if (view.length === 0) return;
    const tag = view[0];

    if (tag === 0x03) {
      const pcmBytes = data.slice(1);
      if (pcmBytes.byteLength % 2 !== 0) return;
      const pcm = new Int16Array(pcmBytes);
      const player = playerRef.current;
      const avmux = avmuxRef.current;
      // needVideoBase 判定（VoxEMW assistant.js 移植语义）：
      // 本 delta 开启新 response——上段已播完则重锚清帧队（常规）；
      // 上段还在播（filler→正式回复连播）则绝不重锚，只裁上段尾帧。
      if (player && avmux && needVideoBaseRef.current) {
        needVideoBaseRef.current = false;
        const prevEnd = player.scheduledEnd;
        const now = player.absoluteNow;
        if (prevEnd - now < 0.3) {
          player.beginResponse();
          avmux.resetFrames();
        } else {
          avmux.trimTailFrames(prevEnd, player.responseBase);
        }
      }
      player?.enqueue(pcm);
      setPlaying(true);
      bumpDebug("audioChunks");
      dispatch({ kind: "milestone", key: "firstPcmTs", ts: Date.now() });
    } else if (tag === 0x01) {
      const subtag = view[1] ?? 0;
      const jpeg = data.slice(2);
      avmuxRef.current?.pushFrame({
        blob: jpeg,
        tag: subtag === 0x01 ? "speech" : "idle",
      });
      setDebugQueueLen(avmuxRef.current?.queueLength ?? 0);
    }
  }, [bumpDebug, setDebugQueueLen]);

  const connect = useCallback(async () => {
    setConn("connecting");
    setError(null);
    reconnectRef.current.intentional = false;

    // 重连前先清理旧资源——自动重连路径（onclose → connect）不经 disconnect，
    // 不清理会泄漏 AudioContext（Chrome ~6 个上限，泄漏几次就无声）
    playerRef.current?.close();
    avmuxRef.current?.interrupt();

    // 同步参数 URL 可调（对齐 VoxEMW ?adelay=/?vlag= 现场调优做法）：
    // /playground?adelay=450&vlag=-3 ——AutoDL 调音画同步不改代码直接试值
    const syncParams = new URLSearchParams(window.location.search);
    const adelayParam = parseInt(syncParams.get("adelay") ?? "", 10);
    const vlagParam = parseInt(syncParams.get("vlag") ?? "", 10);
    const audioDelayMs = Number.isFinite(adelayParam) ? adelayParam : 600;

    playerRef.current = new PcmPlayer({ sampleRate: 16000, audioDelayMs });
    // 音频主时钟驱动视频（对齐 VoxEMW）：AVMux 从 PcmPlayer 读播放位置
    avmuxRef.current = new AVMux(
      {
        audioDelayMs,
        fps: 25,
        videoLagFrames: Number.isFinite(vlagParam) ? vlagParam : 0,
        getAudioTime: () => playerRef.current?.currentTime ?? 0,
      },
      handleFrame
    );
    void playerRef.current.resume();

    // WS 地址推导（computeWsUrl 纯函数；挂载时已展示在 WelcomePane）
    const wsUrl = computeWsUrl();
    setWsUrlState(wsUrl);
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      if (wsRef.current !== ws) return; // stale socket——旧连接迟到事件，丢弃
      setConn("connected");
      reconnectRef.current.attempts = 0;
      if (WS_AUTH_TOKEN) {
        ws.send(JSON.stringify({ type: "auth", token: WS_AUTH_TOKEN }));
      }
      ws.send(
        JSON.stringify({
          type: "session.start",
          payload: {
            profile_id: profileRef.current,
            persona_id: personaRef.current,
          },
        })
      );
      // 心跳保活（AL-P2-007）：20s ping，防 gateway 90s idle 判定半开连接
      window.clearInterval(pingTimerRef.current);
      pingTimerRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 20000);
    };
    ws.onmessage = (ev) => {
      if (wsRef.current !== ws) return; // stale socket 防护
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
      if (wsRef.current !== ws) return; // stale socket 防护
      setConn("error");
      setError("WebSocket 连接失败——确认 Runtime Gateway 已启动（端口 27811）");
    };
    ws.onclose = (ev: CloseEvent) => {
      if (wsRef.current !== ws) return; // stale socket——旧连接的 close 不污染新会话
      window.clearInterval(pingTimerRef.current);
      setConn("disconnected");
      dispatch({ kind: "disconnected" });
      setMicActive(false);
      setPlaying(false); // 说话中途断线不清 → 重连后无播放但"打断"按钮残留
      // 1008（Policy Violation）：gateway token 开启而鉴权未通过——
      // 与"服务未启动"分开提示，避免排障方向跑偏
      if (ev.code === 1008) {
        setError(
          "鉴权失败——检查 NEXT_PUBLIC_WS_TOKEN 与服务端 AVATARLOOM_API_TOKEN 是否一致"
        );
        reconnectRef.current.intentional = true;
        return;
      }
      // 非主动断开（网络抖动/服务端掉线）→ 指数退避自动重连，最多 5 次。
      // 封顶 5s：rc=42 会话后自重启的拉起窗口通常 2-5s，3 次短退避可能全撞
      // 在空窗里导致彻底断开，需手动刷新。
      const r = reconnectRef.current;
      if (!r.intentional && r.attempts < 5) {
        const delay = [500, 1000, 2000, 4000, 5000][r.attempts];
        r.attempts += 1;
        r.timer = window.setTimeout(() => {
          void connectRef.current?.();
        }, delay);
      }
    };
  }, [handleFrame, handleMessage, handleBinary]);

  // connect 最新引用转发（onclose 重连用，打破 useCallback 自引用）
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const disconnect = useCallback(() => {
    // 主动断开：取消挂起的自动重连 + 停心跳
    reconnectRef.current.intentional = true;
    window.clearTimeout(reconnectRef.current.timer);
    window.clearInterval(pingTimerRef.current);
    recorderRef.current?.stop();
    recorderRef.current = null;
    setMicActive(false);
    setPlaying(false); // 同 onclose——主动断开也复位播放态
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
        onChunk: (pcm) => {
          const ws = wsRef.current;
          if (ws?.readyState !== WebSocket.OPEN) return;
          // 半双工防回授（默认开）：数字人播放期间暂停麦克风上行——外放时
          // 扬声器声音进麦克风会触发 VAD 误判（打断/垃圾转写）。戴耳机场景
          // 可设 NEXT_PUBLIC_HALF_DUPLEX=0 恢复全双工实时打断。
          if (HALF_DUPLEX && playerRef.current?.isPlaying) return;
          // 上行二进制协议：0x00 + PCM16（显式 tag，与摄像头 0x02 区分）
          const frame = buildPcmUplinkFrame(pcm);
          if (frame) ws.send(frame);
        },
        onError: (e) => setError(`麦克风错误：${e.message}`),
      });
      void playerRef.current?.resume();
      try {
        await recorderRef.current.start();
        setMicActive(true);
      } catch {
        // 授权被拒/设备不可用——recorder.start 已 rethrow，
        // 不 setMicActive(true)，清掉实例引用避免 stop 空转
        recorderRef.current = null;
      }
    }
  }, [micActive, conn]);

  const interrupt = useCallback(() => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "audio.interrupt" }));
    }
    playerRef.current?.interrupt();
    avmuxRef.current?.interrupt();
  }, []);

  const getMicLevel = useCallback(() => recorderRef.current?.getLevel() ?? 0, []);

  // llmDelta 同步到 ref（llm.text.done 兜底用）
  useEffect(() => {
    llmDeltaRef.current = llmDelta;
  }, [llmDelta]);

  // 卸载清理
  useEffect(() => {
    // reconnectRef 对象身份终身不变（只改属性），提升后 lint 不再误报；
    // 其余 ref 必须在 cleanup 时读最新 .current（卸载当然要关"当前"那个资源）。
    const reconnect = reconnectRef.current;
    return () => {
      window.clearTimeout(reconnect.timer);
      window.clearInterval(pingTimerRef.current);
      recorderRef.current?.stop();
      playerRef.current?.close();
      wsRef.current?.close();
    };
  }, []);

  // 挂载即推导 WS 地址（WelcomePane 未连接时也显示真实目标）
  useEffect(() => {
    setWsUrlState(computeWsUrl());
  }, []);

  // autoConnect：挂载即连。仅触发一次，profile/persona 变化不自动重连（避免打断会话）。
  useEffect(() => {
    if (!autoConnect) return;
    if (!profileId) return;
    void connect().catch(() => {
      /* connect 内部已处理 error 状态 */
    });
    // 无需卸载竞态保护——资源回收由上面的顶层卸载 cleanup effect 负责
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    conn,
    sessionState: runtime.sessionState,
    sessionId: runtime.sessionId,
    transcript,
    llmDelta,
    frameUrl,
    micActive,
    playing,
    error,
    replay,
    debugInfo,
    timing: runtime.timing,
    wsUrl: wsUrlState,
    events: runtime.events,
    lastRunAt: runtime.lastRunAt,
    connect,
    disconnect,
    toggleMic,
    interrupt,
    captureAndSendFrame,
    getMicLevel,
  };
}
