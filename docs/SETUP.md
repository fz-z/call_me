# 环境搭建指南

## 1. 获取 API Keys

### LiveKit Cloud

1. 注册 [LiveKit Cloud](https://cloud.livekit.io/)
2. 创建一个 Project
3. 在 Project Settings → Keys 中获取：
   - `LIVEKIT_URL`（如 `wss://my-project.livekit.cloud`）
   - `LIVEKIT_API_KEY`（如 `APIxxxxxxxxxxxx`）
   - `LIVEKIT_API_SECRET`（如 `xxxxxxxxxxxxxxxxxxxx`）

### 阿里云 DashScope

1. 注册 [阿里云 DashScope](https://dashscope.aliyun.com/)
2. 开通以下服务（均为按量付费）：
   - 语音合成（TTS）— 用于 AI 说话
   - 语音识别（ASR）— 用于听用户说话
   - 大语言模型（LLM）— 用于 AI 思考和对话
   - 声音复刻（Voice Enrollment）— 用于克隆声音
3. 在 [API-KEY 管理](https://dashscope.aliyun.com/api-key) 中获取：
   - `DASHSCOPE_API_KEY`（如 `sk-xxxxxxxxxxxxxxxx`）

## 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入上一步获取的 keys：

```ini
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
LIVEKIT_URL=wss://my-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxx

# 管理员账号（首次启动自动创建）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-secure-password

# JWT 签名密钥（请改成随机字符串）
JWT_SECRET=your-random-secret-string

# Agent Worker 内部鉴权（与 API 共享）
WORKER_INTERNAL_SECRET=your-random-secret-string
```

配置逻辑：
- **首次启动**：`.env` 中的值自动写入数据库配置池
- **后续运行**：所有配置在 Web Admin 管理，修改 `.env` 不再影响运行
- Agent Worker 仅在数据库完全为空时回退到 `.env`

## 3. 部署

### Docker Compose

```bash
docker compose up -d
```

- Web Admin：`http://localhost:8000/admin/`
- Flutter App：`http://localhost:8000/app/`
- API 文档：`http://localhost:8000/docs`（Swagger UI）

### 生产环境

生产环境建议使用 nginx 反向代理 + HTTPS（Let's Encrypt），Docker Compose 示例见项目根目录。

## 4. 首次使用

1. 打开 Web Admin：`http://localhost:8000/admin/`
2. 用管理员账号登录（`admin` / 你在 `.env` 中设置的密码）
3. 配置池 → 添加 API Key → 创建 LLM 模型 → 创建 TTS 模型
4. 声音库 → 上传音频复刻声音（或使用内置音色）
5. 创建 Agent：选音色 → 选 LLM → 写人设 → 上传照片
6. 打开 App：`http://localhost:8000/app/` → 选 Agent → 开始通话

## 5. Flutter App

### 配置

App 自动检测部署域名（`Uri.base.origin`），无需手动配置 Server URL。

### 开发运行

```bash
cd app
flutter pub get
flutter run -d chrome    # Chrome 浏览器测试
```

### 生产构建

```bash
cd app
flutter build web --base-href /app/
# 产物在 build/web/，部署到服务器的 /opt/call_me/flutter-app/
```

## 常见问题

### 声音复刻如何获取好的音频样本？

- 时长 30 秒到 5 分钟
- 尽量清晰无背景噪音
- 单人说话，不要有其他人声
- 正常语速和音量

### 通电话没有声音？

- 检查 Agent 日志：`docker logs call_me-agent-1 --tail 50`
- VC 声音（克隆的）必须用 VC TTS 模型 `qwen3-tts-vc-realtime-2026-01-15`
- Flash 模型只能用内置声音
- 去 Web Admin → Agent 详情 → Pipeline 配置确认 TTS 模型和音色匹配

### Docker 部署后 Flutter App 连不上？

- 确认服务器防火墙已开放 80/443 端口
- 本地开发用 `http://localhost:8000/app/`

### 通话质量不好？

- 检查网络延迟（WebRTC 对网络质量敏感）
- 声音复刻的样本质量直接影响合成效果
- 可以尝试不同的 TTS 模型（在 Web Admin 中修改 Agent 的 Pipeline 配置）
