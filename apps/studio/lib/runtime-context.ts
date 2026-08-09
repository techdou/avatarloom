/** Studio 各入口共享的运行时上下文默认值与持久化键。 */
export const DEFAULT_PROFILE_ID = "mock";
export const DEFAULT_PERSONA_ID = "demo-assistant";

export const RUNTIME_CONTEXT_STORAGE = {
  profile: "al.profile",
  persona: "al.persona",
} as const;
