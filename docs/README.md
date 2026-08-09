# AvatarLoom 文档索引

> 最后更新：2026-08-09

## 活文档（持续维护）

| 文档 | 内容 | 角色 |
|---|---|---|
| [00-完整设计文档](00-AvatarLoom-完整设计文档.md) | 产品定位、四平面架构、Block 清单、Persona 包结构 | 总纲 |
| [01-架构与模块规范](01-架构与模块规范.md) | → 已合并到 block-development.md | 存根 |
| [02-事件协议状态机与音画同步](02-事件协议状态机与音画同步.md) | 事件 Envelope、状态机、WS 通道协议、二进制 tag | **协议权威** |
| [03-Studio部署安全与验收](03-Studio部署安全与验收.md) | 页面清单、安全要求、部署形态、验收清单 | 部署安全 |
| [architecture](architecture.md) | 架构总览（三服务分离、Block 抽象、降级策略） | 入门精炼版 |
| [block-development](block-development.md) | 开发新 Block 指南 + 核心约束 | **Block 开发权威** |
| [deployment](deployment.md) | 部署与启动（dev/Docker/AutoDL）、.env 配置、鉴权 | **部署权威** |
| [08-studio-ui-spec](08-studio-ui-spec.md) | UI/UX 规格（设计令牌、组件契约、逐页清单） | 前端规格（§1/§6/§7 为历史快照） |
| [11-studio-frontend-architecture](11-studio-frontend-architecture.md) | Studio 前端架构（三模式壳、状态模型、实施记录） | **前端架构权威** |
| [12-voxemw-对照与借鉴](12-voxemw-对照与借鉴.md) | VoxEMW 上游对照、已借鉴机制、借鉴路线 | 参考 |
| [14-review-remediation-log](14-review-remediation-log.md) | 全量 review 修复记录 + AL 问题状态回填 | **问题追踪权威** |

## 阶段验收报告（时间点快照）

| 文档 | 内容 |
|---|---|
| [06-MuseTalk 验收报告](06-MuseTalk-real-lipsync-ui-report.md) | RTX 5090 实测性能、技术适配、E2E 产物（2026-08-06） |

## 归档文档（历史交接，不再维护）

`docs/archive/` 下的 3 个文档是阶段性交接快照，已被 `14-review-remediation-log.md` 取代。保留仅供历史回溯，**不要据此判断当前状态**。

| 文档 | 归档原因 |
|---|---|
| [archive/07-handover-next-dev](archive/07-handover-next-dev.md) | 08-06 交接，服务器实例已换、分支已合并 |
| [archive/09-handover-agent-teams](archive/09-handover-agent-teams.md) | 08-06 交接，已被 review 轮大幅推进 |
| [archive/10-handover-maintenance-next-agent](archive/10-handover-maintenance-next-agent.md) | AL 问题追踪表，状态已在 14 号文回填 |
