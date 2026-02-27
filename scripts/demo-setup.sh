#!/usr/bin/env bash
# demo-setup.sh — Create a reproducible ccmux demo environment.
#
# Usage:
#   ./scripts/demo-setup.sh             # create demo repos + sessions
#   ./scripts/demo-setup.sh --teardown  # remove everything
#
# Creates two git repos in /tmp/ccmux-demo with 5 ccmux sessions that
# demonstrate the sidebar's branch/diff display.

set -euo pipefail

DEMO_DIR="/tmp/ccmux-demo"
SESSIONS=(fw-main fw-hot-newness fw-detached cli-main cli-connectivity)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '  \033[1;33m!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Guard against auto_attach_if_outside_tmux replacing our process.
export_tmux_guard() {
    if [[ -z "${TMUX:-}" ]]; then
        export TMUX=1
        export __DEMO_TMUX_GUARD=1
    fi
}

restore_tmux_guard() {
    if [[ -n "${__DEMO_TMUX_GUARD:-}" ]]; then
        unset TMUX
        unset __DEMO_TMUX_GUARD
    fi
}

ccmux_new() {
    # Usage: ccmux_new <name> [--worktree]
    export_tmux_guard
    ccmux new "$@" -y
    restore_tmux_guard
}

ccmux_remove() {
    export_tmux_guard
    ccmux remove -y "$1"
    restore_tmux_guard
}

# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

teardown() {
    info "Tearing down demo environment"

    for name in "${SESSIONS[@]}"; do
        if ccmux_remove "$name" 2>/dev/null; then
            ok "Removed session: $name"
        else
            warn "Session not found (already removed?): $name"
        fi
    done

    if [[ -d "$DEMO_DIR" ]]; then
        rm -rf "$DEMO_DIR"
        ok "Deleted $DEMO_DIR"
    else
        warn "$DEMO_DIR does not exist"
    fi

    info "Teardown complete"
    exit 0
}

# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------

check_existing() {
    if [[ -d "$DEMO_DIR" ]]; then
        die "$DEMO_DIR already exists. Run with --teardown first."
    fi
}

# ---------------------------------------------------------------------------
# Create demo repos
# ---------------------------------------------------------------------------

create_device_firmware() {
    local repo="$DEMO_DIR/device_firmware"
    info "Creating device_firmware repo"
    mkdir -p "$repo"
    git -C "$repo" init -b main --quiet

    cat > "$repo/main.c" << 'CFILE'
#include "firmware.h"
#include "sensor.h"

static config_t g_config;

int main(void) {
    system_init();
    sensor_init(&g_config);

    while (1) {
        sensor_reading_t reading = sensor_read();
        if (reading.status == SENSOR_OK) {
            process_data(&reading);
            transmit_packet(&reading);
        }
        sleep_ms(g_config.poll_interval_ms);
    }
    return 0;
}
CFILE

    cat > "$repo/firmware.h" << 'HFILE'
#ifndef FIRMWARE_H
#define FIRMWARE_H

#include <stdint.h>

#define FW_VERSION_MAJOR 2
#define FW_VERSION_MINOR 4
#define MAX_SENSORS 8
#define POLL_INTERVAL_DEFAULT_MS 100

typedef struct {
    uint32_t poll_interval_ms;
    uint8_t  active_sensors;
    uint8_t  log_level;
} config_t;

typedef enum {
    SENSOR_OK = 0,
    SENSOR_ERR_TIMEOUT,
    SENSOR_ERR_CHECKSUM,
} sensor_status_t;

typedef struct {
    sensor_status_t status;
    int16_t         temperature;
    uint16_t        humidity;
    uint32_t        timestamp;
} sensor_reading_t;

void system_init(void);
void process_data(const sensor_reading_t *reading);
void transmit_packet(const sensor_reading_t *reading);
void sleep_ms(uint32_t ms);

#endif /* FIRMWARE_H */
HFILE

    cat > "$repo/sensor.c" << 'SFILE'
#include "firmware.h"

static uint32_t s_read_count = 0;

void sensor_init(const config_t *cfg) {
    s_read_count = 0;
    /* configure I2C bus, set pull-ups, etc. */
}

sensor_reading_t sensor_read(void) {
    sensor_reading_t r = {0};
    s_read_count++;
    /* ... real hardware access would go here ... */
    r.status      = SENSOR_OK;
    r.temperature = 2350;   /* 23.50 C */
    r.humidity    = 4800;   /* 48.00 % */
    r.timestamp   = s_read_count;
    return r;
}
SFILE

    git -C "$repo" add -A && git -C "$repo" commit -m "Initial firmware scaffold" --quiet
    ok "device_firmware repo ready"
}

create_cli_tools() {
    local repo="$DEMO_DIR/cli_tools"
    info "Creating cli_tools repo"
    mkdir -p "$repo"
    git -C "$repo" init -b main --quiet

    cat > "$repo/cli.py" << 'PYFILE'
"""cli_tools — lightweight device management CLI."""

import argparse
import sys

from config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Device management CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show device status")
    sub.add_parser("logs", help="Stream device logs")

    flash_p = sub.add_parser("flash", help="Flash firmware to device")
    flash_p.add_argument("image", help="Path to firmware image")

    return parser


def main() -> int:
    cfg = load_config()
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    print(f"[{cfg['device_name']}] Running: {args.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYFILE

    cat > "$repo/config.py" << 'CFGFILE'
"""Configuration loader for cli_tools."""

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "device_name": "sensor-hub-01",
    "baud_rate": 115200,
    "log_level": "info",
    "timeout_s": 30,
}


def load_config(path: str | None = None) -> dict:
    """Load configuration from JSON file, falling back to defaults."""
    if path is None:
        path = Path.home() / ".cli_tools" / "config.json"
    else:
        path = Path(path)

    if path.exists():
        with open(path) as f:
            user_cfg = json.load(f)
        return {**DEFAULT_CONFIG, **user_cfg}

    return dict(DEFAULT_CONFIG)
CFGFILE

    git -C "$repo" add -A && git -C "$repo" commit -m "Initial CLI scaffold" --quiet
    ok "cli_tools repo ready"
}

# ---------------------------------------------------------------------------
# Create sessions
# ---------------------------------------------------------------------------

create_sessions() {
    local fw_repo="$DEMO_DIR/device_firmware"
    local cli_repo="$DEMO_DIR/cli_tools"

    # 1. fw-main — main branch, clean
    info "Creating session: fw-main"
    (cd "$fw_repo" && ccmux_new fw-main)
    ok "fw-main (main, clean)"

    # 2. fw-hot-newness — worktree, feature branch with diffs
    info "Creating session: fw-hot-newness"
    (cd "$fw_repo" && ccmux_new fw-hot-newness --worktree)

    local wt_hot="$fw_repo/.worktrees/fw-hot-newness"
    git -C "$wt_hot" checkout -b feature/hot_newness --quiet

    # Edit tracked file (firmware.h): bump version + add turbo mode defines
    sed -i 's/#define FW_VERSION_MINOR 4/#define FW_VERSION_MINOR 5/' "$wt_hot/firmware.h"
    sed -i '/#define POLL_INTERVAL_DEFAULT_MS/a\
#define TURBO_MODE_ENABLED 1\
#define TURBO_BOOST_FACTOR 4' "$wt_hot/firmware.h"

    # Create new file turbo.c and stage it
    cat > "$wt_hot/turbo.c" << 'TURBO'
#include "firmware.h"

#if TURBO_MODE_ENABLED

static uint8_t s_turbo_active = 0;

void turbo_engage(config_t *cfg) {
    if (s_turbo_active) return;
    cfg->poll_interval_ms /= TURBO_BOOST_FACTOR;
    s_turbo_active = 1;
}

void turbo_disengage(config_t *cfg) {
    if (!s_turbo_active) return;
    cfg->poll_interval_ms *= TURBO_BOOST_FACTOR;
    s_turbo_active = 0;
}

uint8_t turbo_is_active(void) {
    return s_turbo_active;
}

#endif /* TURBO_MODE_ENABLED */
TURBO
    git -C "$wt_hot" add turbo.c
    ok "fw-hot-newness (feature/hot_newness, ~+30 -1)"

    # 3. fw-detached — worktree, detached HEAD, clean
    info "Creating session: fw-detached"
    (cd "$fw_repo" && ccmux_new fw-detached --worktree)
    ok "fw-detached (detached HEAD, clean)"

    # 4. cli-main — main branch, clean
    info "Creating session: cli-main"
    (cd "$cli_repo" && ccmux_new cli-main)
    ok "cli-main (main, clean)"

    # 5. cli-connectivity — worktree, feature branch with diffs
    info "Creating session: cli-connectivity"
    (cd "$cli_repo" && ccmux_new cli-connectivity --worktree)

    local wt_conn="$cli_repo/.worktrees/cli-connectivity"
    git -C "$wt_conn" checkout -b feature/updated_connectivity --quiet

    # Create new file connectivity.py and stage it
    cat > "$wt_conn/connectivity.py" << 'CONN'
"""Connectivity checker for remote devices."""

import socket
import time


class DeviceProbe:
    """Probe a device's network endpoint for liveness."""

    def __init__(self, host: str, port: int = 8080, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._history: list[bool] = []

    def ping(self) -> bool:
        """Return True if the device responds within timeout."""
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            ):
                self._history.append(True)
                return True
        except OSError:
            self._history.append(False)
            return False

    def uptime_ratio(self) -> float:
        """Return the fraction of successful pings so far."""
        if not self._history:
            return 0.0
        return sum(self._history) / len(self._history)
CONN
    git -C "$wt_conn" add connectivity.py

    # Append to tracked config.py
    cat >> "$wt_conn/config.py" << 'EXTRA'


CONNECTIVITY_DEFAULTS = {
    "probe_host": "192.168.1.100",
    "probe_port": 8080,
    "probe_timeout_s": 5.0,
    "retry_count": 3,
}
EXTRA
    ok "cli-connectivity (feature/updated_connectivity, ~+25 -0)"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    if [[ "${1:-}" == "--teardown" ]]; then
        teardown
    fi

    check_existing
    create_device_firmware
    create_cli_tools

    echo
    create_sessions

    echo
    info "Demo environment ready!"
    echo "  Repos:    $DEMO_DIR/{device_firmware,cli_tools}"
    echo "  Sessions: ${SESSIONS[*]}"
    echo
    echo "  Run with --teardown to clean up."
}

main "$@"
