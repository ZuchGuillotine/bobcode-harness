#!/usr/bin/env bash
# =============================================================================
# Agent Harness VPS Backup Script
# Backs up SQLite, KuzuDB, traces, config, and secrets from the VPS.
#
# Usage:
#   bash scripts/backup.sh                  # Backup to /tmp on VPS
#   bash scripts/backup.sh --sync-local     # Also rsync tarball to local machine
#   bash scripts/backup.sh --include-traces # Include traces dir (can be large)
#   bash scripts/backup.sh --local-dir ./backups  # Local destination for sync
#
# Make executable: chmod +x scripts/backup.sh
# =============================================================================

set -euo pipefail

# -- Configuration -----------------------------------------------------------
VPS_HOST="${HARNESS_VPS_HOST:-your-server-ip}"
VPS_USER="root"
REMOTE_DIR="/opt/agent-harness"
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

# -- Flags -------------------------------------------------------------------
SYNC_LOCAL=false
INCLUDE_TRACES=false
LOCAL_DIR="./backups"

for arg in "$@"; do
    case "$arg" in
        --sync-local)      SYNC_LOCAL=true ;;
        --include-traces)  INCLUDE_TRACES=true ;;
        --local-dir=*)     LOCAL_DIR="${arg#*=}" ;;
        --local-dir)       shift; LOCAL_DIR="${1:-./backups}" ;;
        --help|-h)
            echo "Usage: $0 [--sync-local] [--include-traces] [--local-dir=PATH]"
            echo ""
            echo "Options:"
            echo "  --sync-local       Rsync the backup tarball to the local machine"
            echo "  --include-traces   Include data/traces/ in the backup (can be large)"
            echo "  --local-dir=PATH   Local directory for synced backup (default: ./backups)"
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
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="harness_backup_${TIMESTAMP}"
REMOTE_BACKUP_DIR="/tmp/${BACKUP_NAME}"
REMOTE_TARBALL="/tmp/${BACKUP_NAME}.tar.gz"

echo "============================================================================="
echo "  Agent Harness Backup"
echo "  Source: ${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}"
echo "  Backup: ${REMOTE_BACKUP_DIR}"
echo "  Include traces: ${INCLUDE_TRACES}"
echo "  Sync local: ${SYNC_LOCAL}"
echo "============================================================================="
echo ""

# Verify SSH connectivity
info "Testing SSH connection..."
if ! ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" "echo ok" &>/dev/null; then
    err "Cannot reach ${VPS_USER}@${VPS_HOST} via SSH."
fi
log "SSH connection verified."

# -- Step 1: Create backup directory on VPS -----------------------------------
log "[1/5] Creating backup directory on VPS..."

ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<REMOTE_MKDIR
    set -euo pipefail
    mkdir -p "${REMOTE_BACKUP_DIR}"
    echo "Created ${REMOTE_BACKUP_DIR}"
REMOTE_MKDIR

# -- Step 2: Backup SQLite databases -----------------------------------------
log "[2/5] Backing up SQLite databases..."

ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<REMOTE_SQLITE
    set -euo pipefail
    SQLITE_DIR="${REMOTE_DIR}/data/sqlite"
    BACKUP_SQLITE="${REMOTE_BACKUP_DIR}/sqlite"
    mkdir -p "\${BACKUP_SQLITE}"

    if [ -d "\${SQLITE_DIR}" ]; then
        for db in "\${SQLITE_DIR}"/*.db; do
            [ -f "\${db}" ] || continue
            db_name=\$(basename "\${db}")
            # Use sqlite3 .backup for a consistent snapshot (WAL-safe)
            if command -v sqlite3 &>/dev/null; then
                sqlite3 "\${db}" ".backup '\${BACKUP_SQLITE}/\${db_name}'"
                echo "  Backed up (sqlite3 .backup): \${db_name}"
            else
                cp "\${db}" "\${BACKUP_SQLITE}/\${db_name}"
                # Also copy WAL and SHM if present
                [ -f "\${db}-wal" ] && cp "\${db}-wal" "\${BACKUP_SQLITE}/\${db_name}-wal"
                [ -f "\${db}-shm" ] && cp "\${db}-shm" "\${BACKUP_SQLITE}/\${db_name}-shm"
                echo "  Backed up (file copy): \${db_name}"
            fi
        done
    else
        echo "  No SQLite directory found at \${SQLITE_DIR}"
    fi
REMOTE_SQLITE

# -- Step 3: Backup KuzuDB ---------------------------------------------------
log "[3/5] Backing up KuzuDB..."

ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<REMOTE_KUZU
    set -euo pipefail
    KUZU_DIR="${REMOTE_DIR}/data/kuzu"
    BACKUP_KUZU="${REMOTE_BACKUP_DIR}/kuzu"

    if [ -d "\${KUZU_DIR}" ] && [ "\$(ls -A "\${KUZU_DIR}" 2>/dev/null)" ]; then
        cp -r "\${KUZU_DIR}" "\${BACKUP_KUZU}"
        echo "  KuzuDB backed up: \$(du -sh "\${BACKUP_KUZU}" | cut -f1)"
    else
        mkdir -p "\${BACKUP_KUZU}"
        echo "  KuzuDB directory empty or not found."
    fi
REMOTE_KUZU

# -- Step 4: Backup traces (optional) ----------------------------------------
if [ "${INCLUDE_TRACES}" = true ]; then
    log "[4/5] Backing up traces (this may take a while)..."

    ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<REMOTE_TRACES
        set -euo pipefail
        TRACES_DIR="${REMOTE_DIR}/data/traces"
        BACKUP_TRACES="${REMOTE_BACKUP_DIR}/traces"

        if [ -d "\${TRACES_DIR}" ] && [ "\$(ls -A "\${TRACES_DIR}" 2>/dev/null)" ]; then
            cp -r "\${TRACES_DIR}" "\${BACKUP_TRACES}"
            echo "  Traces backed up: \$(du -sh "\${BACKUP_TRACES}" | cut -f1)"
        else
            mkdir -p "\${BACKUP_TRACES}"
            echo "  Traces directory empty or not found."
        fi
REMOTE_TRACES
else
    warn "[4/5] Skipping traces backup (use --include-traces to include)."
fi

# -- Step 5: Backup config and secrets ----------------------------------------
log "[5/5] Backing up config and secrets..."

ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<REMOTE_CONFIG
    set -euo pipefail
    BACKUP_CONFIG="${REMOTE_BACKUP_DIR}/config"
    BACKUP_SECRETS="${REMOTE_BACKUP_DIR}/secrets"

    # Config directory
    if [ -d "${REMOTE_DIR}/config" ]; then
        cp -r "${REMOTE_DIR}/config" "\${BACKUP_CONFIG}"
        echo "  Config backed up."
    fi

    # Secrets — encrypt with GPG if available
    if [ -f "${REMOTE_DIR}/secrets/.env" ]; then
        mkdir -p "\${BACKUP_SECRETS}"
        if command -v gpg &>/dev/null; then
            gpg --batch --yes --symmetric --cipher-algo AES256 \
                --passphrase-fd 0 \
                --output "\${BACKUP_SECRETS}/.env.gpg" \
                "${REMOTE_DIR}/secrets/.env" <<< "harness-backup-key"
            echo "  Secrets backed up (GPG encrypted)."
            echo "  NOTE: Decrypt with: gpg --decrypt secrets/.env.gpg > .env"
            echo "        Default passphrase: harness-backup-key (CHANGE THIS)"
        else
            cp "${REMOTE_DIR}/secrets/.env" "\${BACKUP_SECRETS}/.env"
            chmod 600 "\${BACKUP_SECRETS}/.env"
            echo "  Secrets backed up (plaintext — GPG not available for encryption)."
        fi
    else
        echo "  No secrets/.env found."
    fi
REMOTE_CONFIG

# -- Compress to tarball ------------------------------------------------------
log "Compressing backup..."

ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" bash -s <<REMOTE_COMPRESS
    set -euo pipefail
    cd /tmp
    tar -czf "${BACKUP_NAME}.tar.gz" "${BACKUP_NAME}/"
    rm -rf "${REMOTE_BACKUP_DIR}"
    echo "  Tarball: ${REMOTE_TARBALL}"
    echo "  Size: \$(du -sh "${REMOTE_TARBALL}" | cut -f1)"
REMOTE_COMPRESS

# -- Sync to local machine (optional) ----------------------------------------
if [ "${SYNC_LOCAL}" = true ]; then
    log "Syncing backup to local machine: ${LOCAL_DIR}/"
    mkdir -p "${LOCAL_DIR}"

    rsync -azP \
        -e "ssh ${SSH_OPTS}" \
        "${VPS_USER}@${VPS_HOST}:${REMOTE_TARBALL}" \
        "${LOCAL_DIR}/"

    log "Backup synced to ${LOCAL_DIR}/${BACKUP_NAME}.tar.gz"

    # Clean up remote tarball after successful sync
    ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" "rm -f ${REMOTE_TARBALL}"
    log "Remote tarball cleaned up."
fi

# -- Summary -----------------------------------------------------------------
echo ""
echo "============================================================================="
echo -e "  ${GREEN}Backup complete.${NC}"
echo "============================================================================="
echo ""
echo "  Backup name:  ${BACKUP_NAME}"
if [ "${SYNC_LOCAL}" = true ]; then
    echo "  Local path:   ${LOCAL_DIR}/${BACKUP_NAME}.tar.gz"
    if [ -f "${LOCAL_DIR}/${BACKUP_NAME}.tar.gz" ]; then
        LOCAL_SIZE=$(du -sh "${LOCAL_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)
        echo "  Local size:   ${LOCAL_SIZE}"
    fi
else
    echo "  Remote path:  ${REMOTE_TARBALL}"
fi
echo ""
echo "  Contents:"
echo "    sqlite/     — SQLite database snapshots"
echo "    kuzu/       — KuzuDB graph data"
if [ "${INCLUDE_TRACES}" = true ]; then
    echo "    traces/     — Phoenix trace data"
fi
echo "    config/     — Configuration files"
echo "    secrets/    — Encrypted .env (if GPG available)"
echo ""
echo "  Restore:"
echo "    tar -xzf ${BACKUP_NAME}.tar.gz"
echo "    cp ${BACKUP_NAME}/sqlite/*.db ${REMOTE_DIR}/data/sqlite/"
echo "    cp -r ${BACKUP_NAME}/kuzu/* ${REMOTE_DIR}/data/kuzu/"
echo ""
echo "============================================================================="
