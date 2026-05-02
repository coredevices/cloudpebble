#!/bin/sh
set -e

mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"

# Clean stale runtime state from previous container instances. Pulseaudio
# refuses to start if its pid file is still present, which breaks
# `docker compose restart` (the container's filesystem persists across
# restarts, so the dead pulseaudio's pid file lingers).
rm -rf "$XDG_RUNTIME_DIR/pulse"

# Plain pulseaudio. -n skips loading /etc/pulse/default.pa (which auto-
# detects ALSA/BT hardware that doesn't exist in the container and just
# spams warnings). We load only the unix socket protocol; null-sinks
# get loaded per-emulator via pactl. --exit-idle-time=-1 keeps the
# daemon alive even when no clients are connected. Running as root
# triggers a non-fatal warning that pulseaudio logs and ignores.
pulseaudio \
    -n --daemonize=no --exit-idle-time=-1 \
    -L "module-native-protocol-unix socket=$XDG_RUNTIME_DIR/pulse/native auth-anonymous=1" \
    -L "module-suspend-on-idle" &

# Wait for the pulse socket so QEMU's pa client can connect on first launch.
for i in $(seq 1 50); do
    [ -S "$XDG_RUNTIME_DIR/pulse/native" ] && break
    sleep 0.1
done

exec python controller.py
