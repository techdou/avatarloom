"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  useRealtimeSession,
} from "@/hooks/use-realtime-session";
import { gatewayFetch, type GatewayProfilesResponse, type Persona } from "@/lib/api";
import { ContextBar } from "@/components/playground/context-bar";
import { AvatarStage } from "@/components/playground/avatar-stage";
import { TranscriptPane } from "@/components/playground/transcript-pane";
import { ControlBar } from "@/components/playground/control-bar";
import { DebugDrawer } from "@/components/playground/debug-drawer";

/**
 * Realtime Playground —— 可对话的调试器（orchestration 层）。
 *
 * 职责：profile/persona 选择与持久化、拉取下拉选项、装配四个展示组件。
 * 数据流（WS / PCM / AVMux / MicrophoneRecorder）全部在 useRealtimeSession hook 内；
 * 视觉细节在 avatar-stage / transcript-pane / control-bar / debug-drawer 四个纯展示组件。
 *
 * 音频是主时钟：PcmPlayer 用 AudioContext.currentTime 调度，AVMux 按节奏消费帧。
 */
export function PlaygroundClient() {
  // profile / persona：客户端持久化（默认 autodl-best 真实 GPU 链路；
  // 本地无 GPU 开发可手动切 mock）
  const [profileId, setProfileId] = useState<string>("autodl-best");
  const [personaId, setPersonaId] = useState<string>("demo-assistant");
  const [showDebug, setShowDebug] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);

  // 下拉选项（orchestration 层统一拉取，ContextBar 纯渲染）：
  // profiles 来自 gateway（yaml——运行时真实装配来源）；personas 来自 control-api DB
  const [profiles, setProfiles] = useState<GatewayProfilesResponse>({ profiles: [], default: "mock" });
  const [personas, setPersonas] = useState<Persona[]>([]);

  useEffect(() => {
    try {
      const p = localStorage.getItem("al.profile");
      const pe = localStorage.getItem("al.persona");
      if (p) setProfileId(p);
      if (pe) setPersonaId(pe);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    let alive = true;
    gatewayFetch<GatewayProfilesResponse>("/profiles")
      .then((data) => {
        if (alive && Array.isArray(data?.profiles)) setProfiles(data);
      })
      .catch(() => {});
    fetch("/api/control/personas")
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Persona[]) => {
        if (alive && Array.isArray(list)) setPersonas(list);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const session = useRealtimeSession({ profileId, personaId });
  // restartSession 的定时器句柄——卸载时清理，避免组件销毁后 connect() 还在 fire
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const restartSession = useCallback(() => {
    // 已连接时切换 profile/persona：重启会话让新配置生效
    session.disconnect();
    if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
    restartTimerRef.current = setTimeout(() => session.connect(), 100);
  }, [session]);

  // 卸载清理：清掉 pending 的 restart 定时器
  useEffect(() => {
    return () => {
      if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
    };
  }, []);

  const handleProfileChange = useCallback(
    (id: string) => {
      setProfileId(id);
      try {
        localStorage.setItem("al.profile", id);
      } catch {
        /* ignore */
      }
      if (session.conn === "connected") restartSession();
    },
    [restartSession, session.conn]
  );

  const handlePersonaChange = useCallback(
    (id: string) => {
      setPersonaId(id);
      try {
        localStorage.setItem("al.persona", id);
      } catch {
        /* ignore */
      }
      if (session.conn === "connected") restartSession();
    },
    [restartSession, session.conn]
  );

  // 打开运行记录侧滑——useCallback 稳定引用，避免 TranscriptPane.memo 失效
  const handleOpenRuns = useCallback(() => setRunsOpen(true), []);

  // 助手说话人标签：persona label > name > id 兜底
  const currentPersona = personas.find((p) => p.id === personaId);
  const personaLabel = currentPersona?.label || currentPersona?.name || personaId;

  // 空格键切换麦克风（输入控件 focus 时豁免；长按不重复触发）
  const { conn: sessionConn, toggleMic } = session;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat) return;
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (sessionConn !== "connected") return;
      e.preventDefault();
      void toggleMic();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sessionConn, toggleMic]);

  return (
    <div className="flex flex-col gap-2 h-[calc(100vh-3.5rem)] md:h-[calc(100vh-0px)] md:p-2">
      {/* 顶部上下文条（连接 / profile / persona / 调试 / 主题） */}
      <ContextBar
        conn={session.conn}
        profileId={profileId}
        personaId={personaId}
        profiles={profiles.profiles}
        personas={personas}
        onProfileChange={handleProfileChange}
        onPersonaChange={handlePersonaChange}
        onConnect={session.connect}
        onDisconnect={session.disconnect}
        onCaptureFrame={session.captureAndSendFrame}
        showDebug={showDebug}
        onToggleDebug={setShowDebug}
      />

      {/* 主区：角色（左/上） + 对话（右/下） */}
      <div className="grid grid-cols-1 grid-rows-[50vh_1fr] md:grid-rows-none md:grid-cols-[minmax(360px,420px)_1fr] gap-2 flex-1 min-h-0">
        <AvatarStage
          frameUrl={session.frameUrl}
          conn={session.conn}
          error={session.error}
          onConnect={session.connect}
          showDebug={showDebug}
          sessionState={session.sessionState}
          framesShown={session.debugInfo.framesShown}
          personaLabel={personaLabel}
          wsUrl={session.wsUrl}
        />

        {/* 对话面板 + 底部控制条 */}
        <div className="card flex flex-col p-0 min-h-0">
          <TranscriptPane
            transcript={session.transcript}
            llmDelta={session.llmDelta}
            error={session.error}
            conn={session.conn}
            sessionState={session.sessionState}
            sessionId={session.sessionId}
            assistantLabel={personaLabel}
            onOpenRuns={handleOpenRuns}
          />
          <ControlBar
            conn={session.conn}
            micActive={session.micActive}
            playing={session.playing}
            onToggleMic={session.toggleMic}
            onInterrupt={session.interrupt}
            showDebug={showDebug}
            debugInfo={session.debugInfo}
            getMicLevel={session.getMicLevel}
          />
        </div>
      </div>

      {/* 运行记录侧滑（动态导入避免首屏负担） */}
      {runsOpen && <RunsOverlayDeferred onClose={() => setRunsOpen(false)} />}

      {/* 调试抽屉（开关在 ContextBar） */}
      {showDebug && (
        <DebugDrawer
          conn={session.conn}
          sessionState={session.sessionState}
          sessionId={session.sessionId}
          debugInfo={session.debugInfo}
          timing={session.timing}
          events={session.events}
        />
      )}
    </div>
  );
}

/** 运行记录侧滑——延迟加载 RunsPanel，避免打断首屏。 */
function RunsOverlayDeferred({ onClose }: { onClose: () => void }) {
  const [Node, setNode] = useState<React.ReactNode>(null);
  useEffect(() => {
    let alive = true;
    import("@/components/playground/runs-panel")
      .then((m) => {
        if (alive) setNode(<m.RunsPanel onClose={onClose} />);
      })
      .catch(() => {
        if (alive) setNode(null);
      });
    return () => {
      alive = false;
    };
  }, [onClose]);
  return Node;
}
