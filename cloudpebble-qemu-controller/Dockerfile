FROM debian:bullseye AS qemu-builder

# Build deps for QEMU (needs Python 3 for configure)
RUN apt-get update && apt-get install -y \
  libglib2.0-dev libpixman-1-dev libfdt-dev gnutls-dev \
  curl git make gcc pkg-config python3 python3-venv python3-pip \
  && rm -rf /var/lib/apt/lists/*

# Build QEMU from coredevices/qemu
RUN git clone --depth 1 https://github.com/coredevices/qemu.git /qemu && \
  cd /qemu && \
  ./configure --python=python3 --extra-ldflags=-g --enable-debug --disable-werror \
    --target-list="arm-softmmu" && \
  make clean && make -j$(nproc)

# --- Runtime stage ---
FROM python:3.11-slim-bookworm

# Runtime deps for QEMU
RUN apt-get update && apt-get install -y \
  libglib2.0-0 libpixman-1-0 libfdt1 libgnutls30 \
  curl git \
  && rm -rf /var/lib/apt/lists/*

# Copy built QEMU from builder
COPY --from=qemu-builder /qemu /qemu

# Download latest SDK and extract firmware images only
RUN SDK_INFO=$(curl -sf https://sdk.repebble.com/v1/files/sdk-core/4.9.148) && \
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

# Install pypkjs from coredevices
RUN uv pip install --system git+https://github.com/coredevices/pypkjs.git

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

ENV QEMU_DIR=/qemu \
    QEMU_BIN=/qemu/arm-softmmu/qemu-system-arm \
    QEMU_IMAGE_ROOT=/sdk-images \
    QCON_PORT=80

EXPOSE 80
CMD ["python", "controller.py"]
