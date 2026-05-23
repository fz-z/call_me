# call_me

语音 AI 通话应用 —— 创建拥有复刻音色和个性化人设的 AI Agent，随时随地拨打通话。

## 架构

```
Flutter App (通话) ──── LiveKit Cloud ──── Agent Worker (STT+LLM+TTS)
       │                                        │
       └──── api (FastAPI) ───── DashScope ─────┘
                  │
          Web Admin (Vue 3)
```

- **Flutter App**：用户登录 → 选 Agent → 一键通话
- **Web Admin**：管理员在浏览器管理 Agent、用户、授权
- **api**：FastAPI 后端，16 个端点，SQLite 持久化
- **agent**：LiveKit Agent Worker，STT→LLM→TTS 语音管线

## 已实现功能

### 通话
- 实时语音通话（WebRTC via LiveKit Cloud）
- 多 Agent 选择（不同声音 + 不同人设）
- 流式 TTS（DashScope WebSocket，低延迟）

### Agent 管理（Web Admin）
- 根机器人列表 + 创建 + 编辑 + 删除
- 按用户授权（生成独立副本，每人可自定义人设）
- 机器人详情（查看所有副本及每人的人设）
- 可搜索下拉框快速授权

### 用户管理（Web Admin）
- 用户列表 + 查看每人拥有的 Agent
- Agent 标签可一键回收授权
- 删除用户（级联删除其 Agent）

### Flutter App
- 登录/注册
- Agent 选择 + 一键通话
- 编辑自己 Agent 的人设
- 设置（服务器地址 + 登出）

### 权限模型
- 授权 = 创建独立副本（每人改人设互不影响）
- 回收可在机器人页、详情页、用户页三处操作
- 授权只在机器人列表或详情页

### 部署
- Docker Compose 一键部署（2 个容器）
- Web Admin 和 API 同域名，无 CORS
- .env 驱动所有配置
- 31 个单元测试

## 快速开始

### 1. 配置

```bash
cp .env.example .env
# 编辑 .env，至少填入 DASHSCOPE_API_KEY、LIVEKIT_URL、LIVEKIT_API_KEY、LIVEKIT_API_SECRET
```

### 2. 一键部署

```bash
docker compose up -d
```

两个容器：`api`（端口 8000）和 `agent`（LiveKit Worker）。确认运行正常：

```bash
curl http://localhost:8000/api/health  # → {"status":"ok"}
```

### 3. 创建 Agent

打开 **http://localhost:8000/admin/** → 用管理员账号登录 → 点"+ 创建 Agent" → 上传一段音频 → 填写别名和人设 → 保存。

或者直接在 `.env` 里配置种子 Agent（取消注释 `SEED_AGENT_*`），重启后自动创建。

### 4. 打电话

**方式 A：手机 App（推荐）**

```bash
cd app
flutter pub get
flutter run      # Chrome 浏览器 / 模拟器 / 真机
```

打开 App → 注册或登录 → 首页下拉选择 Agent → 点击"开始通话"。

**方式 B：终端测试**

```bash
cd agent
pip install -e .
python agent.py console
```

直接在终端里语音对话，无需 App。

### 5. 管理（Web Admin）

http://localhost:8000/admin/ — 创建/编辑/删除 Agent、管理用户、授权回收。

## .env 关键配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope | - |
| `LIVEKIT_URL` | LiveKit 服务器 | - |
| `LIVEKIT_API_KEY` | LiveKit API Key | - |
| `LIVEKIT_API_SECRET` | LiveKit API Secret | - |
| `STT_PROVIDER` | STT 提供商 | `livekit` |
| `LLM_PROVIDER` | LLM 提供商 | `qwen` |
| `TTS_PROVIDER` | TTS 提供商 | `qwen` |
| `QWEN_TTS_MODEL` | TTS 模型 | `qwen3-tts-vc-realtime-2026-01-15` |
| `ADMIN_USERNAME` | 管理员 | `admin` |
| `ADMIN_PASSWORD` | 管理员密码 | `admin` |
| `SEED_AGENT_*` | 种子 Agent | 可选 |

> 完整配置见 `.env.example` 和 `docs/SETUP.md`

## 项目结构

```
call_me/
├── api/              FastAPI 后端 (16 端点, 31 测试)
├── agent/            LiveKit Agent Worker
├── app/              Flutter App (通话端)
├── web-admin/        Vue 3 Web 管理后台
├── docker-compose.yml
└── docs/
```

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 注册 |
| `/api/auth/login` | POST | 登录 |
| `/api/agents` | POST | 创建 Agent |
| `/api/agents` | GET | 我的 Agent |
| `/api/agents/{id}` | GET/PATCH/DELETE | Agent CRUD |
| `/api/agents/{id}/grant` | POST | 授权（创建副本） |
| `/api/agents/{id}/grant/{user}` | DELETE | 回收 |
| `/api/admin/root-agents` | GET | 根机器人列表 |
| `/api/admin/agents` | GET | 所有 Agent |
| `/api/admin/agents/{id}/copies` | GET | 机器人副本 |
| `/api/admin/users` | GET/DELETE | 用户管理 |
| `/api/admin/users/{user}/agents` | GET | 某用户的 Agent |
| `/api/call/token` | POST | 通话 Token |
| `/api/health` | GET | 健康检查 |
