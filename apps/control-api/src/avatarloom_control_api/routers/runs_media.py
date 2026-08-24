"""Runs 目录媒体文件只读路由（mp4 回放等）。

avatar.video.ready 下发的 url 指到这里；Studio 代理路径
`/api/control/runs-media/<相对路径>` → 本路由。全局鉴权依赖（verify_token）
由 app 挂载时统一生效，媒体文件不额外公开。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()

# 允许的扩展名白名单——runs 目录里只暴露媒体产物，events.jsonl/metrics 等
# 运行数据不经此路由（含 transcript 等可能的隐私内容）
_ALLOWED_EXTS = frozenset({".mp4", ".webm", ".jpg", ".jpeg", ".png", ".wav"})


@router.get("/{rel_path:path}")
async def get_runs_media(rel_path: str, request: Request) -> FileResponse:
    # 复用 app.state.settings（app 启动时构造一次）——每次请求 load_settings()
    # 会重读 .env（磁盘 IO），高频媒体回放下是无谓开销，且测试注入不生效
    settings = request.app.state.settings
    runs_root = Path(settings.runs_root).resolve()  # noqa: ASYNC240 -- 只读路径解析
    target = (runs_root / rel_path).resolve()
    # 防穿越：resolve 后必须仍在 runs_root 内（../ 或绝对路径注入都挡掉）
    if not target.is_relative_to(runs_root):
        raise HTTPException(404, "Not found")
    if target.suffix.lower() not in _ALLOWED_EXTS:
        raise HTTPException(404, "Not found")
    if not target.is_file():
        raise HTTPException(404, "Not found")
    media_type = "video/mp4" if target.suffix == ".mp4" else None
    return FileResponse(target, media_type=media_type)
