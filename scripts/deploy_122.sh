#!/usr/bin/env bash
set -euo pipefail

# ============ 部署到 192.168.2.122 ============
# 用法:
#   bash scripts/deploy_122.sh
#   SSHPASS=your_password bash scripts/deploy_122.sh
#
# 做什么:
#   1. 本地 build 前端
#   2. 备份远端 .env/state
#   3. rsync 同步代码到 122（排除运行时数据和本地依赖）
#   4. 在 122 上生成 JWT_SECRET（如果缺）
#   5. docker compose build + 重启
#   6. 等服务启动，健康检查

REMOTE_USER="${REMOTE_USER:-ab}"
REMOTE_HOST="${REMOTE_HOST:-192.168.2.122}"
REMOTE_DIR="${REMOTE_DIR:-/home/ab/cortex}"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)

ssh_remote() {
  if [ -n "${SSHPASS:-}" ] && command -v sshpass >/dev/null 2>&1; then
    sshpass -p "${SSHPASS}" ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "$@"
  else
    ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "$@"
  fi
}

rsync_remote() {
  local ssh_cmd="ssh -o StrictHostKeyChecking=accept-new"
  if [ -n "${SSHPASS:-}" ] && command -v sshpass >/dev/null 2>&1; then
    sshpass -p "${SSHPASS}" rsync -e "${ssh_cmd}" "$@"
  else
    rsync -e "${ssh_cmd}" "$@"
  fi
}

echo "================================================"
echo "听风部署到 ${REMOTE_HOST}"
echo "本地: ${LOCAL_DIR}"
echo "远端: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}"
echo "时间: $(date)"
echo "================================================"

# 1. 本地 build 前端
echo ""
echo "[1/6] Build 前端..."
cd "${LOCAL_DIR}/frontend"
npm run build
echo "✓ 前端 build 完成"

# 2. 备份远端
echo ""
echo "[2/6] 备份远端 .env/state..."
ssh_remote "set -euo pipefail
  mkdir -p '${REMOTE_DIR}'
  TS=\$(date +%Y%m%d_%H%M%S)
  BACKUP_DIR='${REMOTE_DIR}/backup/deploy_'\${TS}
  mkdir -p \"\${BACKUP_DIR}\"
  [ -f '${REMOTE_DIR}/.env' ] && cp '${REMOTE_DIR}/.env' \"\${BACKUP_DIR}/.env\" || true
  [ -d '${REMOTE_DIR}/state' ] && tar -C '${REMOTE_DIR}' -czf \"\${BACKUP_DIR}/state.tgz\" state || true
  echo \"  backup: \${BACKUP_DIR}\"
"
echo "✓ 远端备份完成"

# 3. rsync 同步
echo ""
echo "[3/6] 同步代码到 ${REMOTE_HOST}..."
cd "${LOCAL_DIR}"
rsync_remote -az --delete \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude 'data' \
  --exclude 'knowledge' \
  --exclude 'research' \
  --exclude 'state' \
  --exclude 'backup' \
  --exclude '.env' \
  ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"
echo "✓ 代码已同步"

# 4. 确保 JWT_SECRET 存在
echo ""
echo "[4/6] 检查 JWT_SECRET..."
ssh_remote "set -euo pipefail
  touch '${REMOTE_DIR}/.env'
  if ! grep -q '^JWT_SECRET=' '${REMOTE_DIR}/.env'; then
    SECRET=\$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)
    printf '\nJWT_SECRET=%s\n' \"\${SECRET}\" >> '${REMOTE_DIR}/.env'
    echo '  JWT_SECRET 已生成'
  else
    echo '  JWT_SECRET 已存在'
  fi
"
echo "✓ JWT_SECRET 已确认"

# 5. docker build + 重启
echo ""
echo "[5/6] Docker build + 重启..."
ssh_remote "cd '${REMOTE_DIR}' && docker compose down && docker compose build --no-cache && docker compose up -d"
echo "✓ Docker 已重启"

# 6. 健康检查
echo ""
echo "[6/6] 健康检查..."
sleep 5
STATUS="000"
for i in $(seq 1 10); do
  STATUS=$(ssh_remote "curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/health" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "✓ 服务已启动 (HTTP 200)"
    break
  fi
  echo "  等待启动... ($i/10)"
  sleep 3
done

if [ "$STATUS" != "200" ]; then
  echo "✗ 服务未正常启动，请检查日志："
  echo "  ssh ${REMOTE_USER}@${REMOTE_HOST} 'cd ${REMOTE_DIR} && docker compose logs --tail 50'"
  exit 1
fi

echo ""
echo "================================================"
echo "✓ 部署完成！"
echo ""
echo "访问: http://${REMOTE_HOST}:8080"
echo "管理员登录: 手机号 00000000000 / 验证码 0000"
echo "================================================"
