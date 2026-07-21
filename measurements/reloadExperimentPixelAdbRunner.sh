#!/usr/bin/env bash

###############################################################################
# PIXEL WIFI-ONLY CHROME AUTO-REFRESH TEST SCRIPT
#
# WHAT IT DOES
# -------
# - Connect to a Google Pixel via ADB over Wi-Fi.
# - Force Airplane Mode ON.
# - Force Wi-Fi ON.
# - Open Chrome to a configurable URL.
# - Refresh the page every N seconds forever.
# - Never intentionally close Chrome.
#
#
# ============================================================================
# ONE-TIME SETUP ON THE PIXEL
# ============================================================================
#
# 1. Enable Developer Options (likely already done):
#
#    Settings
#      -> About phone
#      -> Tap "Build number" 7 times
#
# 2. Enable Wireless Debugging:
#
#    Settings
#      -> System
#      -> Developer options
#      -> Wireless debugging
#
# 3. Tap:
#
#      "Pair device with pairing code"
#
#    The phone will show:
#
#      IP address
#      Pairing port
#      Pairing code
#
#
# ============================================================================
# ONE-TIME PAIRING ON LINUX
# ============================================================================
#
# Example:
#
#   adb pair 192.168.1.100:37125
#
# Enter the pairing code shown on the phone.
#
#
# ============================================================================
# CONNECT EACH TIME
# ============================================================================
#
# Example:
#
#   adb connect 192.168.1.100:42673
#
# Verify:
#
#   adb devices
#
# Expected:
#
#   List of devices attached
#   192.168.1.100:42673    device
#
#
# ============================================================================
# RUN
# ============================================================================
#
#   chmod +x $this
#   ./$this
#
#
# ============================================================================
# CONFIGURATION
# ============================================================================
#

set -e

###############################################################################
# CONFIG
###############################################################################

# https://images.pi.lan/wep.html, https://images.pi.lan/jpg.html,...
URL="${1}"

## autopower (if used)
AUTOPWR_ENABLED=1
AUTOPWR_DEVICE="autopower21"
AUTOPWR_PP="MCP1"

###############################################################################
# OUTPUT FOLDER (derived from URL)
###############################################################################

SAFE_NAME=$(echo "$URL" | sed 's#https\?://##' | tr '/' '_' | tr ':' '_')
OUTDIR="runs/$SAFE_NAME"

mkdir -p "$OUTDIR"

NUM_MEASUREMENTS=150
INTERVAL_SECONDS=5

CONFIG_TEMPLATE="config.txtpb.template"
CONFIG_FILE="$OUTDIR/config.txtpb"

TRACE_REMOTE="/data/misc/perfetto-traces/trace.perfetto-trace"
TRACE_LOCAL="$OUTDIR/trace.perfetto-trace"
REMOTE_CFG="/data/local/tmp/power_config.pbtxt"

# as perfetto uses time since boot, we cannot sync with autopower -> hacky intermediate csv needed
SYNC_LOG="$OUTDIR/sync_timeline.csv"
echo "i,host_ns" > "$SYNC_LOG"
###############################################################################
# DURATION
###############################################################################

DURATION_MS=$(( (NUM_MEASUREMENTS * INTERVAL_SECONDS + 10) * 1000 ))

echo "[0/7] duration_ms = $DURATION_MS"

###############################################################################
# BUILD CONFIG
###############################################################################

sed "s/duration_ms: <durms§§>/duration_ms: $DURATION_MS/g" \
    "$CONFIG_TEMPLATE" > "$CONFIG_FILE"

###############################################################################
# ADB CHECK
###############################################################################

echo "[1/7] Checking ADB..."
adb get-state >/dev/null

echo "[1.5/7] Forwarding Chrome DevTools..."
adb forward tcp:9222 localabstract:chrome_devtools_remote >/dev/null

# Clear Chrome's cache via CDP so the proxy always delivers a fresh response.
# This ensures clean A/B test runs without cross-contamination.
sleep 1
curl -s -X POST http://localhost:9222/devtools/page/Network.clearBrowserCache >/dev/null 2>&1 || true

###############################################################################
# RESET CHROME
###############################################################################

echo "[2/7] Starting Chrome..."

adb shell am force-stop com.android.chrome

adb shell am start \
  -a android.intent.action.VIEW \
  -d "$URL" \
  com.android.chrome >/dev/null

sleep 3

###############################################################################
# PUSH CONFIG
###############################################################################

echo "[3/7] Uploading config..."

adb push "$CONFIG_FILE" "$REMOTE_CFG" >/dev/null

###############################################################################
# [3.5/7] START AUTOPOWER (optional)
###############################################################################

if [ "$AUTOPWR_ENABLED" -eq 1 ]; then
    echo "[3.5/7] Starting Autopower measurement..."

    python3 -m autopowermgmt.cli \
        start \
        --device "$AUTOPWR_DEVICE" \
        --sampling 50 \
        --upload 1 \
        --pp "$AUTOPWR_PP"

    echo "Autopower started"
else
    echo "[3.5/7] Autopower disabled"
fi

###############################################################################
# START PERFETTO (PARALLEL)
###############################################################################

echo "[4/7] Starting Perfetto..."

adb shell "cat $REMOTE_CFG | perfetto -c - --txt -o $TRACE_REMOTE" >/dev/null 2>&1 &
PERFETTO_PID=$!

sleep 2

echo "[4.5/7] Starting CDP network collector..."

python3 chrome_netlog.py \
    --out "$OUTDIR/network_bytes.json" \
    --measurements "$NUM_MEASUREMENTS" &
CDP_PID=$!

###############################################################################
# WORKLOAD (PARALLEL TO TRACE)
###############################################################################

echo "[5/7] Running workload..."

START_TIME=$(date +%s)

for ((i=1; i<=NUM_MEASUREMENTS; i++))
do
    adb shell input keyevent KEYCODE_REFRESH >/dev/null 2>&1

    # ------------------------------------------------------------
    # SYNC MARKER
    # ------------------------------------------------------------
    NOW_NS=$(date +%s%N)

    echo "$i,$NOW_NS" >> "$SYNC_LOG"

    #adb shell "echo loop_${i}_${NOW_NS} > /sys/kernel/tracing/trace_marker"

    # ------------------------------------------------------------
    # SLEEP
    # ------------------------------------------------------------
    sleep "$INTERVAL_SECONDS"

    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TIME))

    if [ "$i" -gt 0 ]; then
        ETA_SEC=$(awk -v e="$ELAPSED" -v i="$i" -v total="$NUM_MEASUREMENTS" \
            'BEGIN {
                avg = e / i
                remaining = total - i
                print avg * remaining
            }')
    else
        ETA_SEC=0
    fi

    # convert safely to integer minutes/seconds (NO bash math on floats)
    ETA_MIN=$(awk -v s="$ETA_SEC" 'BEGIN {print int(s/60)}')
    ETA_REM_SEC=$(awk -v s="$ETA_SEC" 'BEGIN {print int(s%60)}')

    printf "\r[5/7] Running workload... %d/%d | ETA: %dm %02ds   " \
        "$i" "$NUM_MEASUREMENTS" "$ETA_MIN" "$ETA_REM_SEC"
done

echo ""

###############################################################################
# WAIT FOR PERFETTO TO FINISH WRITING
###############################################################################

echo "[6/7] Waiting for trace flush..."

# wait until file exists AND stabilizes
LAST_SIZE=0

for i in {1..30}
do
    SIZE=$(adb shell stat -c%s "$TRACE_REMOTE" 2>/dev/null || echo 0)

    if [ "$SIZE" -gt 0 ] && [ "$SIZE" -eq "$LAST_SIZE" ]; then
        echo "Trace stabilized at $SIZE bytes"
        break
    fi

    LAST_SIZE=$SIZE
    sleep 1
done

###############################################################################
# STOP PERFETTO (SAFE FALLBACK)
###############################################################################

adb shell pkill -SIGINT perfetto || true
sleep 2

###############################################################################
# VERIFY TRACE
###############################################################################

echo "[7/7] Verifying trace..."

adb shell ls -lh "$TRACE_REMOTE"

###############################################################################
# STOP AUTOPOWER (optional)
###############################################################################

if [ "$AUTOPWR_ENABLED" -eq 1 ]; then
    echo "[7/7] Stopping Autopower measurement..."

    python3 -m autopowermgmt.cli \
        stop \
        --device "$AUTOPWR_DEVICE" || true

    echo "Autopower stopped"
else
    echo "[7/7] Autopower disabled"
fi

###############################################################################
# PULL TRACE
###############################################################################

echo "Pulling trace..."

adb pull "$TRACE_REMOTE" "$TRACE_LOCAL" >/dev/null

echo "Trace saved: $TRACE_LOCAL"
echo "Waiting for python packet capture"
wait "$CDP_PID"
