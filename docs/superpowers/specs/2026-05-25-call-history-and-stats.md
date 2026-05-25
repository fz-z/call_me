# 通话记录与统计

## 目标

记录每次通话的起止时间和时长，在 Web Admin 提供通话记录查询和数据统计看板。

## 架构

```
POST /api/call/token
  └── INSERT call_log (status=running, started_at=now)
        │
    LiveKit 通话中
        │
Agent Worker disconnect
  └── PATCH /api/admin/call-logs/{id}/end (status=completed, duration_seconds=X)
```

## 数据库

新增 `call_logs` 表（migration，database.py init_db 中创建）：

```sql
CREATE TABLE IF NOT EXISTS call_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    caller_user_id TEXT NOT NULL REFERENCES users(id),
    room_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    status TEXT NOT NULL DEFAULT 'running'
);
```

## API

### Token 端点改造（call.py）

`POST /api/call/token` — 现有逻辑不变，生成 Token 前 INSERT 一条 call_log。call_log_id 嵌入 agent_config 传给 Worker。

### Worker 回调端点（call.py 新增）

`PATCH /api/admin/call-logs/{call_log_id}/end` — Worker 断开时回调。无需认证（内部调用，Worker 无 JWT）。

请求体：
```json
{"status": "completed", "duration_seconds": 45}
```

### 查询端点（admin.py 新增）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/call-logs` | GET | 分页列表，支持 `?agent_id=&user_id=&status=&page=&page_size=` |
| `/api/admin/stats/overview` | GET | 总通话数、今日通话、总时长、活跃用户数 |
| `/api/admin/stats/trend` | GET | 最近 30 天每天通话数（`?days=30`） |
| `/api/admin/stats/top-agents` | GET | 热门 Agent TOP N（`?limit=10`） |
| `/api/admin/stats/top-users` | GET | 活跃用户 TOP N（`?limit=10`） |

所有 stats 端点 admin 认证。

### call_logs 列表返回格式

```json
{
  "items": [
    {
      "id": "...",
      "agent_alias": "温柔客服",
      "caller_username": "zhangsan",
      "agent_id": "...",
      "caller_user_id": "...",
      "started_at": "2026-05-25T10:30:00",
      "ended_at": "2026-05-25T10:33:15",
      "duration_seconds": 195,
      "status": "completed"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20
}
```

## Agent Worker（agent.py）

- agent_config 新增 `call_log_id` 字段
- room disconnect 时调用 `PATCH /api/admin/call-logs/{call_log_id}/end`，传入时长
- 回调失败只记 log，不影响其他逻辑
- `API_BASE_URL` 环境变量指向 API 内网地址（docker compose 中为 `http://api:8000`）
- docker-compose.yml agent 服务需新增环境变量 `API_BASE_URL=http://api:8000`

## 前端

### 新页面：通话记录（CallLogListView.vue）

- 路由：`/call-logs`
- 表格列：时间、主叫用户、Agent、时长、状态
- 筛选：按 Agent、按用户、按状态
- 分页

### 新页面：统计看板（StatsView.vue）

- 路由：`/stats`
- 顶部 4 张卡片：总通话数、今日通话、总时长（小时）、活跃用户数
- 折线图：最近 30 天通话趋势
- 柱状图：热门 Agent TOP 10
- 柱状图：活跃用户 TOP 10
- 使用 Chart.js（vue-chartjs）

### 导航

侧边栏增加"通话记录"和"数据统计"两个入口。

## Chart.js 依赖

```bash
cd web-admin && npm install chart.js vue-chartjs
```

## 实现任务概览

1. database.py — 新增 call_logs 迁移
2. models.py — 新增 CallLogEnd、CallLogOut、StatsOverview 等 schema
3. call.py — Token 端点写入 call_log + 回调端点
4. admin.py — call-logs 列表 + 4 个 stats 端点
5. agent.py — 读取 call_log_id，disconnect 回调
6. 前端：CallLogListView.vue + StatsView.vue + 路由 + 导航
7. API 测试
