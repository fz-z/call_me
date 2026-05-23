# Web Admin Panel Design Spec

## Overview

A Vue 3 web admin panel for managing Agents, users, and permissions. Replaces the Flutter Admin Panel with a proper desktop web interface. Embedded in the existing Docker Compose deployment.

**End state:** Admin opens browser → logs in → manages agents/users/permissions from a clean web UI.

## Goals

- **Agent management**: List root agents, create (audio upload + alias + prompt), edit, delete
- **Authorization**: Grant any root agent to any user (creates independent copy), revoke access
- **User overview**: See all users, which agents each has, revoke from user view
- **Agent detail**: See all copies of a root agent, each user's custom prompt
- **Root vs Copy**: Distinguish original agents from per-user copies

## Non-goals (Phase 1)

- Call history, usage statistics (Phase B)
- Worker monitoring, real-time call view (Phase C)
- Non-admin access (only admin can log into web admin)

## Data Model Change

Add `source_agent_id` column to agents table:

```sql
ALTER TABLE agents ADD COLUMN source_agent_id TEXT REFERENCES agents(id);
```

- `source_agent_id IS NULL` → root agent (originally created by upload)
- `source_agent_id = <root_id>` → copy created by grant, linked to root

Backward compatible: existing agents get `source_agent_id = NULL` (treated as root).

## Architecture

```
Browser (Vue 3 + Vite SPA)
    │  REST API calls (JWT Bearer)
    ▼
api container (FastAPI :8000)
    │  existing endpoints + new admin endpoints
    ▼
SQLite (agents table with source_agent_id)
```

- Vue SPA served as static files from the `api` container (same origin, no CORS)
- All business logic in existing API endpoints
- New API endpoints for admin views (root agents, agent copies)

## New/Modified API Endpoints

```
GET  /api/admin/root-agents          → list all root agents (source_agent_id IS NULL) with authorized users
GET  /api/admin/agents/{id}/copies   → list all copies of a root agent (source_agent_id = id) with owner info
GET  /api/admin/users/{username}/agents  → list agents owned by a user (already exists, ensure it works)
POST /api/agents/{id}/grant          → create copy for user (already exists, add source_agent_id)
DELETE /api/agents/{id}/grant/{username} → delete user's copy (already exists)
DELETE /api/admin/users/{username}   → delete user and all their agents (admin only, cannot delete self)
```

Modify existing grant endpoint to set `source_agent_id` on the copy.

## Vue App Structure

```
web-admin/
├── index.html
├── package.json
├── vite.config.js
├── src/
│   ├── main.js
│   ├── App.vue              Layout: sidebar + router-view
│   ├── router.js
│   ├── api.js               Axios client with JWT interceptor
│   ├── views/
│   │   ├── LoginView.vue
│   │   ├── AgentListView.vue       Root agents table + grant/revoke
│   │   ├── AgentDetailView.vue     Copies list for one root agent
│   │   ├── UserListView.vue        Users table + agent tags + revoke
│   │   └── UserDetailView.vue      One user's agents with prompts
│   └── components/
│       ├── AgentForm.vue            Create/edit agent modal
│       ├── GrantDialog.vue          Grant agent to user modal
│       └── ConfirmDialog.vue        Delete/revoke confirmation
```

## Pages

### 1. Login
- Username + password form
- Calls POST /api/auth/login
- Only allows users with role=admin
- Stores JWT in localStorage
- Auto-redirect to Agent List on success

### 2. Agent List (default page)
- Table: alias, voice, owner, authorized users (tags), actions
- "Create Agent" button → AgentForm modal (file upload + alias + prompt)
- Each authorized user shown as tag with ✕ → click revokes
- "Grant" button → GrantDialog → input username → creates copy
- "Detail" link → AgentDetailView
- "Edit" → AgentForm modal pre-filled
- "Delete" → ConfirmDialog → deletes root agent and all copies

### 3. Agent Detail
- Header: root agent info (alias, voice, prompt)
- "← Back" link
- Table: authorized user, custom prompt, granted date, revoke button
- "Grant to new user" button at top

### 4. User List
- Table: username, role, agents (tags with ✕), registered date, actions
- Each agent tag on ✕ → revoke
- "View Detail" → UserDetailView
- "Delete" → ConfirmDialog → deletes user and all their agents (cannot delete self)

### 5. User Detail
- Header: username, role
- List of user's agents with alias, voice, custom prompt
- Revoke button per agent

## Auth Flow

- Login → JWT stored in localStorage → all requests include Authorization header
- 401 response → clear token → redirect to login
- Non-admin role → "Access denied" page

## Deployment

- `npm run build` produces static files in `web-admin/dist/`
- api Dockerfile copies dist/ and mounts as static files
- FastAPI serves `/admin` → `web-admin/dist/index.html`
- Vue router uses hash mode for SPA routing

Update `api/Dockerfile`:
```dockerfile
COPY web-admin/dist/ /app/static/
```

Update `api/main.py`:
```python
from fastapi.staticfiles import StaticFiles
app.mount("/admin", StaticFiles(directory="/app/static", html=True), name="admin")
```

Access at `http://localhost:8000/admin`.

## Tech Stack

| Layer | Choice |
|-------|--------|
| Framework | Vue 3 (Composition API) |
| Build | Vite |
| UI | Plain CSS or minimal component library |
| HTTP | Axios |
| Router | Vue Router (hash mode) |
| Deployment | Static files served by FastAPI |
