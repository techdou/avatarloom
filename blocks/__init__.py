"""blocks package."""

from __future__ import annotations

from typing import Any


def release_gpu_objects(objects: list[Any]) -> None:
    """在线程中清掉最后一批模型引用，再回收 Python/CUDA 缓存。

    调用方须先把实例字段置空，再把旧引用装进可变 list 传入。函数先
    ``clear()``，保证执行 ``gc.collect()`` 时参数本身不再持有模型。
    torch 未安装的 mock/单测环境会安全跳过 CUDA 清理。
    """
    import gc

    objects.clear()
    gc.collect()
    try:
        import torch
    except ImportError:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


__all__ = ["release_gpu_objects"]
