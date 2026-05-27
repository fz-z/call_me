# 线上运维指南

## 服务器信息

- IP: 47.116.9.70
- 域名: callme.uno
- 项目路径: /opt/call_me
- SSH: `ssh root@47.116.9.70`

## 常用命令

### 查看服务状态
```bash
ssh root@47.116.9.70 'docker ps'
```

### 查看日志
```bash
# Agent 日志（打电话问题看这个）
ssh root@47.116.9.70 'docker logs call_me-agent-1 --tail 50'

# API 日志
ssh root@47.116.9.70 'docker logs call_me-api-1 --tail 50'
```

### 重启服务
```bash
# 重启所有
ssh root@47.116.9.70 'cd /opt/call_me && docker compose restart'

# 只重启 agent
ssh root@47.116.9.70 'cd /opt/call_me && docker compose restart agent'
```

### 更新代码
```bash
# 1. 先提交本地的修改
cd ~/Projects/call_me
git add -A && git commit -m "描述修改内容"
git push

# 2. 服务器拉取并重建
ssh root@47.116.9.70 'cd /opt/call_me && git pull && docker compose up -d --build'
```

### 证书续期
```bash
# 证书 90 天过期，certbot 自动续期，手动检查：
ssh root@47.116.9.70 'certbot renew --dry-run'
```
