#!/bin/bash
# =============================================================================
# Aktualizační skript pro Pi-Star Control
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

TOTAL_STEPS=5
INSTALL_DIR="/opt/pistar-control"
REPO_URL="https://github.com/ondrahladik/pistar-control.git"
SERVICE_NAME="pistar-control"
SERVICE_FILE="${INSTALL_DIR}/install/${SERVICE_NAME}.service"
SYSTEMD_SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"
IS_PISTAR=false
RESTORE_RO=false

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
        remount_ro_path /var
        remount_ro_path /
    fi
}

cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Aktualizace selhala s kódem: ${exit_code}"
    fi
    restore_pistar_ro
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
echo "  Pi-Star Control – Aktualizační skript"
echo "============================================="
echo ""

# ---------------------------------------------------------------------------
# [1/4] Detekce Pi-Star a příprava prostředí
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
        log_ok "Filesystem přemountován jako read-write."
    fi

    log_info "Ověřuji zapisovatelnost cílového adresáře..."
    if [ -d "${INSTALL_DIR}" ]; then
        TARGET_DIR="${INSTALL_DIR}"
    else
        TARGET_DIR="/opt"
    fi

    if ensure_writable_dir "${TARGET_DIR}"; then
        log_ok "Cílový adresář je zapisovatelný."
    else
        log_error "Adresář ${TARGET_DIR} je stále read-only."
        log_error "Na tomto Pi-Star systému je potřeba nejprve přepnout celý systém do RW režimu."
        exit 1
    fi
else
    log_info "Systém Pi-Star nebyl detekován – standardní Debian/Ubuntu instalace."
fi

# ---------------------------------------------------------------------------
# [2/4] Ověření repozitáře
# ---------------------------------------------------------------------------
log_step 2 "Ověření repozitáře..."

if [ ! -d "${INSTALL_DIR}" ]; then
    log_error "Adresář ${INSTALL_DIR} neexistuje."
    log_error "Nejprve spusťte instalační skript install.sh."
    exit 1
fi

if [ ! -d "${INSTALL_DIR}/.git" ]; then
    log_error "Adresář ${INSTALL_DIR} není git repozitář."
    log_error "Očekávaný repozitář: ${REPO_URL}"
    exit 1
fi

log_ok "Repozitář nalezen."

# ---------------------------------------------------------------------------
# [3/4] Aktualizace z GitHubu
# ---------------------------------------------------------------------------
log_step 3 "Aktualizace repozitáře z GitHubu..."

cd "${INSTALL_DIR}"

if git pull --ff-only --quiet > /dev/null 2>&1; then
    log_ok "Repozitář byl úspěšně aktualizován."
else
    log_error "Aktualizaci z GitHubu se nepodařilo provést."
    log_error "Zkontrolujte lokální změny v ${INSTALL_DIR} nebo dostupnost repozitáře."
    exit 1
fi

# ---------------------------------------------------------------------------
# [4/5] Aktualizace systemd služby a restart
# ---------------------------------------------------------------------------
log_step 4 "Aktualizace systemd služby a restart aplikace..."

if [ ! -f "${SERVICE_FILE}" ]; then
    log_error "Service soubor nenalezen: ${SERVICE_FILE}"
    exit 1
fi

if [ ! -f "${INSTALL_DIR}/install/apply-firewall.sh" ]; then
    log_error "Pomocný firewall skript nenalezen: ${INSTALL_DIR}/install/apply-firewall.sh"
    exit 1
fi

chmod +x "${INSTALL_DIR}/install/apply-firewall.sh"

if [ ! -f "${SYSTEMD_SERVICE}" ] || ! cmp -s "${SERVICE_FILE}" "${SYSTEMD_SERVICE}"; then
    log_info "Kopíruji ${SERVICE_FILE} → ${SYSTEMD_SERVICE}"
    cp "${SERVICE_FILE}" "${SYSTEMD_SERVICE}"
    log_ok "Service soubor aktualizován."
else
    log_info "Service soubor je aktuální."
fi

log_info "Reloaduji systemd..."
systemctl daemon-reload
log_ok "Systemd reloadován."

log_info "Restartuji službu ${SERVICE_NAME}..."
if systemctl restart "${SERVICE_NAME}"; then
    log_ok "Služba ${SERVICE_NAME} byla restartována."
else
    log_error "Restart služby ${SERVICE_NAME} selhal."
    exit 1
fi

# ---------------------------------------------------------------------------
# [5/5] Dokončení a Pi-Star read-only režim
# ---------------------------------------------------------------------------
log_step 5 "Dokončení aktualizace..."

if [ "$IS_PISTAR" = true ] && [ "$RESTORE_RO" = true ]; then
    log_info "Vrácení Pi-Star filesystemu do read-only režimu..."
    restore_pistar_ro
    log_ok "Filesystem přepnut do read-only režimu."
    RESTORE_RO=false
fi

echo ""
echo "============================================="
echo -e "  ${GREEN}Aktualizace úspěšně dokončena!${NC}"
echo "============================================="
echo ""
echo "  Repozitář: ${INSTALL_DIR}"
echo "  Zdroj:     ${REPO_URL}"
echo ""
