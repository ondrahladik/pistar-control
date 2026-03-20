#!/bin/bash
# =============================================================================
# Odinstalační skript pro Pi-Star Control
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
INSTALL_DIR="/opt/pistar-control"
SERVICE_NAME="pistar-control"
SYSTEMD_SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"
REQUIREMENTS="${INSTALL_DIR}/install/requirements.txt"
FIREWALL_PORT=5000
APT_OVERRIDE_FILE="/etc/apt/apt.conf.d/99no-check-valid"
IS_PISTAR=false
RESTORE_RO=false

# ---------------------------------------------------------------------------
# Přesun skriptu mimo odstraňovaný adresář
# ---------------------------------------------------------------------------
CURRENT_SCRIPT="$(readlink -f "$0" 2>/dev/null || printf '%s' "$0")"
if [ -z "${PISTAR_CONTROL_REMOVE_REEXEC:-}" ] && [ -n "$CURRENT_SCRIPT" ] && [ -f "$CURRENT_SCRIPT" ]; then
    case "$CURRENT_SCRIPT" in
        "${INSTALL_DIR}"/*)
            TMP_SCRIPT="/tmp/pistar-control-remove.sh"
            cp "$CURRENT_SCRIPT" "$TMP_SCRIPT"
            chmod +x "$TMP_SCRIPT"
            export PISTAR_CONTROL_REMOVE_REEXEC=1
            exec "$TMP_SCRIPT" "$@"
            ;;
    esac
fi

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

remount_rw_path() {
    local target=$1
    if mountpoint -q "$target" 2>/dev/null; then
        mount -o remount,rw "$target" 2>/dev/null || true
    fi
}

remount_ro_path() {
    local target=$1
    if mountpoint -q "$target" 2>/dev/null; then
        mount -o remount,ro "$target" 2>/dev/null || true
    fi
}

ensure_writable_dir() {
    local dir=$1
    mkdir -p "$dir"
    local probe="${dir}/.pistar-control-write-test"
    if touch "$probe" 2>/dev/null; then
        rm -f "$probe"
        return 0
    fi
    return 1
}

restore_pistar_ro() {
    if [ "$IS_PISTAR" != true ] || [ "$RESTORE_RO" != true ]; then
        return
    fi

    if command -v rpi-ro &>/dev/null; then
        log_info "Vracím Pi-Star filesystem do read-only režimu..."
        rpi-ro || true
    else
        log_info "Vrácení filesystemu do read-only režimu..."
        remount_ro_path /boot
        remount_ro_path /var/cache/debconf
        remount_ro_path /var/cache/apt
        remount_ro_path /var/lib/apt
        remount_ro_path /var/lib/dpkg
        remount_ro_path /var/cache
        remount_ro_path /var/lib
        remount_ro_path /var
        remount_ro_path /
    fi
}

cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Odinstalace selhala s kódem: ${exit_code}"
    fi
    restore_pistar_ro
    if [ "${PISTAR_CONTROL_REMOVE_REEXEC:-}" = "1" ] && [ -f "$0" ]; then
        rm -f "$0" || true
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
echo "  Pi-Star Control – Odinstalační skript"
echo "============================================="
echo ""

# ---------------------------------------------------------------------------
# [1/8] Detekce Pi-Star a příprava prostředí
# ---------------------------------------------------------------------------
log_step 1 "Detekce prostředí a příprava systému..."

if [ -f /etc/pistar-release ] || command -v pistar-update &>/dev/null; then
    IS_PISTAR=true
    RESTORE_RO=true
    log_info "Detekován systém Pi-Star."

    if command -v rpi-rw &>/dev/null; then
        log_info "Přepínám filesystem do read-write režimu..."
        rpi-rw
        log_ok "Filesystem je v read-write režimu."
    else
        log_info "Příkaz rpi-rw nenalezen, zkouším mount..."
        remount_rw_path /
        remount_rw_path /boot
        remount_rw_path /var
        remount_rw_path /var/cache
        remount_rw_path /var/cache/apt
        remount_rw_path /var/cache/debconf
        remount_rw_path /var/lib
        remount_rw_path /var/lib/apt
        remount_rw_path /var/lib/dpkg
        log_ok "Filesystem přemountován jako read-write."
    fi

    log_info "Ověřuji zapisovatelnost systémových adresářů..."
    for writable_dir in /var/cache/debconf /var/cache/apt /var/lib/apt /var/lib/dpkg; do
        if ensure_writable_dir "$writable_dir"; then
            :
        else
            log_error "Adresář ${writable_dir} je stále read-only."
            log_error "Na tomto Pi-Star systému je potřeba nejprve přepnout celý systém do RW režimu."
            exit 1
        fi
    done
    log_ok "Systémové adresáře jsou zapisovatelné."
else
    log_info "Systém Pi-Star nebyl detekován – standardní Debian/Ubuntu instalace."
fi

# ---------------------------------------------------------------------------
# [2/8] Zastavení a zakázání služby
# ---------------------------------------------------------------------------
log_step 2 "Zastavení a zakázání služby ${SERVICE_NAME}..."

if systemctl list-unit-files "${SERVICE_NAME}.service" --no-legend 2>/dev/null | grep -q "^${SERVICE_NAME}\.service"; then
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        log_info "Zastavuji službu ${SERVICE_NAME}..."
        systemctl stop "${SERVICE_NAME}"
        log_ok "Služba zastavena."
    else
        log_info "Služba ${SERVICE_NAME} neběží."
    fi

    if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
        log_info "Zakazuji automatický start služby..."
        systemctl disable "${SERVICE_NAME}" --quiet
        log_ok "Automatický start služby zakázán."
    else
        log_info "Služba není povolena pro start při bootu."
    fi
else
    log_info "Systemd služba ${SERVICE_NAME} není nainstalována."
fi

# ---------------------------------------------------------------------------
# [3/8] Odstranění systemd služby
# ---------------------------------------------------------------------------
log_step 3 "Odstranění systemd služby..."

if [ -f "${SYSTEMD_SERVICE}" ]; then
    rm -f "${SYSTEMD_SERVICE}"
    log_ok "Service soubor odstraněn."
else
    log_info "Service soubor již neexistuje."
fi

systemctl daemon-reload
systemctl reset-failed "${SERVICE_NAME}" >/dev/null 2>&1 || true
log_ok "Systemd reloadován."

# ---------------------------------------------------------------------------
# [4/8] Odstranění firewall pravidel
# ---------------------------------------------------------------------------
log_step 4 "Odstranění firewall pravidel pro port ${FIREWALL_PORT}..."

IPV4_REMOVED=false
while iptables -C INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT 2>/dev/null; do
    iptables -D INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT
    IPV4_REMOVED=true
done
if [ "$IPV4_REMOVED" = true ]; then
    log_ok "IPv4 pravidla odstraněna."
else
    log_info "IPv4 pravidla pro port ${FIREWALL_PORT}/tcp neexistují."
fi

IPV6_REMOVED=false
while ip6tables -C INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT 2>/dev/null; do
    ip6tables -D INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT
    IPV6_REMOVED=true
done
if [ "$IPV6_REMOVED" = true ]; then
    log_ok "IPv6 pravidla odstraněna."
else
    log_info "IPv6 pravidla pro port ${FIREWALL_PORT}/tcp neexistují."
fi

if command -v netfilter-persistent &>/dev/null; then
    log_info "Ukládám pravidla firewallu..."
    netfilter-persistent save > /dev/null 2>&1
    log_ok "Pravidla firewallu uložena."
else
    log_info "netfilter-persistent není dostupný – ukládání pravidel přeskakuji."
fi

# ---------------------------------------------------------------------------
# [5/8] Odinstalace Python závislostí
# ---------------------------------------------------------------------------
log_step 5 "Odinstalace Python závislostí..."

if command -v pip3 &>/dev/null; then
    if [ -f "${REQUIREMENTS}" ]; then
        log_info "Odinstaluji balíčky z ${REQUIREMENTS}..."
        if pip3 uninstall -y -r "${REQUIREMENTS}" > /dev/null 2>&1; then
            log_ok "Python závislosti odinstalovány."
        else
            log_info "Python závislosti se nepodařilo odinstalovat přes requirements.txt – pokračuji dál."
        fi
    else
        log_info "Soubor requirements.txt nebyl nalezen – zkouším odinstalovat Flask přímo..."
        pip3 uninstall -y Flask > /dev/null 2>&1 || true
        log_ok "Odinstalace Python závislostí dokončena."
    fi
else
    log_info "pip3 není dostupný – odinstalaci Python závislostí přeskakuji."
fi

# ---------------------------------------------------------------------------
# [6/8] Smazání repozitáře aplikace
# ---------------------------------------------------------------------------
log_step 6 "Smazání repozitáře aplikace..."

if [ -d "${INSTALL_DIR}" ]; then
    rm -rf "${INSTALL_DIR}"
    log_ok "Adresář ${INSTALL_DIR} odstraněn."
else
    log_info "Adresář ${INSTALL_DIR} již neexistuje."
fi

# ---------------------------------------------------------------------------
# [7/8] Úklid doplňkových artefaktů
# ---------------------------------------------------------------------------
log_step 7 "Úklid doplňkových artefaktů..."

if [ -f "${APT_OVERRIDE_FILE}" ]; then
    rm -f "${APT_OVERRIDE_FILE}"
    log_ok "Soubor ${APT_OVERRIDE_FILE} odstraněn."
else
    log_info "Soubor ${APT_OVERRIDE_FILE} již neexistuje."
fi

PACKAGES_TO_PURGE=()
for package_name in iptables-persistent netfilter-persistent git python3-pip; do
    if dpkg -s "${package_name}" > /dev/null 2>&1; then
        PACKAGES_TO_PURGE+=("${package_name}")
    fi
done

if [ ${#PACKAGES_TO_PURGE[@]} -gt 0 ]; then
    log_info "Odinstaluji balíčky: ${PACKAGES_TO_PURGE[*]}..."
    apt-get purge -y -qq "${PACKAGES_TO_PURGE[@]}" > /dev/null 2>&1 || true
    apt-get autoremove -y -qq > /dev/null 2>&1 || true
    log_ok "Doplňkové balíčky odinstalovány."
else
    log_info "Žádné doplňkové balíčky k odinstalaci nebyly nalezeny."
fi

log_info "Sdílené systémové balíčky python3 a iptables ponechávám beze změny."

# ---------------------------------------------------------------------------
# [8/8] Dokončení a Pi-Star read-only režim
# ---------------------------------------------------------------------------
log_step 8 "Dokončení odinstalace..."

if [ "$IS_PISTAR" = true ] && [ "$RESTORE_RO" = true ]; then
    log_info "Vrácení Pi-Star filesystemu do read-only režimu..."
    restore_pistar_ro
    log_ok "Filesystem přepnut do read-only režimu."
    RESTORE_RO=false
fi

echo ""
echo "============================================="
echo -e "  ${GREEN}Odinstalace úspěšně dokončena!${NC}"
echo "============================================="
echo ""
echo "  Odstraněno:"
echo "    služba ${SERVICE_NAME}"
echo "    pravidla firewallu pro ${FIREWALL_PORT}/tcp"
echo "    repozitář ${INSTALL_DIR}"
echo ""
