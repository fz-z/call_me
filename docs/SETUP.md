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

# 声音复刻模型（默认 qwen3-tts-vc-realtime）
QWEN_TTS_MODEL=qwen3-tts-vc-realtime-2026-01-15

# 管理员账号（首次启动自动创建）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-secure-password

# JWT 签名密钥（请改成随机字符串）
JWT_SECRET=your-random-secret-string
```

## 3. 部署

### 方式一：Docker Compose（推荐）

```bash
docker compose up -d
```

- API 服务：`http://your-server:8000`
- API 文档：`http://your-server:8000/docs`（Swagger UI）
- Agent Worker：自动注册到 LiveKit Cloud

### 方式二：手动运行

**API 服务：**

```bash
cd api
# 安装依赖
pip install -e .
# 启动
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Agent Worker：**

```bash
cd agent
# 安装依赖
pip install -e .
# 先下载模型文件
python agent.py download-files
# 启动 Worker
python agent.py start
```

## 4. Flutter App

### 安装 Flutter SDK

```bash
# macOS
brew install --cask flutter

# 或手动下载：https://docs.flutter.dev/get-started/install
```

### 配置 App 连接

1. 在 App 的 Settings 页面中设置 Server URL（如 `http://your-server:8000`）
2. 如果是 Android 模拟器，使用 `http://10.0.2.2:8000`
3. 如果是 iOS 模拟器，使用 `http://localhost:8000`

### 运行

```bash
cd app
flutter pub get
flutter run              # 自动选择可用设备
flutter run -d chrome    # 或指定 Chrome 浏览器
```

## 5. 首次使用

1. 打开 App → 用管理员账号登录（`admin` / 你在 `.env` 中设置的密码）
2. 或注册一个新用户
3. 点击"创建 Agent" → 上传一段音频（30s~5min，wav/mp3/m4a）→ 起别名 → 写人设
4. 回到首页 → 选择刚创建的 Agent → 点击"开始通话"

## 常见问题

### 声音复刻如何获取好的音频样本？

- 时长 30 秒到 5 分钟
- 尽量清晰无背景噪音
- 单人说话，不要有其他人声
- 正常语速和音量

### Docker 部署后 Flutter App 连不上？

- 确认服务器防火墙已开放 8000 端口
- 检查 App 中 Server URL 是否正确
- 服务器和手机在同一个网络吗？（本地开发用内网 IP，生产用域名）

### 通话质量不好？

- 检查网络延迟（WebRTC 对网络质量敏感）
- 声音复刻的样本质量直接影响合成效果
- 可以尝试不同的 TTS 模型（在 `.env` 中修改 `QWEN_TTS_MODEL`）
