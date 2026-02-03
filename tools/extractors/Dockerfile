# Build AzerothCore map extractor tools (Linux) from local source.
#
# Build:
#   docker build -t ac-tools -f tools/extractors/Dockerfile D:\Test\azerothcore-wotlk
#
# Run extraction:
#   docker run --rm -v "G:\WoW AzerothCore\Data:/wow/Data:ro" -v "D:\Test\wow-pywowlib\tools\extractors\output:/output" ac-tools
#
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake make g++ \
    libmysqlclient-dev libssl-dev libbz2-dev libreadline-dev \
    libncurses-dev libboost-all-dev \
    ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Copy in the local AzerothCore source (build context = repo root)
COPY . /src
WORKDIR /src/build

# Build ONLY the map tools, skip server/scripts/dbimport entirely
RUN cmake .. \
    -DCMAKE_INSTALL_PREFIX=/opt/ac \
    -DCMAKE_BUILD_TYPE=Release \
    -DTOOLS_BUILD=maps-only \
    -DSERVERS=0 \
    -DSCRIPTS=none \
    -DAPPS_BUILD=none \
    && make -j$(nproc) \
    && make install

# ---- Slim runtime stage ----
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmysqlclient21 libssl3 libbz2-1.0 \
    libboost-system1.74.0 libboost-filesystem1.74.0 \
    libboost-program-options1.74.0 libboost-iostreams1.74.0 \
    && rm -rf /var/lib/apt/lists/*

# Binary names use underscores in AzerothCore
COPY --from=builder /opt/ac/bin/map_extractor    /usr/local/bin/
COPY --from=builder /opt/ac/bin/vmap4_extractor  /usr/local/bin/
COPY --from=builder /opt/ac/bin/vmap4_assembler  /usr/local/bin/
COPY --from=builder /opt/ac/bin/mmaps_generator  /usr/local/bin/
COPY --from=builder /opt/ac/bin/mmaps-config.yaml /usr/local/bin/

WORKDIR /wow
