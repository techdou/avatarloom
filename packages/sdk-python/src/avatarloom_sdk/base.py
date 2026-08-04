"""Block 基类、Context、Manifest、健康检查协议。

设计遵循 docs/01-架构与模块规范.md 的生命周期：

    class Block:
        async def setup(self, context, config): ...
        async def warmup(self): ...
        async def process(self, event): ...
        async def reset(self, session_id): ...
        async def health(self): ...
        async def shutdown(self): ...

核心约束（docs/01 第 7 节）：
1. Adapter 负责模型差异。
2. Runtime 只依赖能力和事件协议。
3. Block 必须可独立测试。
4. Block 必须支持超时和取消。
5. Block 必须报告健康状态。
6. 重型依赖使用 Optional Extra 或独立环境。
7. 浏览器不能绕过 Runtime Gateway 直连模型。
"""

from __future__ import annotations

import abc
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

import structlog
from avatarloom_protocol import Event
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.get_logger(__name__)


# Block 运行时类型（python_inproc / 独立进程 / 远程服务 / mock）
BlockRuntimeType = Literal[
    "python_inproc",  # 同进程
    "python_process",  # 独立 Python 进程
    "http_remote",  # 远程 HTTP 服务
    "websocket_remote",  # 远程 WebSocket 服务
    "grpc_remote",  # 远程 gRPC 服务
    "mock",  # 纯 Mock，无实际能力
]


# ---------------------------------------------------------------------------
# Block Manifest
# ---------------------------------------------------------------------------


class BlockCategory(StrEnum):
    """Block 分类。Runtime 用此决定在链路中的位置。"""

    VAD = "vad"
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    AVATAR = "avatar"
    VISION = "vision"
    PERSONA = "persona"
    MEMORY = "memory"
    SKILLS = "skills"
    TRANSPORT = "transport"


class Capability(BaseModel):
    """Block 能力声明。Runtime 用此决定如何调度。"""

    model_config = ConfigDict(extra="forbid")

    streaming: bool = Field(default=False, description="支持流式输入输出")
    voice_cloning: bool = Field(default=False, description="支持音色克隆")
    interruption: bool = Field(default=False, description="支持用户打断")
    languages: list[str] = Field(default_factory=lambda: ["zh", "en"])
    # 可选能力：Runtime 不强制要求
    optional: bool = Field(default=False, description="此 Block 可缺席，失败时降级")


class ResourceRequirements(BaseModel):
    """Block 资源要求。用于 Profile 校验和部署调度。"""

    model_config = ConfigDict(extra="forbid")

    accelerator: list[str] = Field(
        default_factory=list,
        description="需要的加速器，如 ['cuda', 'mlx']；空表示纯 CPU",
    )
    estimated_vram_mb: int = Field(default=0, ge=0, description="估计显存占用")
    estimated_ram_mb: int = Field(default=0, ge=0, description="估计内存占用")
    # 重型依赖 pip extras，供 doctor 检查
    pip_extras: list[str] = Field(
        default_factory=list,
        description="需要的 pip extras，如 ['sensevoice']",
    )


class BlockManifest(BaseModel):
    """Block 声明。每个 Block 类必须通过 manifest() 提供。

    对应 templates/block.yaml 的结构。
    """

    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(description="全局唯一 Block ID，如 'vad.silero'")
    name: str = Field(description="人类可读名称")
    version: str = Field(default="0.1.0")
    category: str = Field(description="Block 分类，见 BlockCategory")
    # 运行时类型
    runtime_type: BlockRuntimeType = "python_inproc"
    # 入口（python_inproc 模式）
    entrypoint: str | None = Field(
        default=None,
        description="python_inproc 模式：'module:ClassName'",
    )
    # 能力
    capabilities: Capability = Field(default_factory=Capability)
    # 资源要求
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    # 事件 I/O
    inputs: list[str] = Field(
        default_factory=list,
        description="订阅的事件类型列表",
    )
    outputs: list[str] = Field(
        default_factory=list,
        description="产出的事件类型列表",
    )
    # 健康检查
    healthcheck_timeout_ms: int = Field(default=3000, ge=100)
    # 配置 schema（JSON Schema dict）
    config_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object"},
        description="JSON Schema 描述 Block config 字段",
    )
    # 安装 Extra
    install_extras: list[str] = Field(
        default_factory=list,
        description="安装本 Block 需要的 pip extras",
    )


# ---------------------------------------------------------------------------
# Health Status
# ---------------------------------------------------------------------------


class HealthStatus(BaseModel):
    """Block 健康状态。"""

    model_config = ConfigDict(extra="allow")

    block_id: str
    status: Literal["healthy", "degraded", "unhealthy", "not_ready"] = "healthy"
    latency_ms: int | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Block Context
# ---------------------------------------------------------------------------


@dataclass
class BlockContext:
    """Block 运行时上下文。

    由 Runtime Orchestrator 创建，传给每个 Block 的 setup() 和 process()。
    Block 通过 ctx.emit() 发布事件、通过 ctx.logger 记录日志、
    通过 ctx.config 读取自身配置。
    """

    session_id: str
    run_id: str | None
    workspace_root: str
    # 配置（已校验）
    config: dict[str, Any] = field(default_factory=dict)
    # Persona 上下文
    persona_id: str | None = None
    persona_instructions: str | None = None
    persona_voice_ref: str | None = None
    persona_avatar_ref: str | None = None
    # 事件发射器：Runtime 注入
    _emit_fn: Callable[[Event], Awaitable[None]] | None = field(default=None, repr=False)
    # 结构化日志
    _logger: Any = field(default=None, repr=False)

    @property
    def logger(self) -> Any:
        if self._logger is None:
            self._logger = structlog.get_logger(
                "avatarloom.block",
                session_id=self.session_id,
                run_id=self.run_id,
            )
        return self._logger

    async def emit(self, event: Event) -> None:
        """发布事件到事件总线。"""
        if self._emit_fn is None:
            raise RuntimeError("BlockContext.emit called before Runtime wired _emit_fn")
        await self._emit_fn(event)

    def bind_logger(self, **kwargs: Any) -> None:
        """给 logger 绑定额外的上下文字段。"""
        self._logger = self.logger.bind(**kwargs)


# ---------------------------------------------------------------------------
# Block 异常
# ---------------------------------------------------------------------------


class BlockError(Exception):
    """Block 通用错误。"""

    def __init__(
        self,
        block_id: str,
        message: str,
        *,
        degraded: bool = False,
        fallback_block_id: str | None = None,
    ) -> None:
        self.block_id = block_id
        self.degraded = degraded
        self.fallback_block_id = fallback_block_id
        super().__init__(f"[{block_id}] {message}")


class BlockSetupError(BlockError):
    """Block setup 阶段失败。"""


class BlockNotReadyError(BlockError):
    """Block 未就绪时被调用 process()。"""


class BlockCancelledError(BlockError):
    """Block 被 Runtime 取消（用户打断或会话关闭）。"""


# ---------------------------------------------------------------------------
# Block 基类
# ---------------------------------------------------------------------------


class Block(abc.ABC):
    """单请求生命周期 Block。

    子类必须实现：setup, process。
    可选实现：warmup, reset, health, shutdown。

    约定：
    - process() 必须支持 asyncio 取消（CancelledError 透传，不吞）。
    - setup() 失败 raise BlockSetupError。
    - 任何失败想触发降级的，raise BlockError(degraded=True)。
    """

    def __init__(self) -> None:
        self._ready: bool = False
        self._setup_time_ms: int = 0

    @classmethod
    @abc.abstractmethod
    def manifest(cls) -> BlockManifest:
        """返回本 Block 的声明。"""

    @abc.abstractmethod
    async def setup(self, ctx: BlockContext) -> None:
        """初始化 Block（加载模型、建立连接等）。

        失败时 raise BlockSetupError。
        成功后 _ready 被置为 True。
        """

    async def warmup(self) -> None:
        """预热（首次推理前调用，可选实现）。

        典型用途：torch.compile、首次 forward、建立连接池。
        默认空实现。
        """

    @abc.abstractmethod
    async def process(self, ctx: BlockContext, event: Event) -> None:
        """处理一个事件，可能 emit 新事件。

        必须支持 asyncio 取消。
        若 Block 未 ready，raise BlockNotReadyError。
        """

    async def reset(self, session_id: str) -> None:
        """重置 Block 到会话初始态（用户打断、新会话开始时）。

        默认空实现。
        """

    async def health(self) -> HealthStatus:
        """健康检查。默认返回 healthy。"""
        return HealthStatus(
            block_id=self.manifest().block_id,
            status="healthy" if self._ready else "not_ready",
        )

    async def shutdown(self) -> None:
        """释放资源。默认空实现。"""

    # ---- 内部状态 ----

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _mark_ready(self) -> None:
        self._ready = True


# ---------------------------------------------------------------------------
# StreamingBlock 基类
# ---------------------------------------------------------------------------


class StreamingBlock(Block):
    """流式 Block（LLM/TTS/Avatar）。

    生命周期：
        open_stream(session) -> 接受多个 push(chunk) -> flush() -> close_stream()

    用 anyio.CancelScope 支持打断/取消。
    """

    @abc.abstractmethod
    async def open_stream(self, ctx: BlockContext) -> None:
        """开始一个流式会话。"""

    @abc.abstractmethod
    async def push(self, ctx: BlockContext, chunk: Any) -> None:
        """推入一个 chunk（文本 delta / PCM chunk / 控制消息）。"""

    async def flush(self) -> None:
        """刷出未完成的输出。默认空实现。"""

    async def close_stream(self) -> None:
        """关闭流，释放本次会话资源。默认空实现。"""


# ---------------------------------------------------------------------------
# Block 工厂
# ---------------------------------------------------------------------------


@runtime_checkable
class BlockClass(Protocol):
    """Block 类的协议（用于类型提示工厂函数）。"""

    def manifest(cls) -> BlockManifest: ...
    def __call__(self) -> Block: ...


def create_block(entrypoint: str) -> Block:
    """从 entrypoint 字符串（'module:ClassName'）实例化 Block。

    供 Runtime 从 YAML 配置加载 Block 用。
    """
    import importlib

    if ":" not in entrypoint:
        raise ValueError(f"Invalid entrypoint {entrypoint!r}, expected 'module:ClassName'")
    module_name, class_name = entrypoint.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise BlockSetupError(
            block_id=entrypoint,
            message=f"Failed to import module {module_name!r}: {e}. "
            f"可能没安装对应 extras。检查 `pip install avatarloom[<extra>]` "
            f"或 `uv sync --extra <extra>`",
        ) from e
    if not hasattr(module, class_name):
        raise BlockSetupError(
            block_id=entrypoint,
            message=f"Module {module_name!r} has no attribute {class_name!r}",
        )
    block_cls = getattr(module, class_name)
    if not (isinstance(block_cls, type) and issubclass(block_cls, Block)):
        raise BlockSetupError(
            block_id=entrypoint,
            message=f"{entrypoint!r} is not a Block subclass",
        )
    return block_cls()


# ---------------------------------------------------------------------------
# 计时工具
# ---------------------------------------------------------------------------


class Timer:
    """简单计时器，用于性能指标采集。"""

    def __init__(self) -> None:
        self._start: float | None = None

    def start(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> int:
        if self._start is None:
            return 0
        return int((time.perf_counter() - self._start) * 1000)

    def reset(self) -> None:
        self._start = None


def now_ms() -> int:
    """当前毫秒时间戳。"""
    return int(time.time() * 1000)


__all__ = [
    "Block",
    "BlockCancelledError",
    "BlockCategory",
    "BlockContext",
    "BlockError",
    "BlockManifest",
    "BlockNotReadyError",
    "BlockSetupError",
    "Capability",
    "HealthStatus",
    "ResourceRequirements",
    "StreamingBlock",
    "Timer",
    "create_block",
    "now_ms",
]
