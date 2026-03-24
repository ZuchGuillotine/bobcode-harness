#!/usr/bin/env bash
# =============================================================================
# Agent Harness VPS Setup Script
# Target: Hetzner VPS, Ubuntu 24.04 LTS
# Usage:  sudo bash scripts/setup.sh
# =============================================================================

set -euo pipefail

# -- Configuration -----------------------------------------------------------
HARNESS_USER="harness"
HARNESS_DIR="/opt/agent-harness"
PYTHON_VERSION="3.12"
NODE_VERSION="20"
PHOENIX_PORT=6006
ORCHESTRATOR_PORT=8080
NGINX_DOMAIN="_"  # Set to your domain for production

# -- Colors ------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

# -- Preflight ---------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  err "This script must be run as root (use sudo)."
fi

echo "============================================================================="
echo "  Agent Harness VPS Setup"
echo "  Target: ${HARNESS_DIR}"
echo "  OS:     $(lsb_release -ds 2>/dev/null || cat /etc/os-release | head -1)"
echo "============================================================================="
echo ""

# -- Step 1: System Packages -------------------------------------------------
log "[1/8] Updating and installing system packages..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
  build-essential \
  curl \
  wget \
  git \
  tmux \
  htop \
  jq \
  unzip \
  sqlite3 \
  software-properties-common \
  apt-transport-https \
  ca-certificates \
  gnupg \
  lsb-release \
  nginx \
  certbot \
  python3-certbot-nginx \
  libssl-dev \
  libffi-dev

# -- Step 2: Python 3.11+ ----------------------------------------------------
log "[2/8] Installing Python ${PYTHON_VERSION}..."
apt-get install -y -qq \
  "python${PYTHON_VERSION}" \
  "python${PYTHON_VERSION}-venv" \
  "python${PYTHON_VERSION}-dev" \
  2>/dev/null || {
    # Ubuntu 24.04 may ship with 3.12 natively
    log "Using system Python 3: $(python3 --version)"
    PYTHON_VERSION="3"
  }

# Verify Python is available
PYTHON_BIN="python${PYTHON_VERSION}"
if ! command -v "${PYTHON_BIN}" &>/dev/null; then
  PYTHON_BIN="python3"
fi
log "Python binary: ${PYTHON_BIN} ($(${PYTHON_BIN} --version))"

# -- Step 3: Node.js (for promptfoo) -----------------------------------------
log "[3/8] Installing Node.js ${NODE_VERSION}.x..."
if ! command -v node &>/dev/null; then
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_VERSION}.x" | bash -
  apt-get install -y -qq nodejs
fi
log "Node.js $(node --version) installed."
log "npm $(npm --version) installed."

# Install promptfoo globally
log "Installing promptfoo..."
npm install -g promptfoo 2>/dev/null || warn "promptfoo install failed; install manually: npm install -g promptfoo"

# -- Step 4: Create Harness User ---------------------------------------------
log "[4/8] Creating harness user..."
if id "${HARNESS_USER}" &>/dev/null; then
  warn "User '${HARNESS_USER}' already exists, skipping creation."
else
  useradd --system --create-home --shell /bin/bash "${HARNESS_USER}"
  log "User '${HARNESS_USER}' created."
fi

# -- Step 5: Directory Structure ----------------------------------------------
log "[5/8] Creating directory structure under ${HARNESS_DIR}..."
mkdir -p "${HARNESS_DIR}"/{bin,apps,config,logs,tmp,secrets}
mkdir -p "${HARNESS_DIR}/data"/{sqlite,kuzu,traces,worktrees}
mkdir -p "${HARNESS_DIR}/skills"/{code,marketing}
mkdir -p "${HARNESS_DIR}/prompts"/{planner,worker,reviewer,brand}
mkdir -p "${HARNESS_DIR}/evals"/{regressions,adversarial,goldens,marketing}
mkdir -p "${HARNESS_DIR}/logs"/{orchestrator,workers,phoenix}

chown -R "${HARNESS_USER}:${HARNESS_USER}" "${HARNESS_DIR}"
chmod 700 "${HARNESS_DIR}/secrets"

log "Directory structure created."

# -- Step 6: Python Venv and Dependencies ------------------------------------
log "[6/8] Setting up Python virtual environment..."
sudo -u "${HARNESS_USER}" "${PYTHON_BIN}" -m venv "${HARNESS_DIR}/.venv"
sudo -u "${HARNESS_USER}" "${HARNESS_DIR}/.venv/bin/pip" install --upgrade pip setuptools wheel -q

# Create requirements file if not present in harness dir
if [[ ! -f "${HARNESS_DIR}/requirements.txt" ]]; then
  cat > "${HARNESS_DIR}/requirements.txt" << 'REQUIREMENTS'
# Agent Harness Requirements
anthropic>=0.40.0
openai>=1.50.0
litellm>=1.50.0
pydantic>=2.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
httpx>=0.27.0
python-dotenv>=1.0
structlog>=24.0
rich>=13.0
click>=8.0
gitpython>=3.1
pyyaml>=6.0
jinja2>=3.1
arize-phoenix>=5.0
opentelemetry-api>=1.20
opentelemetry-sdk>=1.20
opentelemetry-exporter-otlp>=1.20
openinference-instrumentation-openai>=0.1
openinference-instrumentation-anthropic>=0.1
python-telegram-bot>=21.0
redis>=5.0
celery>=5.4
kuzu>=0.5
aiosqlite>=0.20
pytest>=8.0
ruff>=0.6.0
REQUIREMENTS
  chown "${HARNESS_USER}:${HARNESS_USER}" "${HARNESS_DIR}/requirements.txt"
fi

log "Installing Python requirements (this may take a few minutes)..."
sudo -u "${HARNESS_USER}" "${HARNESS_DIR}/.venv/bin/pip" install \
  -r "${HARNESS_DIR}/requirements.txt" -q 2>&1 | tail -5 || \
  warn "Some packages failed to install. Review ${HARNESS_DIR}/requirements.txt"

# -- Step 7: Systemd Services ------------------------------------------------
log "[7/8] Installing systemd services..."

# Orchestrator service
cat > /etc/systemd/system/harness-orchestrator.service << EOF
[Unit]
Description=Agent Harness Orchestrator
After=network.target redis.service
Wants=redis.service

[Service]
Type=simple
User=${HARNESS_USER}
Group=${HARNESS_USER}
WorkingDirectory=${HARNESS_DIR}
ExecStart=${HARNESS_DIR}/.venv/bin/python -m apps.orchestrator.main
Restart=on-failure
RestartSec=5
Environment=HARNESS_CONFIG=${HARNESS_DIR}/config
Environment=HARNESS_DATA=${HARNESS_DIR}/data
Environment=LITELLM_LOG_LEVEL=WARNING
EnvironmentFile=-${HARNESS_DIR}/secrets/.env

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${HARNESS_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Phoenix observability service
cat > /etc/systemd/system/harness-phoenix.service << EOF
[Unit]
Description=Phoenix Observability Server (Arize)
After=network.target

[Service]
Type=simple
User=${HARNESS_USER}
Group=${HARNESS_USER}
WorkingDirectory=${HARNESS_DIR}
ExecStart=${HARNESS_DIR}/.venv/bin/python -m phoenix.server.main serve --port ${PHOENIX_PORT}
Restart=on-failure
RestartSec=5
Environment=PHOENIX_PORT=${PHOENIX_PORT}
Environment=PHOENIX_WORKING_DIR=${HARNESS_DIR}/data/traces

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${HARNESS_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Telegram bot service
cat > /etc/systemd/system/harness-telegram.service << EOF
[Unit]
Description=Agent Harness Telegram Bot
After=network.target harness-orchestrator.service
Wants=harness-orchestrator.service

[Service]
Type=simple
User=${HARNESS_USER}
Group=${HARNESS_USER}
WorkingDirectory=${HARNESS_DIR}
ExecStart=${HARNESS_DIR}/.venv/bin/python -m packages.notifications.telegram_bot
Restart=on-failure
RestartSec=5
Environment=HARNESS_CONFIG=${HARNESS_DIR}/config
EnvironmentFile=-${HARNESS_DIR}/secrets/.env

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${HARNESS_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
log "Systemd services created (not started -- configure secrets first)."

# -- Step 8: Nginx Reverse Proxy ---------------------------------------------
log "[8/8] Configuring nginx reverse proxy..."

cat > /etc/nginx/sites-available/harness << 'EOF'
server {
    listen 80;
    server_name _;

    # Phoenix UI
    location /phoenix/ {
        proxy_pass http://127.0.0.1:6006/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
        auth_basic "Phoenix Observability";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }

    # Harness API
    location /api/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        auth_basic "Harness API";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }

    # Health check (no auth)
    location /health {
        proxy_pass http://127.0.0.1:8080/health;
        access_log off;
    }
}
EOF

ln -sf /etc/nginx/sites-available/harness /etc/nginx/sites-enabled/harness
rm -f /etc/nginx/sites-enabled/default

# Create basic auth with default password (user must change)
echo "harness:$(openssl passwd -apr1 'changeme')" > /etc/nginx/.htpasswd

nginx -t && systemctl reload nginx
log "Nginx configured."

# -- Create .env Template ----------------------------------------------------
if [[ ! -f "${HARNESS_DIR}/secrets/.env" ]]; then
  cat > "${HARNESS_DIR}/secrets/.env" << 'ENVFILE'
# Agent Harness Environment Configuration
# Fill in these values before starting services.

# LLM API Keys
ANTHROPIC_API_KEY=sk-ant-xxxxx
OPENAI_API_KEY=sk-xxxxx

# Telegram Bot
TELEGRAM_BOT_TOKEN=123456:ABC-xxxxx
TELEGRAM_ALLOWED_USERS=comma,separated,usernames

# Redis (for task queue)
REDIS_URL=redis://localhost:6379/0

# Phoenix Observability
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006

# Google Ads (marketing skills)
GOOGLE_ADS_DEVELOPER_TOKEN=xxxxx
GOOGLE_ADS_CLIENT_ID=xxxxx
GOOGLE_ADS_CLIENT_SECRET=xxxxx
GOOGLE_ADS_REFRESH_TOKEN=xxxxx
GOOGLE_ADS_CUSTOMER_ID=xxxxx

# General
LOG_LEVEL=INFO
ENVIRONMENT=production
ENVFILE
  chmod 600 "${HARNESS_DIR}/secrets/.env"
  chown "${HARNESS_USER}:${HARNESS_USER}" "${HARNESS_DIR}/secrets/.env"
  log "Template .env created at ${HARNESS_DIR}/secrets/.env"
fi

# -- Setup Summary -----------------------------------------------------------
echo ""
echo "============================================================================="
echo -e "${GREEN}  Agent Harness Setup Complete${NC}"
echo "============================================================================="
echo ""
echo "  Directory:        ${HARNESS_DIR}"
echo "  User:             ${HARNESS_USER}"
echo "  Python venv:      ${HARNESS_DIR}/.venv"
echo "  Phoenix port:     ${PHOENIX_PORT}"
echo "  Nginx proxy:      http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<server-ip>')/"
echo ""
echo "  Systemd services:"
echo "    - harness-orchestrator.service"
echo "    - harness-phoenix.service"
echo "    - harness-telegram.service"
echo ""
echo "  Directory layout:"
echo "    ${HARNESS_DIR}/"
echo "    ├── apps/            # Application code"
echo "    ├── bin/             # CLI scripts"
echo "    ├── config/          # Configuration files"
echo "    ├── data/"
echo "    │   ├── kuzu/        # Graph database"
echo "    │   ├── sqlite/      # SQLite databases"
echo "    │   ├── traces/      # Phoenix trace storage"
echo "    │   └── worktrees/   # Isolated git worktrees"
echo "    ├── evals/           # Promptfoo eval configs"
echo "    ├── logs/            # Service logs"
echo "    ├── prompts/         # Agent role prompts"
echo "    ├── secrets/         # API keys and credentials (mode 700)"
echo "    ├── skills/          # Skill definitions"
echo "    └── .venv/           # Python virtual environment"
echo ""
echo "  Next steps:"
echo "    1. Edit secrets:      nano ${HARNESS_DIR}/secrets/.env"
echo "    2. Change nginx pw:   htpasswd /etc/nginx/.htpasswd harness"
echo "    3. Copy project files: cp -r skills/ prompts/ evals/ ${HARNESS_DIR}/"
echo "    4. Start services:"
echo "         systemctl enable --now harness-phoenix"
echo "         systemctl enable --now harness-orchestrator"
echo "         systemctl enable --now harness-telegram"
echo "    5. Verify Phoenix:    curl http://localhost:${PHOENIX_PORT}"
echo "    6. (Optional) TLS:    certbot --nginx -d your-domain.com"
echo ""
echo "  Firewall rules (Hetzner):"
echo "    Allow inbound: 22 (SSH), 80 (HTTP), 443 (HTTPS)"
echo "    Block all other inbound ports."
echo ""
echo "============================================================================="
