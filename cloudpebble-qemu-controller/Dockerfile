# Pinned to linux/amd64 so the built qemu-pebble binary matches the
# (also amd64) runtime stage. Builds via Rosetta on Apple Silicon.
FROM --platform=linux/amd64 debian:bookworm AS qemu-builder

# Build deps for QEMU 10.1 Pebble fork (meson/ninja, Python 3)
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential ninja-build pkg-config python3-venv \
  libsdl2-dev libpixman-1-dev libglib2.0-dev \
  libpcre2-dev libffi-dev zlib1g-dev \
  nettle-dev \
  git ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Build QEMU from coredevices/qemu (default branch: pebble-10.1).
# build-dist.sh produces ./dist/bin/qemu-pebble against ./pc-bios/.
# Upstream script disables nettle, but we need it for VNC password auth
# (QEMU 10 dropped the built-in DES, so some crypto backend is required).
RUN git clone --depth 1 https://github.com/coredevices/qemu.git /qemu
WORKDIR /qemu
RUN sed -i 's|--disable-nettle||' build-dist.sh && bash build-dist.sh

# --- Runtime stage ---
# Pinned to linux/amd64 because stpyv8 (pypkjs dep) only publishes
# manylinux x86_64 wheels. On Apple Silicon this runs via Rosetta.
FROM --platform=linux/amd64 python:3.11-slim-bookworm

# Runtime libs for the QEMU 10 Pebble fork (SDL-linked; fork disables
# gnutls and fdt, so those are dropped from the previous image).
RUN apt-get update && apt-get install -y --no-install-recommends \
  libsdl2-2.0-0 libpixman-1-0 libglib2.0-0 libpcre2-8-0 libsndio7.0 \
  libnettle8 libhogweed6 \
  pulseaudio pulseaudio-utils \
  procps \
  curl git ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /run/cloudpebble-pipewire && chmod 0700 /run/cloudpebble-pipewire

# Install qemu-pebble binary plus its data dir (pc-bios keymaps etc.).
# QEMU looks up data relative to -L at runtime.
COPY --from=qemu-builder /qemu/dist/bin/qemu-pebble /usr/local/bin/qemu-pebble
COPY --from=qemu-builder /qemu/pc-bios /usr/local/share/qemu-pebble/pc-bios

# Download latest SDK and extract firmware images only
RUN SDK_INFO=$(curl -sf https://sdk.repebble.com/v1/files/sdk-core/4.9.169) && \
  SDK_URL=$(echo "$SDK_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['url'])") && \
  SDK_VERSION=$(echo "$SDK_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])") && \
  echo "Downloading SDK $SDK_VERSION from $SDK_URL..." && \
  curl -Lf "$SDK_URL" -o /tmp/sdk.tar.gz && \
  mkdir -p /sdk-images && \
  tar xzf /tmp/sdk.tar.gz -C /sdk-images --strip-components=2 "sdk-core/pebble/" && \
  rm /tmp/sdk.tar.gz && \
  echo "Firmware platforms:" && ls /sdk-images/

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install pypkjs from coredevices.
# stpyv8 (transitive dep) has a broken PEP 517 sdist (setup.py does
# `from settings import *` against a local sibling that isn't on sys.path in
# an isolated build). Force uv to use the prebuilt manylinux wheel instead.
RUN uv pip install --system --only-binary=stpyv8 git+https://github.com/coredevices/pypkjs.git

# pypkjs relies on requests/urllib3 internals that changed in urllib3 2.x.
# Pin to known-compatible versions so XMLHttpRequest works in emulator PKJS.
RUN uv pip install --system "requests<2.32" "urllib3<2"

# Fix pypkjs Python 3 bug: struct.unpack returns bytes but token from
# argparse is str, so auth comparison always fails. Decode bytes to str.
RUN sed -i 's/if token == self\.token:/if token.decode("utf-8") == self.token:/' \
  /usr/local/lib/python3.11/site-packages/pypkjs/runner/websocket.py

# Fix pypkjs safe_requests adapter for newer urllib3 PoolManager API.
RUN sed -i 's/def _new_pool(self, scheme, host, port):/def _new_pool(self, scheme, host, port, request_context=None):/' \
  /usr/local/lib/python3.11/site-packages/pypkjs/javascript/safe_requests.py

# Prefer IPv4 for pypkjs HTTP calls in cloud emulation to avoid IPv6 route stalls.
RUN sed -i 's/socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)/socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)/' \
  /usr/local/lib/python3.11/site-packages/pypkjs/javascript/safe_requests.py

# Replace pypkjs geolocation: use ip-api.com with user's real IP instead of
# server IP + offline GeoLiteCity.dat database.
COPY patch_geolocation.py /tmp/patch_geolocation.py
RUN python3 /tmp/patch_geolocation.py && rm /tmp/patch_geolocation.py

# Controller deps
ADD requirements.txt /tmp/requirements.txt
RUN uv pip install --system -r /tmp/requirements.txt

COPY . /code
WORKDIR /code

ENV QEMU_BIN=/usr/local/bin/qemu-pebble \
    QEMU_DATA_DIR=/usr/local/share/qemu-pebble/pc-bios \
    QEMU_IMAGE_ROOT=/sdk-images \
    QCON_PORT=80 \
    XDG_RUNTIME_DIR=/run/cloudpebble-pipewire \
    PULSE_SERVER=unix:/run/cloudpebble-pipewire/pulse/native

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80
CMD ["/entrypoint.sh"]
