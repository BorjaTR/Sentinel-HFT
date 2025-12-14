# Sentinel-HFT Docker Image
# Multi-stage build for minimal final image

# === Build Stage ===
FROM ubuntu:24.04 AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    verilator \
    python3 \
    python3-pip \
    python3-venv \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy source
COPY . .

# Build RTL simulations
RUN make -C sim clean && make -C sim all
RUN make -C sim risk

# Install Python package
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -e ".[ai]"

# === Runtime Stage ===
FROM ubuntu:24.04

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    python3 \
    python3-venv \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy built simulations
COPY --from=builder /build/sim/obj_dir /app/sim/obj_dir

# Copy package
COPY --from=builder /build/host /app/host
COPY --from=builder /build/ai /app/ai
COPY --from=builder /build/protocol /app/protocol
COPY --from=builder /build/wind_tunnel /app/wind_tunnel
COPY --from=builder /build/cli /app/cli
COPY --from=builder /build/demo /app/demo

WORKDIR /app

# Set simulation path
ENV SENTINEL_HFT_SIM_DIR=/app/sim

# Default command
ENTRYPOINT ["sentinel-hft"]
CMD ["--help"]
