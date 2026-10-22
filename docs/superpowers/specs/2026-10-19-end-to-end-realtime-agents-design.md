# 端到端实时语音 Agent 设计

## 目标

在保留当前 STT → LLM → TTS（下称“经典管线”）通话方式的前提下，为每个 Agent 增加可选择的端到端实时通话方式。第一批接入千问实时模型；数据模型与运行时边界必须允许未来接入其他供应商，而无需改变 Agent、音色库或客户端调用方式。

已有 Agent 必须保持经典管线，升级后通话行为不能改变。

## 非目标

- 本期不移除 Deepgram、Qwen LLM 或 Qwen TTS 的经典管线。
- 本期不接入第二家端到端供应商；仅定义并验证提供商适配器扩展点。
- 最终用户的 Flutter 拨号页不提供运行模式选择。
- 端到端服务失败时不自动降级到经典管线，以免在未经确认的情况下改变模型、延迟、声音或工具行为。

## 术语

| 术语 | 含义 |
| --- | --- |
| `pipeline` | 当前的 STT → LLM → TTS 通话模式。 |
| `realtime` | 单一模型接受实时音频并生成实时音频/文本的端到端模式。 |
| 实时模型配置 | 一个可由管理员管理的供应商、模型、密钥、地域和端点组合。 |
| 音色档案 | 面向业务展示的“某人的声音”；不直接等同于供应商音色 ID。 |
| 音色绑定 | 音色档案在某个目标模型上创建得到的供应商音色 ID。 |

## 总体架构

```text
Flutter App ── LiveKit 房间 ── Agent Worker
                                  │
                       Agent.runtime_mode
                         ┌────────┴────────┐
                         │                 │
                    pipeline           realtime
                         │                 │
     STT → LLM → TTS AgentSession   RealtimeProviderAdapter
                         │                 │
                  LiveKit 音频轨   PCM ↔ Provider WebSocket/WebRTC
```

API 仍是配置与鉴权的唯一来源。LiveKit token 只携带 `agent_id`、`runtime_mode`、通话日志 ID 等非敏感数据。Worker 在建立会话时使用 `WORKER_INTERNAL_SECRET` 向 API 读取运行时配置；API Key 和供应商音色 ID 不进入客户端 token、公开或管理员前端接口响应，且不写入日志。

Worker 优先读取 LiveKit job metadata。自动派发不会把 participant attributes 填充到 job metadata，因此 Worker 在元数据缺失时连接房间并回退读取调用方的 `agent_config` attribute；这是当前 API token 的实际契约，两条路径都必须保留。

## 数据模型

### 1. Agent 模式

为 `agents` 表增加：

```sql
ALTER TABLE agents ADD COLUMN runtime_mode TEXT NOT NULL DEFAULT 'pipeline';
ALTER TABLE agents ADD COLUMN realtime_config_id TEXT
  REFERENCES realtime_configs(id) ON DELETE SET NULL;
```

取值只能为 `pipeline` 或 `realtime`。应用层校验：

- `pipeline` 必须使用现有的 `model_config_id`、`tts_config_id` 规则；
- `realtime` 必须指定有效的 `realtime_config_id` 与一个匹配的音色绑定；
- 创建与更新 API、授权复制 API、输出 DTO 和内部 worker runtime API 都携带这两个字段。

已有记录保留或显式回填为 `pipeline`。复制 Agent 时完整复制模式、实时模型配置和音色档案引用。

### 2. 实时模型配置池

新增 `realtime_configs`：

```sql
CREATE TABLE realtime_configs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  api_key_id TEXT REFERENCES api_keys(id) ON DELETE SET NULL,
  api_key TEXT NOT NULL DEFAULT '',
  endpoint TEXT NOT NULL DEFAULT '',
  region TEXT NOT NULL DEFAULT '',
  capabilities_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
```

`capabilities_json` 首期记录诸如 `voice_clone`、`audio_input`、`audio_output`、`text_transcript`、`function_calling`。它只用于 UI 过滤与配置校验，不能代替 Worker 内的提供商能力判断。

首期受支持的配置为：`provider=qwen`，`model=qwen-audio-3.1-realtime-plus` 或 `qwen-audio-3.0-realtime-plus`。管理端将模型、端点和地域作为明确配置，而不是散落在环境变量中。其它供应商只须新增 provider 值和适配器。

### 3. 音色档案与模型绑定

当前 `voices` 表代表业务音色档案，继续被 `agents.voice_pool_id` 引用。保留 `voices.voice_id` 一次发布作为兼容字段，但新的运行时解析只使用绑定表：

```sql
CREATE TABLE voice_runtime_bindings (
  id TEXT PRIMARY KEY,
  voice_pool_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
  runtime_kind TEXT NOT NULL,
  runtime_config_id TEXT NOT NULL,
  provider_voice_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(voice_pool_id, runtime_kind, runtime_config_id)
);
```

`runtime_kind` 是 `tts` 或 `realtime`：

- 现有 `voice_tts_links` 会被迁移为 `tts` 绑定，`provider_voice_id` 取现有 `voices.voice_id`；旧表继续保留兼容读取，直至迁移验证完成。
- 复刻端到端音色时，上传音频、选择实时模型配置，API 以该配置的模型为目标创建音色，并写入 `realtime` 绑定。
- 同一音色档案可以有多个绑定。例如，用户选择同一段参考音频，分别为 `qwen3-tts-flash-realtime` 与 `qwen-audio-3.1-realtime-plus` 生成不同的供应商音色 ID。

这样不会把“展示名称”与“供应商专属且目标模型专属的 ID”混在同一个字段里。

## API 边界

新增管理员 API：

| 路径 | 用途 |
| --- | --- |
| `GET/POST/PATCH/DELETE /api/admin/realtime-configs` | 管理端到端模型配置；删除被 Agent 或绑定引用时拒绝。 |
| `GET /api/admin/voices/{id}/runtime-bindings` | 按音色档案读取所有 TTS / Realtime 绑定（供应商 ID 脱敏）。 |
| `POST /api/admin/voices/{id}/realtime-bindings` | 上传有授权的参考音频，选择实时配置，创建/更新端到端音色绑定。 |
| `POST /api/admin/voices/{id}/audition` | 增加明确的运行时配置参数，试听指定绑定；不再隐式取第一条 TTS 关联。 |

修改以下现有边界：

- `POST/PATCH /api/agents`：接受 `runtime_mode` 和 `realtime_config_id`，按模式进行互斥校验；
- `GET /api/agents`、管理员 Agent 详情、授权副本接口：返回运行模式和实时配置 ID；
- `VoiceOut` 与所有声音库前端响应：移除现有的原始 `voice_id` 字段，改为仅返回业务音色档案 ID、名称、类型及可用绑定摘要；原始供应商 ID 只允许内部 worker runtime API 读取；
- `/api/internal/worker/agent-runtime/{agent_id}`：按模式返回最小的 worker 配置。经典管线返回 LLM、TTS 与解析后的音色；实时模式返回 `realtime_config` 和精确匹配的 `provider_voice_id`；
- `call_logs` 增加 `runtime_mode`、`provider`、`model`、`failure_stage` 和 `failure_reason`，其中失败原因是经脱敏的诊断文本。

所有写入端点保持管理员鉴权。参考音频必须代表上传者拥有或获授权使用的声音；管理台在上传前显示确认文案并记录该确认。

## Worker 与提供商适配器

定义独立于具体供应商的协议：

```python
class RealtimeProviderAdapter(Protocol):
    provider: str

    def validate_config(self, config: RealtimeRuntimeConfig) -> None: ...
    async def run(self, bridge: LiveKitAudioBridge,
                  config: RealtimeRuntimeConfig,
                  on_event: RealtimeEventHandler) -> None: ...
    async def close(self) -> None: ...
```

`LiveKitAudioBridge` 是 Worker 内的公共层，负责：订阅呼叫者的 LiveKit 音轨、转换为提供商要求的 PCM 格式、接收模型输出音频、发布 Agent 音轨，以及将可用的最终转录事件交给通话日志。适配器不得直接依赖 Agent 表、数据库或 Web 管理端。

`QwenRealtimeAdapter` 是首个实现。它负责千问 WebSocket 协议、会话配置、`voice` 设置、事件映射、重连范围内的网络错误与正常关闭。首期支持 `qwen-audio-3.1-realtime-plus` 与 `qwen-audio-3.0-realtime-plus`；配置结构允许未来同 provider 加入其他模型。

经典管线保持当前 `AgentSession` 与 Qwen TTS 实现。模式分发收敛在单独的 runtime factory，避免继续增长 `agent.py` 中的大型条件分支。

## 管理台交互

### Agent 创建与编辑

创建向导第一步选择“对话引擎”：

| 模式 | 步骤 |
| --- | --- |
| 经典管线 | 对话引擎 → TTS 模型 → 音色 → LLM 模型 → 人设与照片 |
| 端到端实时 | 对话引擎 → 实时模型 → 音色 → 人设与照片 |

- 端到端模式隐藏 STT、LLM、TTS 选择器；这些能力由实时模型一体化提供。
- 选定实时模型后，音色列表仅显示拥有对应 `realtime` 绑定的音色档案。
- 如果没有兼容绑定，向导提供“复刻新音色”入口；创建成功后回到向导并自动选中。
- 编辑 Agent 切换模式时必须先选择新的模型和兼容音色，并显示“此变更会改变通话引擎”的二次确认。
- 现有 Agent 编辑页面的“Pipeline 配置”在 `realtime` 模式下改为“实时通话配置”。

### 配置与声音库

- 新增“实时模型”导航页面：名称、供应商、模型、API Key、地域/端点、支持能力、被 Agent 使用次数。
- 声音库详情显示绑定矩阵，按“经典 TTS”和“端到端实时”分组。一个档案可有多个绑定；供应商音色 ID 不显示完整值。
- 试听必须让管理员指定模型绑定，不能再依据创建时间隐式选第一条关联。
- Agent 列表、详情和通话记录显示紧凑标签：`经典管线` 或 `端到端 · {provider}`。

### 最终用户体验

Flutter 端保持拨号操作不变。模式对用户不可选；拨号前 API 已保证被呼叫 Agent 的配置完整。端到端连接初始化失败时，客户端显示“该 Agent 的实时语音服务暂不可用”，不改拨号为经典模式。

## 迁移与发布

1. 先发布只读兼容的数据库迁移和 API 输出字段，所有旧 Agent 默认 `pipeline`。
2. 迁移 `voice_tts_links` 为 TTS 运行时绑定；抽样校验每个原有 Agent 都能解析到与升级前相同的 TTS 和音色 ID。
3. 发布实时配置池、声音绑定 API 和后台配置页面，但不启用任何实时 Agent。
4. 发布 Qwen 适配器和端到端创建向导，用一个管理员测试 Agent 验证双向音频、音色、日志与失败提示。
5. 开放正式创建；旧 Agent 不做自动迁移。

数据库迁移必须可重复执行，不删除旧字段或旧关联表。移除兼容读取只能在单独的、经数据审计确认的后续版本进行。

## 失败处理与可观测性

| 阶段 | 行为 |
| --- | --- |
| Agent 保存 | 模式、模型、音色绑定、密钥引用任一不完整时返回字段级错误。 |
| 拨号前 | API 拒绝向配置不完整的 Agent 签发通话 token。 |
| Worker 连接 | 对端点、鉴权或协议错误记录脱敏失败阶段，停止该次通话。 |
| 通话中断 | 停止发布音频、断开提供商会话、结束 call log，向客户端发送可理解错误。 |
| 重连 | 只在当前实时会话的安全边界内进行有限重试；不在新会话中恢复上下文，也不切换模式。 |

日志和 API 响应不得包含 API Key、Authorization header、完整 `provider_voice_id` 或原始上传音频。管理员日志可见 provider、model、模式、耗时、失败阶段与 request ID。

## 验收标准

- 所有已存在的 Agent 使用 `pipeline`，其创建、编辑、授权、拨号和声音解析行为不变。
- 管理员能创建实时配置、为指定实时模型复刻音色、创建端到端 Agent，并通过 LiveKit 完成双向音频。
- 同一个音色档案可以同时解析不同 TTS 与实时模型的供应商音色 ID。
- 端到端 Agent 不展示或要求独立 STT、LLM、TTS 选择；经典 Agent 不展示实时模型选择。
- 不兼容音色、无效地域、缺失密钥、连接失败和通话中断均有明确错误、可追溯 call log，并且不会静默降级。
- 适配器契约测试使用假 adapter；Qwen adapter 用录制的 WebSocket 事件和可控音频夹具进行集成测试；CI 不调用真实付费服务。

## 验证策略

- API 单元/集成测试：迁移幂等、按模式校验、配置删除保护、运行时配置脱敏、授权副本传播、旧 API 兼容。
- Worker 测试：runtime factory 分发、Qwen 事件到 LiveKit bridge 的映射、终止与资源清理、脱敏日志。
- 管理端测试：两种向导分支、兼容音色过滤、切换确认、无绑定时的复刻入口、配置错误展现。
- Flutter 测试：新通话初始化错误文案与现有正常拨号流程不回归。
