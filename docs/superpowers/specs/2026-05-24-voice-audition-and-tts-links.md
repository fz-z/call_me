# 音色试听 & 音色-TTS 关联编辑

> **Goal:** 管理员可在声音库页面试听任意音色，自由编辑试听文本，并可管理每个音色支持的 TTS 模型（多对多）。

**Architecture:** voices 表新增 audition_text 字段；新增试听 API（按 TTS provider 路由合成）；VoicePoolView 增加试听模态框和 TTS 关联编辑 UI。

**Tech Stack:** FastAPI + DashScope Qwen TTS (provider 可扩展) + Vue 3

---

## 功能

### 1. 音色试听

- voices 表新增 `audition_text` 列（TEXT，默认 `NULL`）
- PATCH `/api/admin/voices/{id}` 扩展支持 `audition_text` 字段
- 新增 `POST /api/admin/voices/{id}/audition`，请求体 `{text: string}`，返回 `{audio_base64: string, mime_type: string}`
  - 后端自动取音色第一个关联 TTS config 作为合成引擎
  - 按 tts_config.provider 路由到对应 TTS handler（当前实现 qwen，未来扩展火山等）
  - 音色未关联任何 TTS config 时返回 400
- 试听接口无需鉴权 TTS 厂商 API：后端从 DB 读取 TTS config 中的 api_key

**前端交互：**
- 声音库表格每行新增"试听"按钮
- 点击弹出模态框：
  - 文本输入框（预填 `voice.audition_text` 或默认中文试听句子，可自由编辑）
  - "试听"按钮 — 调 API → 拿到 base64 → 浏览器音频播放
  - 播放中按钮变为"停止" — 中断播放
- 音色编辑模态框新增 audition_text 字段

### 2. 音色-TTS 关联编辑

**后端已有**（`GET/POST/DELETE /api/admin/voices/{id}/tts-configs`），前端补 UI：

- 音色编辑模态框中新增"TTS 模型"区域
- 显示已关联的 TTS 模型列表，每项有删除按钮
- 下拉框列出未关联的 TTS 模型 + 添加按钮

---

## 数据模型变更

```sql
ALTER TABLE voices ADD COLUMN audition_text TEXT;
```

## API 变更

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/admin/voices/{id}/audition` | POST | 试听（body: `{text}` → `{audio_base64, mime_type}`） |
| `/api/admin/voices/{id}` | PATCH | 扩展支持 `audition_text` |

## Provider 路由

```
POST /voices/{id}/audition {text}
  → 查 voice → 查第一个关联 tts_config
  → provider="qwen" → _qwen_audition(tts_config, voice, text)
  → provider="volcano" → _volcano_audition(...)  # 未来扩展
  → 返回 {audio_base64, mime_type}
```

---

## 涉及文件

### 修改

- `api/database.py` — migration: ALTER TABLE voices ADD COLUMN audition_text
- `api/voices.py` — PATCH 扩展 audition_text；新增 audition 端点
- `api/models.py` — VoiceUpdate 新增 audition_text
- `web-admin/src/views/VoicePoolView.vue` — 试听模态框 + TTS 关联编辑 UI

### 新建

- (可选) `api/tts_audition.py` — 试听的 provider 路由逻辑（如逻辑简单可直接放在 voices.py）
