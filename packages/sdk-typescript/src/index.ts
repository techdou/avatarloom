// AvatarLoom TypeScript SDK — 公共入口。
// 内容全部由 scripts/gen_protocol.py 从 packages/protocol 生成，此处只做 re-export。
// NodeNext 解析要求显式 .js 扩展名（指向编译产物，tsc 会自动映射回 .ts 源码）。

export * from "./generated/events.js";
export * from "./generated/state.js";
