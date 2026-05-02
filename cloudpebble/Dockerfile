FROM python:3.11-slim-trixie
LABEL maintainer="CloudPebble Contributors"

ENV NPM_CONFIG_LOGLEVEL=info NODE_VERSION=20.11.0 DJANGO_VERSION=4.2 NODEJS_CHECK_SIGNATURES=no

# Node stuff.
RUN apt-get update && apt-get install -y curl && \
  curl -SLO "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.gz" && \
  curl -SLO "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt.asc" && \
  grep " node-v$NODE_VERSION-linux-x64.tar.gz\$" SHASUMS256.txt.asc | sha256sum -c - && \
  tar -xzf "node-v$NODE_VERSION-linux-x64.tar.gz" -C /usr/local --strip-components=1 && \
  rm "node-v$NODE_VERSION-linux-x64.tar.gz" SHASUMS256.txt.asc

RUN npm install -g jshint@2.13.6 typescript@3.9.10

# Django stuff + emulator dependencies
RUN apt-get update && apt-get install -y \
    gettext \
    postgresql-client libpq-dev \
    gcc \
    make \
    bzip2 \
    git \
    libc6-dev \
    libfreetype6 \
    libfdt1 \
    libglib2.0-0 \
  --no-install-recommends && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

# CloudPebble stuff
RUN npm install -g bower@1.8.14 && echo '{"allow_root": true}' > ~/.bowerrc

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install pebble-tool via uv
RUN uv tool install pebble-tool --python 3.11

# Ensure pebble is in PATH
ENV PATH="/root/.local/share/uv/tools/pebble-tool/bin:$PATH"

# Work around pebble-tool progress bar overflow during SDK downloads.
# Keep using latest pebble-tool without pinning, but clamp update values so
# transient content-length mismatches don't fail the build.
RUN python - <<'PY'
from pathlib import Path
import re

manager = Path("/root/.local/share/uv/tools/pebble-tool/lib/python3.11/site-packages/pebble_tool/sdk/manager.py")
text = manager.read_text()
old = "bar.update(bar.currval + len(content))"
new = "bar.update(min(getattr(bar, 'max_value', getattr(bar, 'maxval', bar.currval + len(content))), bar.currval + len(content)))"

if old in text:
    manager.write_text(text.replace(old, new))
else:
    # Fallback for minor upstream formatting differences.
    patched = re.sub(
        r"bar\.update\(\s*bar\.currval\s*\+\s*len\(content\)\s*\)",
        "bar.update(min(getattr(bar, 'max_value', getattr(bar, 'maxval', bar.currval + len(content))), bar.currval + len(content)))",
        text,
        count=1,
    )
    if patched == text:
        raise RuntimeError("Could not patch pebble_tool/sdk/manager.py progress update line")
    manager.write_text(patched)
PY

# Install Pebble SDK (downloads SDK + toolchain + QEMU)
RUN pebble sdk install 4.9.169
RUN pebble sdk activate 4.9.169

# Set up SDK paths for CloudPebble
ENV PEBBLE_SDK_PATH=/root/.pebble-sdk
ENV PATH="${PEBBLE_SDK_PATH}/SDKs/current/toolchain/arm-none-eabi/bin:$PATH"

ADD requirements.txt /tmp/requirements.txt
# Use Python 3.11 from the base image directly
RUN /usr/local/bin/pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /code
WORKDIR /code

# Keep tutorial/example repos synced to latest upstream at image build time.
# This is intentionally after COPY so each new app commit invalidates this layer.
RUN mkdir -p /opt && \
  if [ -d "/opt/pebble-examples/.git" ]; then \
    git -C "/opt/pebble-examples" fetch --depth 1 origin main && \
    git -C "/opt/pebble-examples" reset --hard "origin/main"; \
  else \
    rm -rf /opt/pebble-examples && \
    git clone --depth 1 --branch main "https://github.com/Moddable-OpenSource/pebble-examples.git" "/opt/pebble-examples"; \
  fi && \
  if [ -d "/opt/watchface-tutorial/.git" ]; then \
    git -C "/opt/watchface-tutorial" fetch --depth 1 origin main && \
    git -C "/opt/watchface-tutorial" reset --hard "origin/main"; \
  else \
    rm -rf /opt/watchface-tutorial && \
    git clone --depth 1 --branch main "https://github.com/coredevices/alloy-watchface-tutorial.git" "/opt/watchface-tutorial"; \
  fi && \
  if [ -d "/opt/c-watchface-tutorial/.git" ]; then \
    git -C "/opt/c-watchface-tutorial" fetch --depth 1 origin main && \
    git -C "/opt/c-watchface-tutorial" reset --hard "origin/main"; \
  else \
    rm -rf /opt/c-watchface-tutorial && \
    git clone --depth 1 --branch main "https://github.com/coredevices/c-watchface-tutorial.git" "/opt/c-watchface-tutorial"; \
  fi

# Bower is awful. Run bower directly instead of Django management command
RUN rm -rf bower_components && \
  bower install --allow-root \
    "https://github.com/krisk/Fuse.git#2ec2f2c40059e135cabf2b01c8c3f96f808b8809" \
    "jquery#~2.1.3" \
    "underscore" \
    "backbone" \
    "text-encoding" \
    "jshint/jshint" \
    "html.sortable#~0.3.1" \
    "alexgorbatchev/jquery-textext" \
    "codemirror#4.2.0" \
    "bluebird#3.3.4" \
    "kanaka/noVNC#v0.5"

RUN SECRET_KEY=build-placeholder /usr/local/bin/python manage.py compilemessages

RUN make -C /code/c-preload

CMD ["sh", "docker_start.sh"]
