"""背压策略枚举。"""

from __future__ import annotations

from enum import StrEnum


class BackpressurePolicy(StrEnum):
    """队列满时的处理策略。"""

    BLOCK = "block"  # 阻塞生产者直到队列有空位（默认，保数据完整）
    DROP_OLDEST = "drop_oldest"  # 丢最旧（视频帧常用——保实时性）
    DROP_NEWEST = "drop_newest"  # 丢最新（避免堆积，旧数据优先）
