#!/bin/bash
# =============================================================================
# Instalační skript pro Pi-Star Control
# Repozitář: https://github.com/ondrahladik/pistar-control
# =============================================================================
set -e

# ---------------------------------------------------------------------------
# Barvy a formátování výstupu
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

TOTAL_STEPS=8
REPO_URL="https://github.com/ondrahladik/pistar-control.git"
INSTALL_DIR="/opt/pistar-control"
SERVICE_NAME="pistar-control"
SERVICE_FILE="${INSTALL_DIR}/install/${SERVICE_NAME}.service"
SYSTEMD_SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"
REQUIREMENTS="${INSTALL_DIR}/install/requirements.txt"
FIREWALL_PORT=5000
IS_PISTAR=false

# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------
log_step() {
    local step=$1
    local message=$2
    echo -e "${GREEN}[${step}/${TOTAL_STEPS}]${NC} ${message}"
}

log_info() {
    echo -e "       ${YELLOW}→${NC} $1"
}

log_ok() {
    echo -e "       ${GREEN}✓${NC} $1"
}

log_error() {
    echo -e "       ${RED}✗${NC} $1" >&2
}

cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Instalace selhala s kódem: ${exit_code}"
        if [ "$IS_PISTAR" = true ] && command -v rpi-ro &>/dev/null; then
            log_info "Vracím Pi-Star filesystem do read-only režimu..."
            rpi-ro || true
        fi
    fi
    exit $exit_code
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# [0] Kontrola oprávnění
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    log_error "Tento skript musí být spuštěn jako root (sudo)."
    exit 1
fi

echo ""
echo "============================================="
echo "  Pi-Star Control – Instalační skript"
echo "============================================="
echo ""

# ---------------------------------------------------------------------------
# [1/8] Detekce Pi-Star a příprava prostředí
# ---------------------------------------------------------------------------
log_step 1 "Detekce prostředí a příprava systému..."

if [ -f /etc/pistar-release ] || command -v pistar-update &>/dev/null; then
    IS_PISTAR=true
    log_info "Detekován systém Pi-Star."

    if command -v rpi-rw &>/dev/null; then
        log_info "Přepínám filesystem do read-write režimu..."
        rpi-rw
        log_ok "Filesystem je v read-write režimu."
    else
        log_info "Příkaz rpi-rw nenalezen, zkouším mount..."
        mount -o remount,rw / 2>/dev/null || true
        mount -o remount,rw /boot 2>/dev/null || true
        log_ok "Filesystem přemountován jako read-write."
    fi

    log_info "Opravuji Debian Buster repozitáře (EOL)..."

    APT_SOURCES=()
    [ -f /etc/apt/sources.list ] && APT_SOURCES+=(/etc/apt/sources.list)
    if [ -d /etc/apt/sources.list.d ]; then
        for f in /etc/apt/sources.list.d/*.list; do
            [ -f "$f" ] && APT_SOURCES+=("$f")
        done
    fi

    for src_file in "${APT_SOURCES[@]}"; do
        sed -i 's|https\?://httpredir\.debian\.org/debian|http://archive.debian.org/debian|g' "$src_file" || true
        sed -i 's|https\?://deb\.debian\.org/debian|http://archive.debian.org/debian|g' "$src_file" || true
        sed -i 's|https\?://raspbian\.raspberrypi\.org/raspbian|http://legacy.raspbian.org/raspbian|g' "$src_file" || true
        sed -i 's|https\?://archive\.raspbian\.org/raspbian|http://legacy.raspbian.org/raspbian|g' "$src_file" || true
        sed -i 's|https\?://legacy\.raspbian\.org/debian|http://archive.raspberrypi.org/debian|g' "$src_file" || true
        sed -i '/^#\(deb.*archive\.raspberrypi\.org\/debian\)/s/^#//' "$src_file" || true
    done

    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid

    log_ok "Repozitáře opraveny."
else
    log_info "Systém Pi-Star nebyl detekován – standardní Debian/Ubuntu instalace."
fi

# ---------------------------------------------------------------------------
# [2/8] Instalace systémových balíčků
# ---------------------------------------------------------------------------
log_step 2 "Instalace systémových balíčků..."

export DEBIAN_FRONTEND=noninteractive

log_info "Aktualizace seznamu balíčků..."
apt-get update -qq || {
    log_info "apt update skončil s varováním – pokračuji v instalaci..."
}

log_info "Předkonfigurace iptables-persistent..."
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections

log_info "Instalace balíčků: iptables, iptables-persistent, git, python3, python3-pip..."
apt-get install -y -qq iptables iptables-persistent netfilter-persistent git python3 python3-pip > /dev/null 2>&1

log_ok "Systémové balíčky nainstalovány."

# ---------------------------------------------------------------------------
# [3/8] Nastavení firewallu (iptables)
# ---------------------------------------------------------------------------
log_step 3 "Nastavení firewallu – otevření TCP portu ${FIREWALL_PORT}..."

if iptables -C INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT 2>/dev/null; then
    log_info "IPv4 pravidlo pro port ${FIREWALL_PORT}/tcp již existuje."
else
    iptables -I INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT
    log_ok "IPv4 pravidlo pro port ${FIREWALL_PORT}/tcp přidáno."
fi

if ip6tables -C INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT 2>/dev/null; then
    log_info "IPv6 pravidlo pro port ${FIREWALL_PORT}/tcp již existuje."
else
    ip6tables -I INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT
    log_ok "IPv6 pravidlo pro port ${FIREWALL_PORT}/tcp přidáno."
fi

log_info "Ukládám pravidla firewallu (IPv4 + IPv6)..."
netfilter-persistent save > /dev/null 2>&1
log_ok "Pravidla firewallu uložena."

# ---------------------------------------------------------------------------
# [4/8] Klonování / aktualizace repozitáře
# ---------------------------------------------------------------------------
log_step 4 "Příprava repozitáře v ${INSTALL_DIR}..."

if [ -d "${INSTALL_DIR}/.git" ]; then
    log_info "Repozitář již existuje – stahuji aktualizace..."
    cd "${INSTALL_DIR}"
    if git pull --ff-only 2>/dev/null; then
        log_ok "Repozitář aktualizován."
    else
        log_info "${YELLOW}Varování:${NC} git pull selhal (lokální změny?) – pokračuji s aktuální verzí."
    fi
else
    if [ -d "${INSTALL_DIR}" ]; then
        log_info "Adresář existuje, ale není git repozitář – odstraňuji..."
        rm -rf "${INSTALL_DIR}"
    fi
    log_info "Klonuji repozitář..."
    git clone "${REPO_URL}" "${INSTALL_DIR}"
    log_ok "Repozitář naklonován do ${INSTALL_DIR}."
fi

# ---------------------------------------------------------------------------
# [5/8] Ověření souborů repozitáře
# ---------------------------------------------------------------------------
log_step 5 "Ověření souborů repozitáře..."

if [ ! -f "${INSTALL_DIR}/main.py" ]; then
    log_error "Soubor main.py nenalezen v ${INSTALL_DIR}!"
    exit 1
fi
log_ok "main.py nalezen."

if [ ! -f "${REQUIREMENTS}" ]; then
    log_error "Soubor requirements.txt nenalezen: ${REQUIREMENTS}"
    exit 1
fi
log_ok "requirements.txt nalezen."

if [ ! -f "${SERVICE_FILE}" ]; then
    log_error "Service soubor nenalezen: ${SERVICE_FILE}"
    exit 1
fi
log_ok "pistar-control.service nalezen."

CONFIG_DIR="${INSTALL_DIR}/config"
if [ ! -f "${CONFIG_DIR}/app.ini" ] && [ -f "${CONFIG_DIR}/app.ini.sample" ]; then
    log_info "Vytvářím výchozí konfiguraci z app.ini.sample..."
    cp "${CONFIG_DIR}/app.ini.sample" "${CONFIG_DIR}/app.ini"
    log_ok "Konfigurační soubor app.ini vytvořen."
elif [ -f "${CONFIG_DIR}/app.ini" ]; then
    log_info "Konfigurační soubor app.ini již existuje – ponechávám beze změny."
fi

# ---------------------------------------------------------------------------
# [6/8] Instalace Python závislostí
# ---------------------------------------------------------------------------
log_step 6 "Instalace Python závislostí..."

log_info "Instaluji balíčky z ${REQUIREMENTS}..."
pip3 install --root-user-action=ignore --break-system-packages -r "${REQUIREMENTS}" -q 2>/dev/null \
    || pip3 install --root-user-action=ignore -r "${REQUIREMENTS}" -q 2>/dev/null \
    || pip3 install -r "${REQUIREMENTS}" -q
log_ok "Python závislosti nainstalovány."

# ---------------------------------------------------------------------------
# [7/8] Instalace a spuštění systemd služby
# ---------------------------------------------------------------------------
log_step 7 "Instalace systemd služby ${SERVICE_NAME}..."

if [ ! -f "${SYSTEMD_SERVICE}" ] || ! cmp -s "${SERVICE_FILE}" "${SYSTEMD_SERVICE}"; then
    log_info "Kopíruji ${SERVICE_FILE} → ${SYSTEMD_SERVICE}"
    cp "${SERVICE_FILE}" "${SYSTEMD_SERVICE}"
    log_ok "Service soubor zkopírován."
else
    log_info "Service soubor je aktuální – kopírování není potřeba."
fi

log_info "Reloaduji systemd..."
systemctl daemon-reload
log_ok "Systemd reloadován."

log_info "Povoluji službu pro start při bootu..."
systemctl enable "${SERVICE_NAME}" --quiet
log_ok "Služba povolena."

log_info "Spouštím službu ${SERVICE_NAME}..."
systemctl restart "${SERVICE_NAME}"

sleep 2
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    log_ok "Služba ${SERVICE_NAME} běží."
else
    log_error "Služba ${SERVICE_NAME} se nepodařila spustit!"
    log_info "Pro diagnostiku spusťte: journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
    exit 1
fi

# ---------------------------------------------------------------------------
# [8/8] Dokončení a Pi-Star read-only režim
# ---------------------------------------------------------------------------
log_step 8 "Dokončení instalace..."

if [ "$IS_PISTAR" = true ]; then
    if command -v rpi-ro &>/dev/null; then
        log_info "Vracím Pi-Star filesystem do read-only režimu..."
        rpi-ro || true
        log_ok "Filesystem přepnut do read-only režimu."
    fi
fi

echo ""
echo "============================================="
echo -e "  ${GREEN}Instalace úspěšně dokončena!${NC}"
echo "============================================="
echo ""
echo "  Služba:       ${SERVICE_NAME}"
echo "  Port:         ${FIREWALL_PORT}/tcp"
echo "  Adresář:      ${INSTALL_DIR}"
echo "  Web rozhraní: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):${FIREWALL_PORT}"
echo ""
echo "  Užitečné příkazy:"
echo "    systemctl status ${SERVICE_NAME}"
echo "    journalctl -u ${SERVICE_NAME} -f"
echo ""