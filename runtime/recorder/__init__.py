"""AvatarLoom Run Recorder。

每轮对话（Run）生成一个目录，记录：
- manifest.json：Run 元数据
- events.jsonl：所有事件（逐行 JSON）
- metrics.json：性能指标（首字/首音/首帧延迟、中断次数等）
- transcript.json：对话转写
- runtime-config.json：运行时配置快照
- input/：用户输入产物（可选）
- output/：助手输出产物（音频/视频/文本）
- snapshots/：状态快照

参考 docs/03-Studio部署安全与验收.md 的 Run Recorder 目录结构。
"""

from runtime.recorder.artifacts import ArtifactWriter
from runtime.recorder.recorder import RunMetrics, RunRecorder

__all__ = ["RunRecorder", "RunMetrics", "ArtifactWriter"]
