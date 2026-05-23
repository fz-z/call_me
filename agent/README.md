# call_me Agent Worker

LiveKit Agent Worker — STT → LLM → TTS 语音管线。

## 快速启动

```bash
pip install -e .
python agent.py download-files  # 首次
python agent.py console         # 终端测试
python agent.py start           # 生产模式
```

## 管线配置

Worker 从 LiveKit Token 中读取 `agent_config`，动态配置 LLM + TTS：

1. **Token 内嵌配置**（优先）：API 在生成 Token 时始终嵌入有效的 `model_config` 和 `tts_config`
2. **紧急回退**（仅数据库完全为空时）：硬编码默认模型 + `DASHSCOPE_API_KEY`

## 配置注入流程

```
Token → agent_config {system_prompt, voice_id, model_config, tts_config}
  ├── model_config → LLM 动态配置（provider, model, api_key, temperature）
  ├── tts_config   → TTS 动态配置（provider, model, api_key）
  └── API 保证 model_config 和 tts_config 始终有值（回退到 DB 默认）
```

## .env 回退配置

仅在数据库完全无可用配置时生效，正常运行时由 Web Admin 管理：

| 变量 | 默认值 |
|------|--------|
| `DASHSCOPE_API_KEY` | - |
| `DEFAULT_LLM_TEMPERATURE` | `0.7` |
| `DEFAULT_SYSTEM_PROMPT` | 你是一位贴心的语音智能助手。 |

## 通话行为

- 接通后 Agent 主动打招呼（LLM 生成符合人设的开场白）
- 可配置开场白提示词：`INITIAL_GREETING_PROMPT`
