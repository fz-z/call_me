# call_me Agent Worker

LiveKit Agent Worker。运行语音 AI 管线（STT → LLM → TTS），注册到 LiveKit Cloud。

## 快速启动

```bash
pip install -e .
python agent.py download-files  # 首次
python agent.py console         # 终端对话测试
python agent.py start           # 生产模式
```

## 管线配置

所有组件通过 `.env` 切换：

| 变量 | 默认 | 说明 |
|------|------|------|
| `STT_PROVIDER` | `livekit` | `livekit`(Deepgram) 或 `qwen` |
| `STT_MODEL` | `deepgram/nova-2` | |
| `STT_LANGUAGE` | `zh-CN` | |
| `LLM_PROVIDER` | `qwen` | `qwen` 或 `deepseek` |
| `QWEN_MODEL` | `qwen3-max` | |
| `TTS_PROVIDER` | `qwen` | `qwen` 或 `elevenlabs` |
| `QWEN_TTS_MODEL` | `qwen3-tts-vc-realtime` | VC 流式 WebSocket |
| `QWEN_TTS_VOICE` | `Cherry` | 默认音色 |

## Agent 配置注入

Worker 不访问数据库。通话时配置通过 LiveKit Token 的参与者属性传入：

```
Flutter App → POST /api/call/token (agent_id)
           → api 读 SQLite，生成 Token（attributes 含 agent_config）
           → App 连 LiveKit Room
           → LiveKit 调度 Agent Worker
           → Worker 从 remote_participants 读 system_prompt + voice_id
           → 配置 LLM + TTS → 对话
```

## Turn Detection

使用新版 `TurnHandlingOptions` API（`turn_detection` + `preemptive_generation` 已废弃）。
