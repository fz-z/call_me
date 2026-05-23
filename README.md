# call_me

语音 AI 通话应用 —— 创建拥有复刻音色和个性化人设的 AI Agent，随时随地拨打通话。

## 已实现功能

### 核心通话
- **实时语音通话**：Flutter App 一键呼叫，WebRTC 直连 LiveKit Cloud
- **Agent 选择**：首页下拉框切换不同的 Agent，每个有独立的声音和人设
- **声音复刻**：上传音频样本 → DashScope 克隆音色 → Agent 用你的声音说话
- **内置音色**：支持 DashScope 内置音色（Cherry、Stella 等），无需上传音频

### Agent 管理
- **创建 Agent**：上传音频 + 起别名 + 写人设描述
- **编辑 Agent**：在 App 内点击 Agent → 修改别名和人设 → 保存即生效
- **删除 Agent**：App 内一键删除
- **种子 Agent**：在 `.env` 中配置 `SEED_AGENT_*` 变量，启动时自动创建

### 权限管理
- **用户注册/登录**：JWT 认证
- **Admin 面板**：Admin 登录后在 Agent 列表页看到盾牌图标 → 进入管理面板
- **授权/撤销**：Admin 可将任意 Agent 授权给任意用户
- **隐式权限**：创建者自动拥有自己的 Agent

### 部署运维
- **Docker Compose 一键部署**：`docker compose up -d`
- **Swagger 文档**：`http://localhost:8000/docs` 可直接调试所有 API
- **31 个单元测试**：覆盖 database、auth、agents、permissions、call
- **环境变量驱动**：所有管道组件（STT/LLM/TTS）可通过 `.env` 切换

### Flutter 页面（6 屏）
| 页面 | 功能 |
|------|------|
| Login | 注册 / 登录 |
| Home | Agent 下拉选择 + 一键通话 + 底部导航 |
| Call | 通话中界面（麦克风状态 + 计时 + 挂断） |
| Agent List | Agent 列表 + 创建 + 删除 + Admin 入口 |
| Agent Detail | 编辑别名和人设 |
| Settings | 服务器地址配置 + 登出 |

## 快速开始

### 1. 准备环境

- 注册 [LiveKit Cloud](https://cloud.livekit.io/) 获取 API Key
- 注册 [阿里云 DashScope](https://dashscope.aliyun.com/) 获取 API Key

> 详细步骤见 **[环境搭建指南](docs/SETUP.md)**

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入真实的 API Keys
```

### 3. 一键部署

```bash
docker compose up -d
```

两个容器：`api`（FastAPI 后端，端口 8000）和 `agent`（LiveKit Agent Worker）。

### 4. 启动 Flutter App

```bash
cd app
flutter pub get
flutter run -d chrome    # Chrome 浏览器
flutter run               # 自动选择可用设备（模拟器/真机）
```

## 使用流程

1. 打开 App → 注册账号（或登录 admin / admin）
2. 创建 Agent：上传音频样本 → 起别名 → 写人设
3. 首页选择 Agent → 点击"开始通话"
4. 跟 AI 实时语音对话
5. Admin 可在 Agent 列表页点盾牌图标 → 授权给其他用户

## 项目结构

```
call_me/
├── api/                    FastAPI 后端（16 个端点，31 个测试）
│   ├── main.py            App 入口、路由注册
│   ├── auth.py            注册/登录、JWT 认证
│   ├── agents.py          Agent CRUD
│   ├── permissions.py     授权/撤销（admin）
│   ├── admin.py           管理员面板
│   ├── call.py            通话 Token 生成
│   ├── sip.py             SIP 绑定
│   ├── voice_enrollment.py DashScope 声音复刻
│   ├── database.py        SQLite + 种子数据
│   ├── models.py          Pydantic 模型
│   └── tests/             31 个单元测试
├── agent/                  LiveKit Agent Worker
│   ├── agent.py           语音管线（STT+LLM+TTS）
│   ├── qwen_tts.py        Qwen TTS 适配器（支持流式 WebSocket）
│   ├── qwen_asr_realtime_stt.py  Qwen ASR 适配器
│   └── simple_qwen_tts.py 简化版 HTTP TTS（备用）
├── app/                    Flutter App（6 屏）
│   └── lib/
│       ├── main.dart
│       ├── models/agent.dart
│       ├── services/api_service.dart
│       └── screens/ (login, home, call, agent_list, agent_detail, agent_create, admin, settings)
├── docker-compose.yml
├── .env.example
└── docs/
    ├── SETUP.md           环境搭建详细指南
    └── superpowers/       Spec + Plan
```

## 技术栈

| 层 | 选择 |
|----|------|
| 后端 API | Python / FastAPI |
| 数据库 | SQLite |
| Agent | Python / LiveKit Agents |
| 语音识别 (STT) | Deepgram（通过 LiveKit Cloud） / Qwen ASR |
| 大语言模型 (LLM) | 通义千问 / DeepSeek |
| 语音合成 (TTS) | 通义 Qwen TTS（流式 + 声音复刻） / ElevenLabs |
| 实时通信 | LiveKit Cloud (WebRTC / SIP) |
| 移动端 | Flutter |
| 部署 | Docker Compose |

## 环境变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key | - |
| `LIVEKIT_URL` | LiveKit 服务器地址 | - |
| `LIVEKIT_API_KEY` | LiveKit API Key | - |
| `LIVEKIT_API_SECRET` | LiveKit API Secret | - |
| `STT_PROVIDER` | 语音识别提供商 | `livekit` |
| `STT_MODEL` | STT 模型 | `deepgram/nova-2` |
| `STT_LANGUAGE` | 识别语言 | `zh-CN` |
| `LLM_PROVIDER` | 大语言模型提供商 | `qwen` |
| `QWEN_MODEL` | Qwen LLM 模型 | `qwen3-max` |
| `TTS_PROVIDER` | 语音合成提供商 | `qwen` |
| `QWEN_TTS_MODEL` | TTS 模型 | `qwen3-tts-vc-realtime-2026-01-15` |
| `QWEN_TTS_VOICE` | TTS 默认音色 | `Cherry` |
| `ADMIN_USERNAME` | 管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理员密码 | `admin` |
| `JWT_SECRET` | JWT 签名密钥 | `changeme` |
| `SEED_AGENT_ALIAS` | 种子 Agent 别名（可选） | - |
| `SEED_AGENT_SYSTEM_PROMPT` | 种子 Agent 人设 | - |
| `SEED_AGENT_VOICE` | 种子 Agent 音色 | `Cherry` |
| `SEED_AGENT_OWNER` | 种子 Agent 所有者 | `admin` |

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | 用户登录 |
| `/api/agents` | POST | 创建 Agent（上传音频 + 别名 + 人设） |
| `/api/agents` | GET | 列出我的可用 Agent |
| `/api/agents/{id}` | GET | 获取 Agent 详情 |
| `/api/agents/{id}` | PATCH | 更新 Agent 别名/人设 |
| `/api/agents/{id}` | DELETE | 删除 Agent |
| `/api/agents/{id}/grant` | POST | 授权 Agent 给用户（admin） |
| `/api/agents/{id}/grant/{username}` | DELETE | 撤销授权（admin） |
| `/api/admin/users` | GET | 列出所有用户（admin） |
| `/api/admin/agents` | GET | 列出所有 Agent（admin） |
| `/api/call/token` | POST | 获取通话 Token |
| `/api/sip/bind` | POST | 绑定 SIP 手机号（admin） |
| `/api/sip/status` | GET | 查询 SIP 状态（admin） |
| `/api/health` | GET | 健康检查 |

## API 使用示例

```bash
BASE=http://localhost:8000

# 注册并登录
curl -X POST $BASE/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"secret123"}'

TOKEN=$(curl -s -X POST $BASE/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"secret123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 创建 Agent
curl -X POST $BASE/api/agents \
  -H "Authorization: Bearer $TOKEN" \
  -F "alias=温柔客服" \
  -F "system_prompt=你是一位温柔耐心的客服" \
  -F "audio_file=@sample.wav"

# 编辑 Agent 人设
curl -X PATCH $BASE/api/agents/<agent-id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"alias":"新名字","system_prompt":"新的人设描述"}'

# 获取通话 Token
curl -X POST $BASE/api/call/token \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"agent_id":"<agent-id>"}'

# Admin 授权
curl -X POST $BASE/api/agents/<agent-id>/grant \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"username":"bob"}'
```

## 运行测试

```bash
cd api
python3 -m pytest tests/ -v
# 31 passed
```
