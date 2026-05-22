# call_me API

FastAPI 后端服务，提供用户认证、Agent 管理、权限控制、通话 Token 生成等 API。

## 快速启动

```bash
pip install -e .
uvicorn main:app --reload
```

访问 http://localhost:8000/docs 查看 Swagger API 文档。

## 运行测试

```bash
python3 -m pytest tests/ -v
# 31 tests
```

## 项目结构

```
api/
├── main.py              FastAPI 入口、路由注册、CORS
├── auth.py              用户注册/登录、JWT Token、权限依赖
├── agents.py            Agent CRUD（创建/列表/详情/更新/删除）
├── permissions.py       授权/撤销 Agent 访问（admin only）
├── admin.py             管理员面板（列出用户/Agent）
├── call.py              通话 Token 生成（嵌入 Agent 配置）
├── sip.py               SIP 手机号绑定（MVP 内存存储）
├── voice_enrollment.py  DashScope 声音复刻 API 封装
├── database.py          SQLite 连接、建表、Admin 初始化
├── models.py            Pydantic 请求/响应模型
├── tests/
│   ├── conftest.py      测试夹具
│   ├── test_database.py 数据库测试
│   ├── test_auth.py     认证测试
│   ├── test_agents.py   Agent CRUD 测试
│   └── test_permissions.py 权限/通话测试
├── Dockerfile
└── pyproject.toml
```

## 核心设计

### 认证

- 所有端点（除 register/login）需要 `Authorization: Bearer <JWT>` header
- JWT 包含 `sub`（user_id）、`username`、`role`、`iat`、`exp`（24h）
- `get_current_user` 依赖用于获取当前用户信息
- `require_admin` 依赖限制只有 admin 角色可以访问

### 权限模型

- Agent 创建者（owner）自动拥有该 Agent 的使用权
- Admin 可以通过 `/api/agents/{id}/grant` 授权任意 Agent 给任意用户
- 用户可用 Agent = 自己创建的 + 被授权的

### 通话 Token

`POST /api/call/token` 返回的 LiveKit Token 在 `attributes` 中嵌入了 Agent 配置：

```json
{
  "agent_id": "...",
  "alias": "温柔客服Cherry",
  "system_prompt": "你是一位温柔耐心的客服...",
  "voice_id": "voice_abc123"
}
```

Agent Worker 从参与者属性中读取这些配置，无需访问数据库。

### 声音复刻

`POST /api/agents` 接收音频文件后：
1. Base64 编码音频
2. 调用 DashScope `qwen-voice-enrollment` API
3. 返回 `voice_id`
4. 存入 agents 表的 `voice_id` 字段

## 数据库表结构

```sql
users (id, username, password_hash, role, created_at)
agents (id, alias, voice_id, system_prompt, owner_id, created_at)
permissions (agent_id, user_id, granted_by, created_at)
```
