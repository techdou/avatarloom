"""AvatarLoom Control API 启动入口。

用法：
    uv run python -m avatarloom_control_api
    或
    uv run uvicorn avatarloom_control_api.app:create_app --factory --port 27810
"""

from __future__ import annotations

import uvicorn

from avatarloom_control_api.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "avatarloom_control_api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
