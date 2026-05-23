# call_me

语音 AI 通话应用 —— 创建拥有复刻音色和个性化人设的 AI Agent，随时随地拨打通话。

## 架构

```
Flutter App (通话) ──── LiveKit Cloud ──── Agent Worker (STT+LLM+TTS)
       │                                        │
       └──── api (FastAPI:8000) ──── DashScope ──┘
                  │
          Web Admin (Vue 3)
```

- **Flutter App**：用户登录 → 选 Agent → 一键通话
- **Web Admin**：管理员在浏览器管理 Agent、用户、权限、模型配置、声音库
- **api**：FastAPI 后端、SQLite 持久化、静态文件 serve
- **agent**：LiveKit Agent Worker，STT→LLM→TTS 语音管线

## 配置管理

**首次启动**：`.env` 中的 API Key 和配置初始化到数据库配置池。  
**后续运行**：所有配置通过 Web Admin 页面管理，重启不会覆盖。  
**Agent 回退**：未配置模型/TTS 的 Agent 自动使用数据库中第一个可用配置。

```
.env (首次) → 数据库配置池 ──→ Agent Token ──→ Agent Worker
     ↑                    ↑              ↑
   仅首次种子         Web Admin 管理   始终嵌入有效配置
```

## 快速开始

```bash
cp .env.example .env    # 编辑填入真实 Key
docker compose up -d    # 启动服务端

# Web Admin: http://localhost:8000/admin/
# API Docs:  http://localhost:8000/docs

cd app && flutter run -d chrome  # 启动 Flutter App
```

## 已实现功能

### 通话
- 实时语音通话（WebRTC via LiveKit Cloud）
- 接通后 Agent 主动打招呼（LLM 生成开场白）
- 多 Agent 选择（不同声音 + 不同人设）
- 流式 TTS（DashScope WebSocket，低延迟）

### Agent 管理
- **4 步创建向导**：TTS 模型 → 音色（级联过滤） → LLM 模型 → 人设
- **独立副本**：授权 = 创建副本，每人可自定义人设，互不影响
- **Pipeline 编辑**：Agent 详情页可直接修改音色、LLM 模型、TTS 模型
- 管理员可编辑任意用户的 Agent 人设

### 配置池（四个独立池）
| 池 | 表 | 说明 |
|----|-----|------|
| API Keys | api_keys | 底层 API Key 引用 |
| LLM 模型 | model_configs | Agent 可选，回退到数据库默认 |
| TTS 模型 | tts_configs | Agent 可选，回退到数据库默认 |
| 声音 | voices + voice_tts_links | 级联过滤 |

### 用户管理
- 用户列表 + 每人拥有的 Agent
- 授权/回收（Agent 页 + 详情页 + 用户页）
- 删除用户（级联删除 Agent）

### 部署
- Docker Compose 一键部署（2 个容器）
- API 和 Web Admin 同域名同端口
- `.env.example` 驱动首次种子配置
- 31 个单元测试

## 项目结构

```
call_me/
├── api/              FastAPI 后端 (16+ 端点, 31 测试)
├── agent/            LiveKit Agent Worker
├── app/              Flutter App (通话端)
├── web-admin/        Vue 3 Web 管理后台
├── docker-compose.yml
└── docs/
```

## .env 关键配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope | - |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（可选） | - |
| `LIVEKIT_URL` | LiveKit 服务器 | - |
| `LIVEKIT_API_KEY` | LiveKit API Key | - |
| `LIVEKIT_API_SECRET` | LiveKit API Secret | - |
| `STT_PROVIDER` / `STT_MODEL` | STT 全局配置 | `livekit` / `deepgram/nova-2` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理员 | `admin` / `admin` |
| `DEFAULT_LLM_MODEL` | 首次启动种子 LLM 模型 | `qwen-plus` |
| `SEED_BUILTIN_VOICES` | 内置音色列表 | `Cherry,Stella,Luna,Scott,Kevin` |

> 完整配置见 `.env.example`

## 开发命令

```bash
# API 测试
cd api && python3 -m pytest tests/ -v

# Vue 管理后台开发
cd web-admin && npm run dev

# Vue 管理后台构建
cd web-admin && npm run build

# Flutter App 测试
cd app && flutter test

# Flutter App 开发运行
cd app && flutter run -d chrome
```

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 注册 |
| `/api/auth/login` | POST | 登录 |
| `/api/agents` | POST | 创建 Agent（voice_pool_id + tts_config_id + model_config_id） |
| `/api/agents` | GET | 我的 Agent（admin 看根，用户看自己的） |
| `/api/agents/{id}` | GET/PATCH/DELETE | Agent CRUD |
| `/api/agents/{id}/grant` | POST | 授权（创建独立副本） |
| `/api/agents/{id}/grant/{user}` | DELETE | 回收 |
| `/api/admin/root-agents` | GET | 根机器人列表 |
| `/api/admin/agents` | GET | 所有 Agent |
| `/api/admin/agents/{id}/copies` | GET | 某机器人的副本 |
| `/api/admin/users` | GET/DELETE | 用户管理 |
| `/api/admin/users/{user}/agents` | GET | 某用户的 Agent |
| `/api/admin/model-configs` | CRUD | LLM 模型池 |
| `/api/admin/tts-configs` | CRUD | TTS 模型池 |
| `/api/admin/api-keys` | CRUD | API Key 池 |
| `/api/admin/voices` | CRUD | 声音库（上传音频 + 关联 TTS） |
| `/api/admin/voices/{id}/tts-configs` | GET/POST/DELETE | 音色-TTS 关联 |
| `/api/call/token` | POST | 通话 Token |
| `/api/health` | GET | 健康检查 |
