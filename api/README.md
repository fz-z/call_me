# call_me API

FastAPI 后端，16 个端点。用户认证、Agent 管理、权限控制、通话 Token。同时 serve Web Admin 静态文件。

## 快速启动

```bash
pip install -e .
uvicorn main:app --reload
open http://localhost:8000/docs
```

## 运行测试

```bash
python3 -m pytest tests/ -v
# 31 tests
```

## 端点总览

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 注册（用户名校验：非空、>=2字符） |
| `/api/auth/login` | POST | 登录，返回 JWT |
| `/api/agents` | POST | 创建 Agent（上传音频→声音复刻） |
| `/api/agents` | GET | 列出我的 Agent（admin 只看根） |
| `/api/agents/{id}` | GET/PATCH/DELETE | Agent CRUD |
| `/api/agents/{id}/grant` | POST | 授权（创建独立副本，source_agent_id 指向根） |
| `/api/agents/{id}/grant/{user}` | DELETE | 回收（删除用户副本） |
| `/api/admin/root-agents` | GET | 根机器人列表（source_agent_id IS NULL） |
| `/api/admin/agents` | GET | 所有 Agent |
| `/api/admin/agents/{id}/copies` | GET | 某根机器人的所有副本 |
| `/api/admin/users` | GET | 用户列表 |
| `/api/admin/users` | DELETE | 删除用户及所有 Agent（不能删自己） |
| `/api/admin/users/{user}/agents` | GET | 某用户拥有的 Agent |
| `/api/call/token` | POST | 获取通话 Token（嵌入 agent_config） |
| `/api/health` | GET | 健康检查 |

## 数据模型

```sql
users (id, username, password_hash, role, created_at)
agents (id, alias, voice_id, system_prompt, owner_id, source_agent_id, created_at)
```

- `source_agent_id IS NULL` = 根机器人（原始创建）
- `source_agent_id = <root_id>` = 授权副本

## 权限模型

- 用户拥有自己的 Agent（包括创建的和被授权的副本）
- Admin 授权 = 创建独立副本，用户可自定义人设，互不影响
- 回收 = 删除用户副本
