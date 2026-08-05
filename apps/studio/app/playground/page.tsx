import { PlaygroundClient } from "@/components/audio/playground-client";

export default function PlaygroundPage() {
  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">实时对话</h1>
          <p className="page-desc">连接 Runtime Gateway 实时语音对话。音频是音画同步主时钟。</p>
        </div>
      </div>
      <PlaygroundClient />
    </div>
  );
}
