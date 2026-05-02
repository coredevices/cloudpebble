FROM python:3.11-slim-bookworm AS ycmd-builder

# Build dependencies for ycmd with clang-completer
RUN apt-get update && apt-get install -y \
  cmake build-essential libncurses-dev git \
  && rm -rf /var/lib/apt/lists/*

# Clone and build ycmd (ycm-core fork, Python 3 compatible)
RUN git clone https://github.com/ycm-core/ycmd.git /ycmd && \
  cd /ycmd && \
  git reset --hard 6297cad7dfffd2a117275b4fe8a867581b4ab236 && \
  git submodule update --init --recursive && \
  python3 build.py --clang-completer --force-sudo

# --- Runtime stage ---
FROM python:3.11-slim-bookworm

# Runtime deps
RUN apt-get update && apt-get install -y \
  libncurses6 curl git bzip2 \
  && rm -rf /var/lib/apt/lists/*

# Copy built ycmd from builder
COPY --from=ycmd-builder /ycmd /ycmd

# Grab the ARM toolchain (for stdlib headers used by completions)
RUN curl -o /tmp/arm-cs-tools.tar https://cloudpebble-vagrant.s3.amazonaws.com/arm-cs-tools-stripped.tar && \
  tar -xf /tmp/arm-cs-tools.tar -C / && rm /tmp/arm-cs-tools.tar

# Node.js 16.x (for pebble npm dependencies)
ENV NODE_VERSION=16.20.2 NPM_CONFIG_LOGLEVEL=info
RUN curl -SLO "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.gz" \
  && tar -xzf "node-v$NODE_VERSION-linux-x64.tar.gz" -C /usr/local --strip-components=1 \
  && rm "node-v$NODE_VERSION-linux-x64.tar.gz"

# Pebble SDK (for include headers only – must match the version used by the
# build system so that YCM sees headers for all supported platforms including
# gabbro and flint).
RUN SDK_INFO=$(curl -sf https://sdk.repebble.com/v1/files/sdk-core/4.9.169) && \
  SDK_URL=$(echo "$SDK_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['url'])") && \
  curl -Lf "$SDK_URL" -o /tmp/sdk.tar.gz && \
  mkdir -p /sdk3 && \
  tar xzf /tmp/sdk.tar.gz -C /sdk3 --strip-components=1 "sdk-core/" && \
  rm /tmp/sdk.tar.gz

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Python dependencies
ADD requirements.txt /tmp/requirements.txt
RUN uv pip install --system -r /tmp/requirements.txt

COPY . /code
WORKDIR /code

ENV PATH="$PATH:/arm-cs-tools/bin" YCMD_PEBBLE_SDK3=/sdk3/ \
  YCMD_STDLIB=/arm-cs-tools/arm-none-eabi/include/ \
  DEBUG=yes YCMD_PORT=80 YCMD_BINARY=/ycmd/ycmd/__main__.py \
  YCMD_DEFAULT_SETTINGS=/ycmd/ycmd/default_settings.json

ENV PATH="$PATH:/ycmd"

EXPOSE 80
CMD ["python", "proxy.py"]
