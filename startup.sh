#!/bin/bash
# ═══════════════════════════════════════════════════════
# SPECTRICOM — SERVICE STARTUP
# Run: bash ~/spectricom-orchestrator/startup.sh
# Options:
#   startup.sh          ← start all services
#   startup.sh status   ← check what's running
#   startup.sh stop     ← stop all services
# ═══════════════════════════════════════════════════════

ORCH=~/spectricom-orchestrator
YORSIE=~/spectricom-dev-pipeline/yorsie
GATEWAY=~/spectricom-gateway

CMD="${1:-start}"

# Colors
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'; B='\033[1m'

check_port() {
    ss -tlnp 2>/dev/null | grep -q ":$1 " && return 0 || return 1
}

check_process() {
    pgrep -f "$1" > /dev/null 2>&1 && return 0 || return 1
}

status() {
    echo -e "\n${B}═══ SPECTRICOM SERVICE STATUS ═══${N}\n"

    # 1. Yorsie dev server
    if check_port 5173; then
        echo -e "  ${G}✅${N} Yorsie dev server          localhost:5173"
    else
        echo -e "  ${R}❌${N} Yorsie dev server          NOT RUNNING"
    fi

    # 2. Cloudflare tunnel
    if check_process "cloudflared"; then
        echo -e "  ${G}✅${N} Cloudflare tunnel          app.yorsie.com → :5173"
    else
        echo -e "  ${R}❌${N} Cloudflare tunnel          NOT RUNNING"
    fi

    # 3. Gateway
    if check_port 3003; then
        echo -e "  ${G}✅${N} Spectricom Gateway         localhost:3003"
    else
        echo -e "  ${R}❌${N} Spectricom Gateway         NOT RUNNING"
    fi

    # 4. Ops Dashboard
    if check_port 8091; then
        echo -e "  ${G}✅${N} Ops Dashboard              localhost:8091"
    else
        echo -e "  ${R}❌${N} Ops Dashboard              NOT RUNNING"
    fi

    # 5. Drive Bridge
    if [ -f "$ORCH/bridge.pid" ] && kill -0 $(cat "$ORCH/bridge.pid") 2>/dev/null; then
        echo -e "  ${G}✅${N} Drive Bridge               PID $(cat $ORCH/bridge.pid)"
    else
        echo -e "  ${R}❌${N} Drive Bridge               NOT RUNNING"
    fi

    # 6. Drive Watcher
    if [ -f "$ORCH/drive-watcher.pid" ] && kill -0 $(cat "$ORCH/drive-watcher.pid") 2>/dev/null; then
        echo -e "  ${G}✅${N} Drive Watcher              PID $(cat $ORCH/drive-watcher.pid)"
    else
        echo -e "  ${R}❌${N} Drive Watcher              NOT RUNNING"
    fi

    echo ""
}

start() {
    echo -e "\n${B}═══ SPECTRICOM SERVICE STARTUP ═══${N}\n"

    # 1. Yorsie dev server
    if check_port 5173; then
        echo -e "  ${Y}⏭️${N}  Yorsie dev server         already running"
    else
        echo -e "  ${G}🚀${N} Starting Yorsie dev server..."
        cd "$YORSIE" && nohup npm run dev > /tmp/yorsie-dev.log 2>&1 &
        sleep 2
        if check_port 5173; then
            echo -e "  ${G}✅${N} Yorsie dev server          localhost:5173"
        else
            echo -e "  ${R}❌${N} Yorsie failed to start — check /tmp/yorsie-dev.log"
        fi
    fi

    # 2. Cloudflare tunnel
    if check_process "cloudflared"; then
        echo -e "  ${Y}⏭️${N}  Cloudflare tunnel         already running"
    else
        echo -e "  ${G}🚀${N} Starting Cloudflare tunnel..."
        nohup ~/cloudflared tunnel run > /tmp/cloudflared.log 2>&1 &
        sleep 2
        if check_process "cloudflared"; then
            echo -e "  ${G}✅${N} Cloudflare tunnel          app.yorsie.com"
        else
            echo -e "  ${R}❌${N} Cloudflare tunnel failed — check /tmp/cloudflared.log"
        fi
    fi

    # 3. Gateway
    if check_port 3003; then
        echo -e "  ${Y}⏭️${N}  Spectricom Gateway        already running"
    else
        echo -e "  ${G}🚀${N} Starting Gateway..."
        cd "$GATEWAY" && nohup npm run dev > /tmp/gateway.log 2>&1 &
        sleep 3
        if check_port 3003; then
            echo -e "  ${G}✅${N} Spectricom Gateway         localhost:3003"
        else
            echo -e "  ${R}❌${N} Gateway failed — check /tmp/gateway.log"
        fi
    fi

    # 4. Ops Dashboard
    if check_port 8091; then
        echo -e "  ${Y}⏭️${N}  Ops Dashboard             already running"
    else
        echo -e "  ${G}🚀${N} Starting Ops Dashboard..."
        cd "$ORCH" && nohup python3 orch-dashboard.py > /tmp/orch-dashboard.log 2>&1 &
        sleep 1
        if check_port 8091; then
            echo -e "  ${G}✅${N} Ops Dashboard              localhost:8091"
        else
            echo -e "  ${R}❌${N} Dashboard failed — check /tmp/orch-dashboard.log"
        fi
    fi

    # 5. Drive Bridge
    if [ -f "$ORCH/bridge.pid" ] && kill -0 $(cat "$ORCH/bridge.pid") 2>/dev/null; then
        echo -e "  ${Y}⏭️${N}  Drive Bridge              already running"
    else
        echo -e "  ${G}🚀${N} Starting Drive Bridge..."
        cd "$ORCH" && python3 drive-bridge.py start
    fi

    # 6. Drive Watcher
    if [ -f "$ORCH/drive-watcher.pid" ] && kill -0 $(cat "$ORCH/drive-watcher.pid") 2>/dev/null; then
        echo -e "  ${Y}⏭️${N}  Drive Watcher             already running"
    else
        if [ -f "$ORCH/drive-watcher.py" ]; then
            echo -e "  ${G}🚀${N} Starting Drive Watcher..."
            cd "$ORCH" && python3 drive-watcher.py start
            echo ""
        else
            echo -e "  ${Y}⏭️${N}  Drive Watcher             not installed"
        fi
    fi

    echo ""
    echo -e "${B}  URLs:${N}"
    echo "    Yorsie:     http://localhost:5173"
    echo "    Yorsie:     https://app.yorsie.com"
    echo "    Dashboard:  http://localhost:8091"
    echo "    Gateway:    http://localhost:3003"
    echo ""
}

stop() {
    echo -e "\n${B}═══ SPECTRICOM SERVICE SHUTDOWN ═══${N}\n"

    # Yorsie dev
    pkill -f "vite.*yorsie" 2>/dev/null && echo -e "  ${G}✅${N} Yorsie stopped" || echo -e "  ${Y}—${N}  Yorsie was not running"

    # Cloudflare
    pkill -f "cloudflared" 2>/dev/null && echo -e "  ${G}✅${N} Cloudflare stopped" || echo -e "  ${Y}—${N}  Cloudflare was not running"

    # Gateway
    pkill -f "tsx.*gateway" 2>/dev/null && echo -e "  ${G}✅${N} Gateway stopped" || echo -e "  ${Y}—${N}  Gateway was not running"

    # Dashboard
    pkill -f "orch-dashboard" 2>/dev/null && echo -e "  ${G}✅${N} Dashboard stopped" || echo -e "  ${Y}—${N}  Dashboard was not running"

    # Bridge
    cd "$ORCH" && python3 drive-bridge.py stop 2>/dev/null || echo -e "  ${Y}—${N}  Bridge was not running"

    # Watcher
    if [ -f "$ORCH/drive-watcher.pid" ]; then
        kill $(cat "$ORCH/drive-watcher.pid") 2>/dev/null && rm "$ORCH/drive-watcher.pid" && echo -e "  ${G}✅${N} Watcher stopped" || echo -e "  ${Y}—${N}  Watcher was not running"
    fi

    echo ""
}

case "$CMD" in
    start)  start ;;
    status) status ;;
    stop)   stop ;;
    *)      echo "Usage: startup.sh [start|status|stop]" ;;
esac
