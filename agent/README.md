# call_me Agent Worker

LiveKit Agent Worker，运行语音 AI 管线（STT → LLM → TTS）。注册到 LiveKit Cloud，通话时自动被调度到房间。

## 快速启动

```bash
# 安装依赖
pip install -e .

# 首次运行需下载模型（Silero VAD 等）
python agent.py download-files

# 开发模式（终端直接对话测试）
python agent.py console

# 生产模式（注册到 LiveKit Cloud，等待通话）
python agent.py start
```

## 项目结构

```
agent/
├── agent.py                     主入口 + 语音 AI 管线
├── qwen_tts.py                  通义 Qwen TTS 适配器（含声音复刻）
├── qwen_asr_realtime_stt.py     通义 Qwen ASR 实时识别适配器
├── Dockerfile
└── pyproject.toml
```

## 管线配置

所有组件通过环境变量切换：

### LLM（大语言模型）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `qwen` | `qwen` 或 `deepseek` |
| `QWEN_MODEL` | `qwen3-max` | Qwen 模型名 |
| `QWEN_BASE_URL` | DashScope 兼容模式地址 | |
| `DASHSCOPE_API_KEY` | - | API Key |

### STT（语音识别）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `STT_PROVIDER` | `livekit` | `qwen` 或 `livekit` |
| `STT_MODEL` | `deepgram/nova-2` | LiveKit 模式下的模型 |
| `STT_LANGUAGE` | `zh-CN` | 识别语言 |

### TTS（语音合成）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TTS_PROVIDER` | `qwen` | `qwen` 或 `elevenlabs` |
| `QWEN_TTS_MODEL` | `qwen3-tts-vc-realtime` | 含声音复刻能力 |
| `DASHSCOPE_API_KEY` | - | |

## Agent 配置的动态注入

Worker 不直接访问数据库。通话时，配置通过 LiveKit Token 的参与者属性传入：

```
Flutter App → POST /api/call/token (agent_id)
                ↓
             api 读取 SQLite 中的 Agent 配置
                ↓
             生成 Token（attributes 中嵌入 agent_config）
                ↓
             App 连接 LiveKit Room
                ↓
             LiveKit 调度 Agent Worker 进入房间
                ↓
             Worker 从参与者属性中读取 system_prompt + voice_id
                ↓
             配置 LLM 人设 + TTS 音色 → 开始对话
```

## TTS 声音复刻

`qwen_tts.py` 中的 `QwenTTS` 类支持两种方式指定声音：

- `voice`：内置音色名（如 `Cherry`、`Stella`）
- `voice_id`：通过声音复刻 API 创建的克隆音色 ID

`voice_id` 优先于 `voice`。如果 `voice_id` 为 None，则使用环境变量 `QWEN_TTS_VOICE` 指定的内置音色。
