#!/usr/bin/env bash
# =============================================================================
# Server Hardening Script
# Run after setup.sh to lock down the VPS
# Usage:  sudo bash scripts/harden.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

if [[ $EUID -ne 0 ]]; then
  err "This script must be run as root (use sudo)."
fi

echo "============================================================================="
echo "  Server Hardening"
echo "============================================================================="
echo ""

# -- Step 1: SSH Hardening ---------------------------------------------------
log "[1/6] Hardening SSH configuration..."

SSH_CONFIG="/etc/ssh/sshd_config"
cp "${SSH_CONFIG}" "${SSH_CONFIG}.bak.$(date +%s)"

# Disable root password login (key-only)
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSH_CONFIG"
# Disable password authentication entirely
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' "$SSH_CONFIG"
# Disable empty passwords
sed -i 's/^#*PermitEmptyPasswords.*/PermitEmptyPasswords no/' "$SSH_CONFIG"
# Limit auth attempts
sed -i 's/^#*MaxAuthTries.*/MaxAuthTries 3/' "$SSH_CONFIG"
# Disable X11 forwarding
sed -i 's/^#*X11Forwarding.*/X11Forwarding no/' "$SSH_CONFIG"
# Set idle timeout (10 min)
grep -q "^ClientAliveInterval" "$SSH_CONFIG" || echo "ClientAliveInterval 600" >> "$SSH_CONFIG"
grep -q "^ClientAliveCountMax" "$SSH_CONFIG" || echo "ClientAliveCountMax 2" >> "$SSH_CONFIG"

systemctl restart ssh 2>/dev/null || systemctl restart sshd
log "SSH hardened: key-only auth, no passwords, 3 max attempts."

# -- Step 2: UFW Firewall ---------------------------------------------------
log "[2/6] Configuring UFW firewall..."

apt-get install -y -qq ufw

ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'

# Enable without prompt
echo "y" | ufw enable
ufw status verbose

log "UFW configured: allow 22, 80, 443 inbound only."

# -- Step 3: Fail2Ban -------------------------------------------------------
log "[3/6] Installing and configuring fail2ban..."

apt-get install -y -qq fail2ban

cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
backend = systemd

[sshd]
enabled = true
port = ssh
maxretry = 3
bantime = 7200

[nginx-http-auth]
enabled = true
port = http,https
maxretry = 5
bantime = 3600
EOF

systemctl enable --now fail2ban
log "fail2ban configured: SSH (3 attempts, 2hr ban), nginx auth (5 attempts, 1hr ban)."

# -- Step 4: Automatic Security Updates -------------------------------------
log "[4/6] Enabling automatic security updates..."

apt-get install -y -qq unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades 2>/dev/null || true

cat > /etc/apt/apt.conf.d/20auto-upgrades << 'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

log "Automatic security updates enabled."

# -- Step 5: System Hardening -----------------------------------------------
log "[5/6] Applying system hardening..."

# Restrict /tmp and shared memory
grep -q "/run/shm" /etc/fstab || echo "tmpfs /run/shm tmpfs defaults,noexec,nosuid 0 0" >> /etc/fstab

# Harden sysctl
cat > /etc/sysctl.d/99-hardening.conf << 'EOF'
# Disable IP forwarding
net.ipv4.ip_forward = 0
net.ipv6.conf.all.forwarding = 0

# Ignore ICMP redirects
net.ipv4.conf.all.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0

# Ignore source-routed packets
net.ipv4.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0

# SYN flood protection
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 2048
net.ipv4.tcp_synack_retries = 2

# Ignore ICMP broadcasts
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Log martian packets
net.ipv4.conf.all.log_martians = 1
EOF

sysctl -p /etc/sysctl.d/99-hardening.conf 2>/dev/null

log "System hardening applied (sysctl, shared memory)."

# -- Step 6: Log rotation for harness ---------------------------------------
log "[6/6] Configuring log rotation..."

cat > /etc/logrotate.d/agent-harness << 'EOF'
/opt/agent-harness/logs/**/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 640 harness harness
}
EOF

log "Log rotation configured: 14 days, daily, compressed."

# -- Summary -----------------------------------------------------------------
echo ""
echo "============================================================================="
echo -e "${GREEN}  Server Hardening Complete${NC}"
echo "============================================================================="
echo ""
echo "  Applied:"
echo "    - SSH: key-only, no passwords, max 3 auth attempts"
echo "    - UFW: allow 22/80/443 only, deny all other inbound"
echo "    - fail2ban: SSH brute-force protection, nginx auth protection"
echo "    - Auto security updates enabled"
echo "    - Sysctl hardening (SYN flood, ICMP, redirects)"
echo "    - Log rotation (14 day retention)"
echo ""
echo "  Recommended manual steps:"
echo "    - Create a non-root user for SSH: adduser deploy && usermod -aG sudo deploy"
echo "    - Copy SSH keys: ssh-copy-id -i ~/.ssh/hetzner deploy@server"
echo "    - Set up TLS: certbot --nginx -d your-domain.com"
echo "    - Change nginx htpasswd: htpasswd /etc/nginx/.htpasswd harness"
echo "    - Review Hetzner Cloud firewall rules match UFW"
echo ""
echo "============================================================================="
