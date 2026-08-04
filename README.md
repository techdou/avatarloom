# AvatarLoom / 灵构

> Weave voices, minds and faces into digital humans.  
> 将声音、人格与形象，编织成可运行的数字人。

AvatarLoom（灵构）是一个面向实时 AI 数字人的模块化编排与运行框架设计方案。它把 VAD、STT、LLM、Memory、Persona、TTS、Avatar、Vision、Skills、Transport、Safety 和 Observability 拆分成可替换的 Block，由 Runtime Orchestrator 统一编排。

本包包含项目设计文档、完整开发 Prompt、分阶段开发 Prompt、Runtime Profile 和配置模板。它可以作为 GitHub 项目立项资料，也可以直接提供给 ChatGPT Agent、Codex、Claude Code 或 OpenCode 驱动开发。

## 目录

```text
avatarloom-design-pack-v0.1.0/
├── README.md
├── CHANGELOG.md
├── manifest.json
├── docs/
│   ├── 00-AvatarLoom-完整设计文档.md
│   ├── 01-架构与模块规范.md
│   ├── 02-事件协议状态机与音画同步.md
│   └── 03-Studio部署安全与验收.md
├── prompts/
│   ├── 00-AvatarLoom-完整项目开发Prompt.md
│   ├── 01-Phase1-项目骨架与Mock链路Prompt.md
│   └── 02-Phase2-真实语音与数字人链路Prompt.md
├── profiles/
│   ├── lite-12gb.yaml
│   ├── distributed.yaml
│   └── full-24gb.yaml
└── templates/
    ├── avatarloom.yaml
    ├── block.yaml
    └── persona-package/
        ├── persona.yaml
        ├── persona.md
        ├── voice/
        └── avatar/
```

## 使用方法

完整开发：使用 `prompts/00-AvatarLoom-完整项目开发Prompt.md`。

分阶段开发：先使用 Phase 1 Prompt 完成协议、Block SDK、Mock 全链路和 Recorder，再使用 Phase 2 Prompt 接入真实模型和 Avatar。

## 核心原则

1. 数字人不是一个模型，而是一组可组合能力。
2. Runtime 核心不得依赖具体模型名称。
3. 所有模型通过 Block Adapter 接入。
4. 浏览器只连接 Runtime Gateway。
5. 音频是音画同步主时钟。
6. Avatar、Vision 等可选模块故障时，主语音链路必须降级运行。
7. 每轮运行必须可记录、复现、分析和评测。
8. Mock Profile 必须始终可运行。

## 当前边界

本包是设计与开发指令包，不包含已经实现完成的 AvatarLoom 源码。开发 Agent 应按照 Prompt 创建项目、执行测试、修复错误并形成可运行交付。
