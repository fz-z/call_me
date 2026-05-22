# call_me

语音 AI 通话应用 —— 创建拥有复刻音色和个性化人设的 AI Agent，随时随地拨打通话。

## 功能

- **声音复刻**：上传一段音频样本，生成专属克隆音色
- **Agent 人格定制**：每个 Agent = 声音 + 性格（system prompt），想让它是什么人设就是什么人设
- **一键通话**：打开 App 选择 Agent，点击呼叫即可实时语音对话
- **SIP 电话接入**：绑定真实手机号，外部来电也能跟你的 Agent 通话
- **权限管理**：管理员可授权其他用户使用你的 Agent

## 快速开始

### 1. 准备环境

- 注册 [LiveKit Cloud](https://cloud.livekit.io/) 获取 API Key
- 注册 [阿里云 DashScope](https://dashscope.aliyun.com/) 获取 API Key

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
flutter run
```

首次启动需配置 Server URL 指向你的 API 地址。

## 使用流程

1. 打开 App → 注册/登录
2. 点击"创建 Agent" → 上传音频样本 → 起别名 → 写人设
3. 回到首页 → 选择刚创建的 Agent → 点击"开始通话"
4. 跟你的 AI Agent 实时语音对话

## 项目结构

```
call_me/
├── api/          FastAPI 后端（认证、Agent 管理、权限、通话 Token）
├── agent/        LiveKit Agent Worker（STT+LLM+TTS 语音管线）
├── app/          Flutter 移动端
└── docker-compose.yml
```

## 技术栈

| 层 | 选择 |
|----|------|
| 后端 API | Python / FastAPI |
| 数据库 | SQLite |
| Agent | Python / LiveKit Agents |
| 语音识别 (STT) | 通义 Qwen ASR / Deepgram |
| 大语言模型 (LLM) | 通义千问 / DeepSeek |
| 语音合成 (TTS) | 通义 Qwen TTS（含声音复刻）/ ElevenLabs |
| 实时通信 | LiveKit Cloud (WebRTC / SIP) |
| 移动端 | Flutter |
| 部署 | Docker Compose |

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

## 运行测试

```bash
cd api
pip install -e . pytest pytest-asyncio httpx
python3 -m pytest tests/ -v
# 31 passed
```
