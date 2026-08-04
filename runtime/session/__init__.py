"""Session Manager — 显式状态机驱动 + 会话生命周期。

职责：
- 持有当前状态，所有转换经 state_machine.transition() 校验
- 维护 session 内事件序号（单调递增）
- 暴露 on_state_change 回调（供 Recorder、Studio 订阅）
- 处理打断：进入 INTERRUPTING，触发清理，再退出到 LISTENING/IDLE
"""

from runtime.session.session import Session, SessionManager

__all__ = ["Session", "SessionManager"]
