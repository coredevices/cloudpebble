# CloudPebble QEMU Controller - Python 3.11 + pebble-tool
FROM python:3.11-slim-bookworm

# Install system dependencies including Node.js for SDK
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libpixman-1-0 \
    libglib2.0-0 \
    libpng16-16 \
    libjpeg62-turbo \
    libsdl1.2debian \
    libsdl2-2.0-0 \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x (LTS)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install pebble-tool (includes pypkjs, qemu-pebble)
RUN uv tool install pebble-tool

# Add pebble-tool to PATH
ENV PATH="/root/.local/share/uv/tools/pebble-tool/bin:/root/.local/bin:$PATH"

# Install Flask and dependencies for the controller
RUN pip install --no-cache-dir flask flask-cors flask-sock simple-websocket websocket-client websockify

# SDK will be installed at first run or mounted from host
# Create directory for SDK persistence
RUN mkdir -p /root/.pebble-sdk

# Copy controller code
WORKDIR /app
COPY controller_v2.py /app/controller.py
COPY requirements_py3.txt /app/requirements.txt

# Expose ports
EXPOSE 8001
EXPOSE 6080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run the controller (use system Python which has Flask installed)
CMD ["/usr/local/bin/python", "controller.py"]
