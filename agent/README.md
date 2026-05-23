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

Worker 支持两级配置：

1. **Agent 级**（优先）：Token 中的 `model_config` 和 `tts_config`，来自 Web Admin 配置池
2. **全局默认**（回退）：`.env` 中的 `LLM_PROVIDER`、`QWEN_TTS_MODEL` 等

## 配置注入流程

```
Token → agent_config {system_prompt, voice_id, model_config?, tts_config?}
  ├── model_config → LLM 动态配置（provider, model, api_key, temperature）
  ├── tts_config   → TTS 动态配置（provider, model, api_key）
  └── null         → 回退 .env
```

## .env 全局默认

| 变量 | 默认值 |
|------|--------|
| `STT_PROVIDER` | `livekit` |
| `STT_MODEL` | `deepgram/nova-2` |
| `LLM_PROVIDER` | `qwen` |
| `TTS_PROVIDER` | `qwen` |
| `QWEN_TTS_MODEL` | `qwen3-tts-flash-realtime` |
