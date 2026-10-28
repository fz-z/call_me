# Realtime 固定开场白设计

## 目标

为端到端实时 Agent 增加独立的“固定开场白”配置。配置非空时，通话接通后向 Realtime 模型施加首句必须朗读该文本的约束；配置为空时，维持当前基于人设生成开场白的行为。

## 范围

- 仅端到端实时 Agent 在运行时使用该配置；经典 Pipeline 忽略它。
- 管理后台在创建、编辑 Agent，以及编辑授权副本时提供该字段，字段只在选择实时模式时显示。
- 配置会随 Agent 与授权副本持久化、通过 Worker 私有运行时配置下发，并在模型会话建立时生效。
- 不增加录音、预生成音频或独立 TTS 配置。Realtime 模型仍负责生成开场音频，因此无法提供音频输出逐字不变的硬保证。

## 数据和 API

在 `agents` 增加 `greeting_text TEXT NOT NULL DEFAULT ''`。数据库初始化包含该列，已有库通过迁移补齐默认空字符串。

`AgentCreate`、`AgentUpdate` 和 `AgentOut` 增加 `greeting_text`：

- 创建时默认为空字符串。
- 更新时未传入则保留旧值；传入后去除首尾空白。
- 非空值最长 300 个字符；超限返回 422。
- 复制 Agent 时复制该字段。

Worker 私有的 `resolve_agent_runtime_config` 在运行时负载中带上 `greeting_text`。公有 LiveKit Token 不增加该字段。

## 管理后台

在 Agent 配置中把字段置于“人设”之后，标签为“固定开场白（仅端到端实时）”。输入框为空时显示提示：“留空则由人设生成开场白”。

创建向导、详情页的 Agent 配置编辑、管理员快速编辑、用户 Agent 编辑和授权副本编辑都读取并提交此字段。运行模式为 Pipeline 时字段隐藏，但已保存值不被清空，以便日后切回实时模式后恢复。

## 实时运行行为

Qwen Realtime Adapter 建立会话时：

1. 保持现有 `session.update`、模拟用户消息和 `response.create` 的启动流程。
2. `greeting_text` 非空时，将系统人设与首句约束组合为 instructions：首个响应只能朗读配置文本，不添加、删减或改写；朗读后等待用户输入。
3. `greeting_text` 为空时，instructions 与现有 `system_prompt` 保持一致，保留当前自由生成的开场行为。

这是对模型的强约束，而不是确定性 TTS；模型提供商仍可能违反指令。该限制会在后台文案中明确说明。

## 错误处理和兼容性

- 所有历史 Agent 因默认空字符串继续走原开场逻辑。
- 缺失或空白配置不触发额外指令。
- Pipeline Agent 不因保存该字段而改变行为。
- 配置内容不包含密钥，不需要额外脱敏处理。

## 测试

- API：迁移补列、创建/更新/复制/返回该字段、300 字符限制和空值兼容。
- Worker：Realtime 配置存在固定文本时，`session.update` instructions 包含首句硬约束；为空时保持原 instructions。
- 后台：构建的 Agent 请求带上 `greeting_text`，Realtime 配置显示该字段，Pipeline 不显示，编辑初始化并提交该字段。
- 回归：现有 Realtime 启动与 Pipeline 问候测试继续通过。
