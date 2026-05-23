# call_me API

FastAPI 后端。用户认证、Agent 管理、配置池管理、权限控制、通话 Token。

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

## 配置管理

**首次启动**：`.env` 中的 API Key 和种子配置初始化到数据库。  
**后续运行**：所有配置通过 Web Admin 修改，重启不覆盖。

Token 生成时，若 Agent 未配置模型/TTS，自动嵌入数据库中第一个可用配置，确保 Worker 始终拿到有效配置。

## 配置池

| 表 | 管理入口 | Agent 可选 |
|----|---------|-----------|
| `api_keys` | `POST /api/admin/api-keys` | 底层引用 |
| `model_configs` | `POST /api/admin/model-configs` | model_config_id |
| `tts_configs` | `POST /api/admin/tts-configs` | tts_config_id |
| `voices` | `POST /api/admin/voices` | voice_pool_id |
| `voice_tts_links` | `POST /api/admin/voices/{id}/tts-configs` | 多对多关联 |

## 端点总览

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 注册 |
| `/api/auth/login` | POST | 登录 |
| `/api/agents` | POST | 创建 Agent（JSON：voice_pool_id + tts_config_id + model_config_id） |
| `/api/agents` | GET | 我的 Agent |
| `/api/agents/{id}` | GET/PATCH/DELETE | Agent CRUD（admin 可修改任意 agent） |
| `/api/agents/{id}/grant` | POST/DELETE | 授权/回收 |
| `/api/admin/root-agents` | GET | 根机器人 |
| `/api/admin/agents` | GET | 所有 Agent |
| `/api/admin/agents/{id}/copies` | GET | 副本列表 |
| `/api/admin/users` | GET/DELETE | 用户管理 |
| `/api/admin/users/{user}/agents` | GET | 某用户的 Agent |
| `/api/admin/model-configs` | CRUD | LLM 模型池 |
| `/api/admin/tts-configs` | CRUD | TTS 模型池 |
| `/api/admin/api-keys` | CRUD | API Key 池 |
| `/api/admin/voices` | CRUD | 声音库 |
| `/api/admin/voices/{id}/tts-configs` | GET/POST/DELETE | 音色-TTS 关联 |
| `/api/admin/voices?tts_config_id=X` | GET | 按 TTS 过滤音色 |
| `/api/call/token` | POST | 通话 Token（始终嵌入有效 model_config + tts_config） |
| `/api/health` | GET | 健康检查 |

## 数据模型

```sql
users (id, username, password_hash, role, created_at)
agents (id, alias, voice_id, voice_pool_id, system_prompt, owner_id,
        source_agent_id, model_config_id, tts_config_id, created_at)
api_keys (id, name, provider, api_key, created_at)
model_configs (id, name, provider, model, api_key_id, temperature, max_tokens, created_at)
tts_configs (id, name, provider, model, api_key_id, created_at)
voices (id, name, voice_id, type, created_at)
voice_tts_links (voice_id, tts_config_id)
```

## 权限模型

- 用户拥有自己的 Agent（创建 + 被授权副本）
- Admin 授权 = 创建独立副本（含 voice_pool_id + tts_config_id + model_config_id）
- Admin 可编辑任意用户的 Agent 人设和 Pipeline 配置
- 回收 = 删除副本
