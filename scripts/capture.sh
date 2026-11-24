#!/usr/bin/env bash
# Usage: sudo bash scripts/capture.sh start TAG | stop
# Capture inside a writable temporary directory, then copy completed PCAPNGs
# into results/pcap. Compatible with tools/run.py evidence.
set -Eeuo pipefail
source "$(dirname "$0")/lib.sh"
need_root

OUT="$ROOT/results/pcap"
STATE="$OUT/.capture-state"
mkdir -p "$OUT"

stop_captures() {
    if [[ ! -d "$STATE" ]]; then
        echo "No active capture state found."
        return 0
    fi

    local file pid label source_path dest_path tempdir failures=0
    shopt -s nullglob

    # Ask dumpcap to close its output file cleanly before copying it.
    for file in "$STATE"/*.pid; do
        pid=$(<"$file")
        if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
            echo "Stopping capture PID $pid ..."
            kill -INT "$pid" 2>/dev/null || true
        fi
    done

    for file in "$STATE"/*.pid; do
        pid=$(<"$file")
        if [[ "$pid" =~ ^[0-9]+$ ]]; then
            for ((attempt=0; attempt<30; attempt++)); do
                if ! kill -0 "$pid" 2>/dev/null || [[ "$(ps -o stat= -p "$pid" 2>/dev/null || true)" == Z* ]]; then
                    break
                fi
                sleep 0.1
            done
            if kill -0 "$pid" 2>/dev/null && [[ "$(ps -o stat= -p "$pid" 2>/dev/null || true)" != Z* ]]; then
                echo "WARNING: Capture PID $pid did not exit after SIGINT; sending SIGTERM" >&2
                kill -TERM "$pid" 2>/dev/null || true
                sleep 1
            fi
        fi
    done

    for file in "$STATE"/*.source; do
        label=${file##*/}
        label=${label%.source}
        source_path=$(<"$file")
        dest_path=$(<"$STATE/$label.dest")
        if [[ -s "$source_path" ]]; then
            if cp -- "$source_path" "$dest_path"; then
                chmod 644 "$dest_path"
                echo "Saved: $dest_path ($(stat -c %s "$dest_path") bytes)"
            else
                echo "ERROR: Could not copy $source_path to $dest_path" >&2
                failures=1
            fi
        else
            echo "WARNING: No capture data for $label at $source_path" >&2
            failures=1
        fi
    done

    tempdir=$(<"$STATE/tempdir")
    # Do not delete the temporary evidence when copying fails.
    if (( failures == 0 )); then
        rm -rf -- "$tempdir" "$STATE"
    else
        echo "Temporary evidence retained at $tempdir" >&2
        echo "State retained at $STATE for inspection or retrying 'stop'." >&2
    fi
    return "$failures"
}

start_capture() {
    local tag=${1:?Missing tag} ns iface label pid source_path dest_path log spec tempdir
    [[ "$tag" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "ERROR: Invalid tag: $tag" >&2; return 1; }
    command -v dumpcap >/dev/null || { echo "ERROR: dumpcap not installed" >&2; return 1; }
    [[ ! -e "$STATE" ]] || { echo "ERROR: Existing capture session. Run '$0 stop' first." >&2; return 1; }
    mkdir -m 700 "$STATE"

    # dumpcap commonly drops privileges. A fresh unpredictable directory under
    # /tmp ensures it can write without granting access to the source tree.
    tempdir=$(mktemp -d /tmp/ftp-nat-capture.XXXXXXXX)
    chmod 1777 "$tempdir"
    printf '%s\n' "$tempdir" > "$STATE/tempdir"

    local -a specs=("$NS_R1:eth-in:r1-inside" "$NS_R1:eth-out:r1-outside" "$NS_R2:eth-srv:r2-server")
    for spec in "${specs[@]}"; do
        IFS=: read -r ns iface label <<< "$spec"
        source_path="$tempdir/${tag}__${label}.pcapng"
        dest_path="$OUT/${tag}__${label}.pcapng"
        log="$OUT/${tag}__${label}.log"

        if ! ip netns exec "$ns" ip link show "$iface" >/dev/null 2>&1; then
            echo "ERROR: Interface $ns/$iface is missing" >&2
            stop_captures || true
            return 1
        fi

        # Keep the full filename after -w (not just the directory).
        ( exec ip netns exec "$ns" dumpcap -q -i "$iface" -w "$source_path" ) >"$log" 2>&1 &
        pid=$!
        printf '%s\n' "$pid" > "$STATE/$label.pid"
        printf '%s\n' "$source_path" > "$STATE/$label.source"
        printf '%s\n' "$dest_path" > "$STATE/$label.dest"
        echo "Starting $ns/$iface: PID $pid -> $source_path"
    done

    sleep 2
    local failed=0
    for spec in "${specs[@]}"; do
        IFS=: read -r ns iface label <<< "$spec"
        pid=$(<"$STATE/$label.pid")
        source_path=$(<"$STATE/$label.source")
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "ERROR: Capture for $label exited at startup:" >&2
            cat "$OUT/${tag}__${label}.log" >&2
            failed=1
        elif [[ ! -f "$source_path" ]]; then
            echo "ERROR: No capture file created for $label:" >&2
            cat "$OUT/${tag}__${label}.log" >&2
            failed=1
        fi
    done
    if (( failed )); then
        stop_captures || true
        return 1
    fi
    echo "All three captures are active: $tag"
}

case "${1:-}" in
    start) [[ $# -eq 2 ]] || { echo "Usage: $0 start TAG | stop" >&2; exit 2; }; start_capture "$2" ;;
    stop) [[ $# -eq 1 ]] || { echo "Usage: $0 start TAG | stop" >&2; exit 2; }; stop_captures ;;
    *) echo "Usage: $0 start TAG | stop" >&2; exit 2 ;;
esac
