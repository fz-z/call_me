# call_me Flutter App

语音 AI 通话客户端。管理功能已移至 Web Admin。

## 运行

```bash
flutter pub get
flutter run -d chrome
flutter run          # 模拟器/真机
```

## 功能

- 登录/注册
- 选择 Agent → 一键通话
- 编辑自己 Agent 的人设
- 服务器地址配置 + 登出

## 页面

```
Login → Home (Agent 下拉 + 通话) → Call (WebRTC)
              ├── Agent List (查看 + 编辑人设)
              └── Settings (服务器地址 + 登出)
```

> Agent 创建、删除、授权等管理功能请使用 Web Admin：`http://localhost:8000/admin/`
