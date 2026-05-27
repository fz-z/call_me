# User Password Management Design

## Scope

Three features for the web admin panel:

1. **Create user** — admin creates new user accounts (role always `user`)
2. **Change admin password** — logged-in admin changes their own password
3. **Reset user password** — admin sets a new password for any user

All implemented as in-page modal dialogs on existing pages.

## API Changes

### New Pydantic Models (`api/models.py`)

```python
class AdminCreateUser(BaseModel):
    username: str
    password: str = "aB@12345"

class ChangePassword(BaseModel):
    old_password: str
    new_password: str

class AdminResetPassword(BaseModel):
    new_password: str = "aB@12345"
```

### New Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/admin/users` | admin | Create a new user (role=user). Returns `UserOut`. 409 if username exists. |
| PUT | `/api/auth/change-password` | login | Change own password. Validates old_password before update. 400 on wrong old password. |
| PUT | `/api/admin/users/{username}/reset-password` | admin | Set a new password for a user. 404 if user not found. |

### Error Responses

- `POST /api/admin/users` — 409 `{"detail": "用户名已存在"}`
- `PUT /api/auth/change-password` — 400 `{"detail": "旧密码错误"}`
- `PUT /api/admin/users/{username}/reset-password` — 404 `{"detail": "用户不存在"}`

## Frontend Changes

### UserListView.vue

- Add "+ 创建用户" button at top-right of the page (opens create user modal)
- Add "重置密码" link in each user row's actions column (opens reset password modal, hidden for the current admin user if desired)
- **Create user modal**: username input + password input (default `aB@12345`), confirm/cancel buttons, calls `POST /api/admin/users`
- **Reset password modal**: shows target username, new password input (default `aB@12345`), confirm/cancel buttons, calls `PUT /api/admin/users/{username}/reset-password`

### App.vue (or shared Layout)

- Add "修改密码" link next to the admin username in the header/nav area
- **Change password modal**: old password, new password, confirm new password inputs, confirm/cancel buttons, calls `PUT /api/auth/change-password`
- On success, display success message; on wrong old password, display error

### api.js

No changes needed — existing axios instance already handles token and 401 redirect.

## Validation & UX

- Change password: new password and confirm must match (frontend validation)
- All modals show loading state during API call, success toast on completion
- Create user: auto-refresh user list after creation
- Password fields: toggle visibility (eye icon) is nice-to-have but not required
- Reset password: modal closes and shows success toast on success

## Not In Scope

- Email-based password reset (no email field on users)
- Role selection on user creation (always `user`)
- User profile editing (username change, role change)
- Password complexity requirements beyond the default suggestion
