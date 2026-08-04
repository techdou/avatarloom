import { PlaygroundClient } from "@/components/audio/playground-client";

export default function PlaygroundPage() {
  return (
    <div>
      <h1 className="mb-1">Realtime Playground</h1>
      <p className="text-sm text-fg-muted mb-6">
        连接 Runtime Gateway，实时语音对话。音频是音画同步主时钟。
      </p>
      <PlaygroundClient />
    </div>
  );
}
