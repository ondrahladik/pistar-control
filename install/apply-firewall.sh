#!/bin/bash
set -e

FIREWALL_PORT="${FIREWALL_PORT:-5000}"
MQTT_PORT="${MQTT_PORT:-1883}"

ensure_rule() {
    local tool=$1
    shift

    if command -v "${tool}" >/dev/null 2>&1; then
        if "${tool}" -C "$@" 2>/dev/null; then
            return 0
        fi
        "${tool}" -I "$@"
    fi
}

ensure_append_rule() {
    local tool=$1
    shift

    if command -v "${tool}" >/dev/null 2>&1; then
        if "${tool}" -C "$@" 2>/dev/null; then
            return 0
        fi
        "${tool}" -A "$@"
    fi
}

ensure_rule iptables INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT
ensure_rule ip6tables INPUT -p tcp --dport "${FIREWALL_PORT}" -j ACCEPT
ensure_append_rule iptables OUTPUT -p tcp --dport "${MQTT_PORT}" -j ACCEPT

if command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save >/dev/null 2>&1 || true
fi
