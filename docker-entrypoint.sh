#!/bin/sh
set -e

# /data 卷可能由旧版本镜像以 root 创建，先统一归属再降权运行
chown -R appuser:appuser /data

exec setpriv --reuid appuser --regid appuser --init-groups "$@"
