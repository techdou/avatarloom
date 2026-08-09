# 全量 Review 修复记录（2026-08-09）

> 本轮 review 分两阶段修复：**16 HIGH**（批次 1-5）+ **~35 MEDIUM/LOW**（批次 6-10）。
> 全量门禁全绿：ruff ✓ / mypy 75 文件 ✓ / pytest 329 passed / vitest 31 passed / tsc ✓。
> 历史交接文档 `docs/archive/10-*` 的 AL 编号体系在此逐一回填状态。

---

## 一、修复总览

| 批次 | 范围 | HIGH | MEDIUM/LOW | Commit |
|---|---|---|---|---|
| 1 | 崩溃路径 | 3（silero cuda / os._exit / mem0 阻塞） | 1（mem0 shutdown） | `d8c8735` |
| 2 | 打断链路端到端 | 4（状态机 / recorder / ollama / musetalk） | 4（mock 打断 / 空流重试 / delegate / 测试） | `26a0f58` |
| 3 | 数据串扰 | 3（stt 类属性 / persona refText / EventBus 死锁） | 1（fallback config） | `0065702` |
| 4 | 前端泄漏+竞态 | 5（AudioContext / stale socket / 麦克风×2 / SDK 类型） | 2（restartSession / interrupt） | `5a1fa45` |
| 5 | 安全部署 | 1（Studio 0.0.0.0） | ~10（compose / Dockerfile / alembic / 上传 / 外键 / 鉴权告警 / WS 上限 / warmup / 假绿） | `ec790d9` |
| 6 | runtime MEDIUM | — | 13（详见下表） | `fc52e33` |
| 7 | blocks MEDIUM | — | 9（详见下表） | `fc52e33` |
| 8-10 | apps/studio/scripts | — | ~12（分页 / showcase / memo / scripts LOW） | `fc52e33` |
| 修正 | recorder 回退 | — | 1（自审发现并发写交错） | `65136d5` |

---

## 二、AL 问题编号状态回填

对照 `docs/archive/10-*` 的 AL 编号体系，逐条标注当前状态。

### AL-P0 系列（全部 ✅ 已修复）

| 编号 | 问题 | 状态 | 修复 commit |
|---|---|---|---|
| AL-P0-001 | Studio JSX 语法错误 | ✅ | `c08feab`（历史） |
| AL-P0-002 | captureAndSendFrame 初始化顺序 | ✅ | `c08feab` |
| AL-P0-003 | RealtimeSession 接口缺少公开方法 | ✅ | `c08feab` |
| AL-P0-004 | 协议包漏导出 VISION_REQUEST | ✅ | `c08feab` |
| AL-P0-005 | Persona 自动加载缺少 Path | ✅ | `c08feab` |
| AL-P0-006 | TTS 下行 PCM 解析偏移 | ✅ | `c08feab` |

### AL-P1 系列

| 编号 | 问题 | 状态 | 证据 |
|---|---|---|---|
| AL-P1-001 | 上行裸 PCM 与 0x02 歧义 | ✅ | `0x00+PCM16` 显式 tag，`ws_handler.py` 已实现 |
| AL-P1-002 | Vision 与 LLM 同轮竞态 | ✅ | orchestrator `_on_transcript_completed` 做同轮编排 |
| AL-P1-003 | Vision context 无 TTL | ⚠️ 部分修 | `_vision_contexts` 有 session 级生命周期，但无显式 TTL 过期 |
| AL-P1-004 | persona.set 假切换 | ⚠️ 需核实 | doc09 记录修过 persona_voice_ref，但本轮未再验证 |
| AL-P1-005 | Run 创建晚于 transcript | ✅ | orchestrator `start_new_run` 在发下游事件前，重发带 re_emitted 标记 |
| AL-P1-006 | 打断只 reset 不取消 | ✅ | 批次2：mock generation 机制 + ollama reset 透传 + musetalk request id |
| AL-P1-007 | STT DROP_OLDEST 丢音频 | ✅ | STT audio.appended 改 BLOCK 策略；EventBus BLOCK 改短超时轮询 |
| AL-P1-008 | Block 实例状态隔离 | ✅ | 批次3：stt `_audio_buffers` 移实例属性；批次6：qwen3 删 `_voice_cache` 死代码、silero carry 实例化 |
| AL-P1-009 | 运行期 BlockContext.config 为空 | ✅ | orchestrator `_block_configs[category]` 存储 + process 注入 |
| AL-P1-010 | Gateway setup 清理 | ✅ | 批次6：orchestrator setup 部分失败时 shutdown 已装配 block；ws_handler setup 失败回收 |
| AL-P1-011 | Vision 帧无限制 | ✅ | WS `_MAX_MSG_SIZE` 2MB 上限 + Vision 并发锁 + 节流 + describe_frame 外层超时 |

### AL-P2 系列

| 编号 | 问题 | 状态 | 证据 |
|---|---|---|---|
| AL-P2-001 | Persona/Vision context session 结束清理 | ⚠️ 部分修 | end_session 清理 `_vision_pending`，但 `_vision_contexts` 清理依赖 session 级 teardown |
| AL-P2-002 | VoxCPM2 voice_ref 与 prompt_text 成对 | ✅ | 批次3：persona loader 删 refText→refAudio 兜底，字段分离 |
| AL-P2-003 | total_samples 生命周期 | ✅ | mock blocks reset 清零；voxcpm2/qwen3 reset 清状态 |
| AL-P2-004 | 浏览器摄像头兼容性 | ✅ | `captureAndSendFrame` 超时兜底 + vision.frame_error 降级 |
| AL-P2-005 | WS URL 固定 ws:// | ✅ | `computeWsUrl()` https 自动 wss |
| AL-P2-006 | 下行队列混排 | ✅ | 三队列分离（控制/音频/视频），控制队列不丢 |
| AL-P2-007 | receive 无超时 | ✅ | 90s idle timeout + 20s ping 心跳 |
| AL-P2-008 | Recorder 同步 write/flush | ⚠️ 已知限制 | 尝试移出锁外但引入并发写交错风险（commit `65136d5` 回退）。当前锁内 write 保证正确性，磁盘反压是已知 trade-off |
| AL-P2-009 | Vision 结果伪装 assistant transcript | ✅ | `kind: "vision"` 独立样式 |
| AL-P2-010 | Vision Block SDK 类型契约 | ⚠️ 需核实 | SDK TS 类型已修 snake_case，但 Vision describe_frame 的鸭子类型契约无显式接口 |
| AL-P2-011 | Blocks Explorer 未完成 | ❌ 未做 | 低优先级，管理台 stub 仍在 |

### AL-E2E 系列

| 编号 | 问题 | 状态 | 证据 |
|---|---|---|---|
| AL-E2E-001 | e2e_real.py 重复扫描累计事件 | ✅ | 批次10：shutdown 吞错改记 stderr |
| AL-E2E-002 | GPU 验收记录 degradation | ❌ 未做 | 需实机验证 |

### AL-QA 系列

| 编号 | 问题 | 状态 |
|---|---|---|
| AL-QA-001 | 没有 CI | ❌ 未建立 |
| AL-QA-002 | 没有浏览器 E2E | ❌ 未建立 |
| AL-QA-003 | Vision 协议测试不足 | ⚠️ 有 mock 链路测试，无真实 API |
| AL-QA-004 | Interruption 测试无 HTTP cancel | ✅ | 批次2补了 mock generation 打断回归测试 |

---

## 三、四条系统性根因（本轮发现）

1. **打断链路从未端到端贯通**：orchestrator 状态机→LLM block→Avatar block→Mock→测试，每一环都有断裂。批次 2 从 emit response.done/interrupted 到 mock generation 机制到 ollama/musetalk 透传，全链路修复。

2. **异步资源无对称 teardown**：connect/setup 路径普遍缺"重建前先释放旧资源"。批次 1/4 给 mem0/silero/AudioContext/麦克风统一补了 shutdown/close/reset。

3. **跨边界消息无关联标识**：musetalk render 无 request id、WS 事件无 stale socket 防护、EventBus 快照与 enqueue 非原子。批次 2/3/4 分别加了 request id / ws 实例比对 / 短超时轮询。

4. **声明与实现脱节（无契约测试）**：SDK 类型 camelCase、silero device=cuda 不支持、qwen3 streaming=True 但非真流式、avatar_state interrupt 死代码。批次 2/4/6 逐一修正。

---

## 四、自审发现并修复的回归

| 问题 | 引入 commit | 发现方式 | 修复 commit |
|---|---|---|---|
| recorder write 移出锁→并发写交错 | `fc52e33`（M-4） | 豆哥质疑后自审 | `65136d5`（回退到锁内 write） |

**教训**：测试全绿只意味着已有测试没回归，不等于改动正确。磁盘 IO 移出锁看似优化，实际引入数据损坏——多协程拿到同一文件句柄后 `asyncio.to_thread` 在不同线程并发 write。

---

## 五、仍开放的问题（下一步）

| 优先级 | 问题 | 说明 |
|---|---|---|
| P1 | 真实 GPU 链路验收 | silero cuda / musetalk / flashhead 本机无法验证，需 AutoDL 实机 |
| P1 | CI 建立 | AL-QA-001，无 GitHub Actions |
| P2 | 浏览器 E2E | AL-QA-002，无 Playwright/Cypress |
| P2 | AL-P2-008 Recorder 磁盘反压 | 正确性优先于性能，当前锁内 write 是已知 trade-off |
| P3 | AL-P2-011 Blocks Explorer | 管理台 stub，低优先级 |
| P3 | Session.trigger emit 乱序风险 | 移出锁后有理论乱序可能，sequence 可缓解但下游未排序 |
