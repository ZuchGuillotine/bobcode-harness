#!/usr/bin/env bash
# =============================================================================
# Agent Harness Deployment Script
# Rsyncs code to VPS, installs deps, restarts services, runs health checks.
#
# Usage:
#   bash scripts/deploy.sh                   # Full deploy
#   bash scripts/deploy.sh --skip-deps       # Skip pip install on VPS
#   bash scripts/deploy.sh --restart-phoenix # Also restart Phoenix service
#
# Make executable: chmod +x scripts/deploy.sh
# =============================================================================

set -euo pipefail

# -- Configuration -----------------------------------------------------------
VPS_HOST="${HARNESS_VPS_HOST:-your-server-ip}"
VPS_USER="root"
REMOTE_DIR="/opt/agent-harness"
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

# -- Flags -------------------------------------------------------------------
SKIP_DEPS=false
RESTART_PHOENIX=false

for arg in "$@"; do
    case "$arg" in
        --skip-deps)       SKIP_DEPS=true ;;
        --restart-phoenix) RESTART_PHOENIX=true ;;
        --help|-h)
            echo "Usage: $0 [--skip-deps] [--restart-phoenix]"
            echo ""
            echo "Options:"
            echo "  --skip-deps        Skip pip install on VPS"
            echo "  --restart-phoenix  Also restart the Phoenix tracing service"
            exit 0
            ;;
        *)
            echo "Unknown flag: $arg (use --help for usage)"
            exit 1
            ;;
    esac
done

# -- Colors ------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[*]${NC} $1"; }

# -- Preflight ---------------------------------------------------------------
echo "============================================================================="
echo "  Agent Harness Deploy"
echo "  Target: ${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}"
echo "  Skip deps: ${SKIP_DEPS}"
echo "  Restart Phoenix: ${RESTART_PHOENIX}"
echo "============================================================================="
echo ""

# Verify SSH connectivity
info "Testing SSH connection..."
if ! ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" "echo ok" &>/dev/null; then
    err "Cannot reach ${VPS_USER}@${VPS_HOST} via SSH. Check your connection and keys."
fi
log "SSH connection verified."

# -- Step 1: Rsync code to VPS -----------------------------------------------
log "[1/4] Syncing code to VPS..."

rsync -azP --delete \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='secrets/' \
    --exclude='*.db' \
    --exclude='data/' \
    --exclude='.harness/' \
    --exclude='.venv/' \
    --exclude='node_modules/' \
    --exclude='.mypy_cache/' \
    --exclude='.pytest_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='*.egg-info/' \
    -e "ssh ${SSH_OPTS}" \
    ./ "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/"

log "Code synced successfully."

# -- Step 2: Install dependencies (optional) ---------------------------------
if [ "${SKIP_DEPS}" = false ]; then
    log "[2/4] Installing Python dependencies on VPS..."
    ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<'REMOTE_DEPS'
        set -euo pipefail
        cd /opt/agent-harness

        if [ -f .venv/bin/pip ]; then
            .venv/bin/pip install -r requirements.txt -q 2>&1 | tail -5
            echo "Dependencies installed."
        else
            echo "WARNING: No virtualenv found at .venv/. Run scripts/setup.sh first."
            exit 1
        fi
REMOTE_DEPS
    log "Dependencies installed on VPS."
else
    warn "[2/4] Skipping dependency installation (--skip-deps)."
fi

# -- Step 3: Restart services ------------------------------------------------
log "[3/4] Restarting services..."

SERVICES_TO_RESTART="harness-orchestrator harness-telegram"
if [ "${RESTART_PHOENIX}" = true ]; then
    SERVICES_TO_RESTART="${SERVICES_TO_RESTART} harness-phoenix"
fi

ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<REMOTE_RESTART
    set -euo pipefail
    systemctl daemon-reload

    for svc in ${SERVICES_TO_RESTART}; do
        if systemctl is-enabled "\${svc}" &>/dev/null; then
            systemctl restart "\${svc}"
            echo "Restarted \${svc}"
        else
            echo "WARNING: \${svc} is not enabled. Enable with: systemctl enable --now \${svc}"
        fi
    done
REMOTE_RESTART

log "Services restarted: ${SERVICES_TO_RESTART}"

# -- Step 4: Health checks ---------------------------------------------------
log "[4/4] Running health checks..."

HEALTH_OK=true

# Check Phoenix is responding (only if we manage it)
info "Checking Phoenix (port 6006)..."
PHOENIX_STATUS=$(ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost:6006/ --max-time 5 2>/dev/null || echo '000'")

if [ "${PHOENIX_STATUS}" = "200" ] || [ "${PHOENIX_STATUS}" = "302" ]; then
    log "Phoenix is healthy (HTTP ${PHOENIX_STATUS})."
else
    warn "Phoenix returned HTTP ${PHOENIX_STATUS} (may still be starting up)."
    HEALTH_OK=false
fi

# Check systemd service statuses
info "Checking service statuses..."
ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<'REMOTE_HEALTH'
    for svc in harness-orchestrator harness-telegram harness-phoenix; do
        status=$(systemctl is-active "${svc}" 2>/dev/null || echo "unknown")
        echo "  ${svc}: ${status}"
    done
REMOTE_HEALTH

# -- Summary -----------------------------------------------------------------
echo ""
echo "============================================================================="
if [ "${HEALTH_OK}" = true ]; then
    echo -e "  ${GREEN}Deployment complete.${NC}"
else
    echo -e "  ${YELLOW}Deployment complete with warnings.${NC}"
fi
echo "============================================================================="
echo ""
echo "  Host:     ${VPS_USER}@${VPS_HOST}"
echo "  Path:     ${REMOTE_DIR}"
echo "  Phoenix:  http://${VPS_HOST}:6006 (via nginx: http://${VPS_HOST}/phoenix/)"
echo ""
echo "  Useful commands:"
echo "    ssh ${VPS_USER}@${VPS_HOST} journalctl -u harness-orchestrator -f"
echo "    ssh ${VPS_USER}@${VPS_HOST} systemctl status harness-orchestrator"
echo ""
echo "============================================================================="
