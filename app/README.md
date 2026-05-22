# call_me Flutter App

语音 AI 通话的移动客户端。

## 运行

```bash
cd app
flutter pub get
flutter run                # 自动选择可用设备
flutter run -d chrome      # Chrome 浏览器预览
```

## 环境要求

- Flutter 3.38+（通过 `flutter --version` 检查）
- Android Studio（Android 构建）或 Xcode（iOS 构建）
- 后端 API 服务已在运行（默认 `http://10.0.2.2:8000`）

## 项目结构

```
app/lib/
├── main.dart                         App 入口
├── models/
│   └── agent.dart                    VoiceAgent + User 模型
├── services/
│   └── api_service.dart              API 通信层（Auth、Agent、Call、Admin）
└── screens/
    ├── login_screen.dart             登录/注册
    ├── home_screen.dart              首页（Agent 选择 + 一键通话）
    ├── call_screen.dart              通话中（LiveKit WebRTC）
    ├── agent_list_screen.dart         Agent 列表管理
    ├── agent_create_screen.dart      创建 Agent（上传音频 + 人设）
    └── settings_screen.dart          服务器配置 + SIP 绑定 + 登出
```

## 页面导航

```
LoginScreen ──(登录成功)──▶ HomeScreen
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
               CallScreen  AgentList  Settings
                              │
                              ▼
                         CreateAgent
```

## 配置

首次启动时需在 Settings 页面设置 Server URL：

- Android 模拟器：`http://10.0.2.2:8000`
- iOS 模拟器：`http://localhost:8000`
- 真机（同一网络）：`http://<服务器IP>:8000`
- 生产环境：`https://your-domain.com`
