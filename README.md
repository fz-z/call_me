# call_me

语音 AI 通话应用 —— 创建拥有复刻音色和个性化人设的 AI Agent，随时随地拨打通话。

## 架构

```
Flutter App ──── LiveKit Cloud ──── Agent Worker (STT+LLM+TTS)
     │                                      │
     │  /app  (Flutter)                     │ reads system_prompt, voice_id,
     │  /admin (Web Admin)                  │ model_config, tts_config
     │  /api   (REST)                       │ from token attrs
     ▼                                      ▼
  nginx (:443) ── api (FastAPI:8000) ──── DashScope API
                      │  SQLite
                      │  /data/photos (Agent 照片)
```

- **Flutter App**：手机浏览器打开即用，选 Agent → 一键通话
- **Web Admin**：管理员在浏览器管理 Agent、用户、权限、配置池
- **api**：FastAPI 后端、SQLite 持久化、静态文件 serve
- **agent**：LiveKit Agent Worker，STT→LLM→TTS 语音管线，主动挂断，对话记录

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
- **Agent 主动挂断**：LLM 工具调用识别告别意图，友好告别后挂机
- **静音超时**：用户 30 秒不说话 → Agent 询问"你还在吗" → 无回应挂断
- **对话记录**：通话结束后自动保存文字对话，管理后台可展开查看

### Agent 管理
- **4 步创建向导**：TTS 模型 → 音色（级联过滤） → LLM 模型 → 人设 + 照片
- **照片上传**：创建或编辑 Agent 时上传照片，头像显示在详情页
- **独立副本**：授权 = 创建副本，每人可自定义名字、人设、照片，互不影响
- **Pipeline 编辑**：Agent 详情页可直接修改音色、LLM 模型、TTS 模型、照片
- 管理员可编辑任意用户的 Agent（名字 + 人设 + 照片）

### 配置池（四个独立池）
| 池 | 表 | 说明 |
|----|-----|------|
| API Keys | api_keys | 底层 API Key 引用 |
| LLM 模型 | model_configs | Agent 可选，回退到数据库默认 |
| TTS 模型 | tts_configs | Agent 可选，回退到数据库默认 |
| 声音 | voices + voice_tts_links | 级联过滤 |

### 用户管理
- 用户列表 + 每人拥有的 Agent（含照片预览）
- 授权/回收（Agent 页 + 详情页 + 用户页）
- 删除用户（级联删除 Agent）
- 管理后台修改密码

### 部署
- Docker Compose 一键部署（2 个容器）
- nginx 反向代理 + Let's Encrypt HTTPS
- API、Web Admin、Flutter App 同域名同端口
- `.env.example` 驱动首次种子配置
- 31 个单元测试

## 项目结构

```
call_me/
├── api/              FastAPI 后端 (20+ 端点, 31 测试)
├── agent/            LiveKit Agent Worker
├── app/              Flutter App (通话端，Web 部署)
├── web-admin/        Vue 3 Web 管理后台
├── docker-compose.yml
├── OPS.md            运维手册（本地，gitignored）
└── docs/
    └── SETUP.md      环境搭建指南
```

## .env 关键配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope | - |
| `LIVEKIT_URL` | LiveKit 服务器 | - |
| `LIVEKIT_API_KEY` | LiveKit API Key | - |
| `LIVEKIT_API_SECRET` | LiveKit API Secret | - |
| `STT_PROVIDER` / `STT_MODEL` | STT 全局配置 | `livekit` / `deepgram/nova-2` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理员 | `admin` / `admin` |
| `JWT_SECRET` | JWT 签名密钥 | - |
| `WORKER_INTERNAL_SECRET` | Agent 内部调用鉴权 | 回退到 JWT_SECRET |

> 完整配置见 `.env.example`

## 开发命令

```bash
# API 测试
cd api && python3 -m pytest tests/ -v

# Vue 管理后台开发
cd web-admin && npm run dev

# Vue 管理后台构建
cd web-admin && npm run build

# Flutter App 开发运行
cd app && flutter run -d chrome
```

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 注册 |
| `/api/auth/login` | POST | 登录 |
| `/api/auth/change-password` | POST | 修改密码 |
| `/api/agents` | POST | 创建 Agent（含 photo_url） |
| `/api/agents` | GET | 我的 Agent |
| `/api/agents/{id}` | GET/PATCH/DELETE | Agent CRUD（含照片） |
| `/api/agents/{id}/grant` | POST | 授权（创建独立副本） |
| `/api/agents/{id}/grant/{user}` | DELETE | 回收 |
| `/api/admin/upload` | POST | 上传照片（multipart/form-data） |
| `/api/admin/root-agents` | GET | 根机器人列表 |
| `/api/admin/agents` | GET | 所有 Agent |
| `/api/admin/agents/{id}/copies` | GET | 某机器人的副本 |
| `/api/admin/users` | GET/DELETE | 用户管理 |
| `/api/admin/users/{user}/agents` | GET | 某用户的 Agent |
| `/api/admin/model-configs` | CRUD | LLM 模型池 |
| `/api/admin/tts-configs` | CRUD | TTS 模型池 |
| `/api/admin/api-keys` | CRUD | API Key 池 |
| `/api/admin/voices` | CRUD | 声音库 |
| `/api/admin/voices/{id}/tts-configs` | GET/POST/DELETE | 音色-TTS 关联 |
| `/api/admin/call-logs` | GET | 通话记录（含对话文字） |
| `/api/admin/stats` | GET | 通话统计 |
| `/api/call/token` | POST | 通话 Token（嵌入模型配置） |
| `/api/call/admin/call-logs/{id}/end` | PATCH | Worker 回调结束通话 |
| `/api/health` | GET | 健康检查 |
