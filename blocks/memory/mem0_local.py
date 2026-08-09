"""Mem0 内嵌记忆 Block——移植自 VoxEMW `voxemw/memory.py`（MIT，出处保留）。

机制（与上游一致）：
- **召回**：session 开始时 `search(agent_id)`（user_id 固定、agent_id=persona 隔离），
  经 `build_memory_block` 格式化后一次性追加到 persona instructions——不进语音回合。
- **写入**：`response.done` 后 `add_turn`（Mem0 内部调 LLM 做事实抽取/去重），
  调用方一律 `asyncio.to_thread`——不占语音延迟。
- **降级**：`enabled=false` / 缺 API key / mem0 未安装 / 初始化失败 → `_store=None`
  静默跳过，对话链路零影响。

选型（沿用上游调研结论）：Mem0 Python SDK 内嵌模式——LLM 抽取走 OpenAI 兼容端点
（DeepSeek 等），embedding 走本地 bge-m3（DeepSeek 无 embedding API），
向量库用内嵌 Qdrant（文件落盘）。无需新服务/数据库进程。

安装：`uv sync --extra memory`（mem0ai + qdrant-client；bge-m3 模型首次启用时下载，
AutoDL 建议预置到数据盘并设 HF_HOME）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from avatarloom_sdk import (
    Block,
    BlockContext,
    BlockManifest,
    Capability,
    ResourceRequirements,
)

logger = logging.getLogger(__name__)

MAX_MEMORY_CHARS = 80  # 单条注入截断（防人设正文被稀释）


def build_memory_block(memories: list[str]) -> str:
    """记忆条目 → 注入 instructions 的文本块（纯函数，便于单测）。空列表返回 ""。"""
    if not memories:
        return ""
    lines = [f"- {m[:MAX_MEMORY_CHARS]}" for m in memories]
    return "# 关于用户的记忆（历史对话提取，自然引用，不要逐条复述）\n" + "\n".join(lines)


class MemoryStore:
    """Mem0 懒加载封装。所有方法同步阻塞，调用方用 asyncio.to_thread。"""

    def __init__(self, cfg: dict[str, Any], llm_cfg: dict[str, Any], api_key: str):
        from mem0 import Memory  # 依赖重，仅启用时加载

        store_dir = Path(cfg.get("storeDir", "data/memory"))
        store_dir.mkdir(parents=True, exist_ok=True)
        self.user_id = cfg.get("userId", "default_user")
        self.top_k = int(cfg.get("topK", 5))
        self._m = Memory.from_config(
            {
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": llm_cfg.get("model", "deepseek-v4-flash"),
                        "openai_base_url": llm_cfg.get(
                            "baseUrl", "https://api.deepseek.com/v1"
                        ),
                        "api_key": api_key,
                        "temperature": 0.0,
                    },
                },
                "embedder": {
                    "provider": "huggingface",
                    "config": {"model": cfg.get("embedderModel", "BAAI/bge-m3")},
                },
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": "avatarloom_memory",
                        "path": str(store_dir),
                        "embedding_model_dims": 1024,  # bge-m3
                    },
                },
            }
        )

    def search(self, agent_id: str) -> list[str]:
        """召回该 persona 的记忆条目（user_id 固定单用户，agent_id=persona 隔离）。"""
        results = self._m.search(
            "用户的重要事实、偏好、约定与近期事件",
            top_k=self.top_k,
            filters={"user_id": self.user_id, "agent_id": agent_id},
        )
        return [r["memory"] for r in (results.get("results") or []) if r.get("memory")]

    def add_turn(self, user_text: str, assistant_text: str, agent_id: str) -> None:
        """一轮对话 → Mem0 抽取/去重/更新（内部调 LLM，阻塞）。"""
        messages = []
        if user_text:
            messages.append({"role": "user", "content": user_text})
        if assistant_text:
            messages.append({"role": "assistant", "content": assistant_text})
        if messages:
            self._m.add(messages, user_id=self.user_id, agent_id=agent_id)


class Mem0MemoryBlock(Block):
    """Mem0 内嵌记忆 Block。orchestrator 鸭子调用 recall/memorize（同 vision 模式）。"""

    _store: MemoryStore | None = None

    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="memory.mem0-local",
            name="Mem0 Embedded Memory",
            category="memory",
            runtime_type="python_inproc",
            capabilities=Capability(),
            inputs=[],
            outputs=[],
            resources=ResourceRequirements(pip_extras=["memory"]),
            config_schema={
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean", "default": False},
                    "apiKeyEnv": {"type": "string", "default": "DEEPSEEK_API_KEY"},
                    "model": {"type": "string", "default": "deepseek-v4-flash"},
                    "baseUrl": {"type": "string", "default": "https://api.deepseek.com/v1"},
                    "embedderModel": {"type": "string", "default": "BAAI/bge-m3"},
                    "storeDir": {"type": "string", "default": "data/memory"},
                    "topK": {"type": "integer", "default": 5},
                    "userId": {"type": "string", "default": "default_user"},
                },
            },
            install_extras=["memory"],
        )

    async def setup(self, ctx: BlockContext) -> None:
        cfg = ctx.config
        self._store = None
        if not bool(cfg.get("enabled", False)):
            self._mark_ready()
            await ctx.logger.ainfo("memory.mem0-local disabled（静默跳过）")
            return
        api_key = os.environ.get(str(cfg.get("apiKeyEnv") or "DEEPSEEK_API_KEY"), "")
        if not api_key:
            self._mark_ready()
            await ctx.logger.awarning("memory 启用但缺 API key，降级关闭")
            return
        try:
            # MemoryStore.__init__ 是同步重操作（qdrant 初始化 + bge-m3 加载，
            # 首次还要下载 ~2GB 模型）——必须 offload 线程，否则阻塞事件循环。
            self._store = await asyncio.to_thread(
                MemoryStore,
                cfg,
                {"model": cfg.get("model"), "baseUrl": cfg.get("baseUrl")},
                api_key,
            )
        except ImportError as e:
            await ctx.logger.awarning(
                "mem0 未安装，降级关闭——运行 `uv sync --extra memory`", error=str(e)
            )
        except Exception as e:
            await ctx.logger.awarning("memory 初始化失败，降级关闭", error=str(e))
        self._mark_ready()
        await ctx.logger.ainfo(
            "memory.mem0-local ready", active=self._store is not None
        )

    @property
    def active(self) -> bool:
        return self._store is not None

    async def shutdown(self) -> None:
        """释放 qdrant client + embedder 模型。

        qdrant local 模式对 storeDir 持有文件锁，不释放会导致同进程重 setup
        （fallback 重建）撞锁。clear 引用让 GC 回收 embedder 模型。
        """
        store = self._store
        self._store = None
        if store is None:
            return
        # qdrant client 的 close 是同步阻塞调用——offload 线程
        def _close() -> None:
            try:
                client = getattr(store._m, "vector_store", None)
                if client is not None:
                    close = getattr(client, "close", None)
                    if callable(close):
                        close()
            except Exception:
                logger.debug("mem0 vector_store close 失败（忽略）", exc_info=True)

        await asyncio.to_thread(_close)

    async def process(self, ctx: BlockContext, event) -> None:
        """不订阅任何事件——recall/memorize 由 orchestrator 鸭子调用（同 vision 模式）。"""
        return

    async def recall(self, agent_id: str) -> str:
        """召回该 persona 的记忆并格式化为 instructions 块。未启用返回 ""。"""
        if self._store is None:
            return ""
        try:
            memories = await asyncio.to_thread(self._store.search, agent_id)
            return build_memory_block(memories)
        except Exception as e:
            logger.warning("memory recall 失败（按无记忆继续）: %s", e)
            return ""

    async def memorize(self, user_text: str, assistant_text: str, agent_id: str) -> None:
        """写入一轮对话（异步抽取，不占语音延迟）。未启用 no-op。"""
        if self._store is None:
            return
        try:
            await asyncio.to_thread(
                self._store.add_turn, user_text, assistant_text, agent_id
            )
        except Exception as e:
            logger.warning("memory memorize 失败（静默跳过）: %s", e)
