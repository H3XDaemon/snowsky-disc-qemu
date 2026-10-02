# Reproducible environment for emulating the FiiO Snowsky Disc firmware
# (Ingenic X2000, MIPS32 LE) under qemu-user on any host via Docker.
#
# Build:  docker build -t snowsky-disc-qemu emulator/docker/
# Run:    see emulator/docs/running.md  (needs --privileged for binfmt_misc + POSIX mqueue + qemu VA reservation)
#
# Works on both amd64 and arm64 Docker hosts (Debian is multi-arch; qemu-user-static
# runs the MIPS guest regardless of host arch).
FROM debian:12@sha256:6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443

ENV DEBIAN_FRONTEND=noninteractive
# One package root for python -m entry points (source is mounted, not baked in).
ENV PYTHONPATH=/repo

# Signed, dated package indexes pin transitive dependencies on both host architectures.
# HTTP bootstraps ca-certificates; apt still verifies Debian signatures and package hashes.
COPY debian.sources /etc/apt/sources.list.d/debian.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
      qemu-user-static \
      binfmt-support \
      squashfs-tools \
      gcc-mipsel-linux-gnu \
      binutils-mipsel-linux-gnu \
      libc6-dev-mipsel-cross \
      gdb-multiarch \
      strace \
      sqlite3 \
      dosfstools \
      exfatprogs \
      sox \
      python3 \
      python3-aiohttp \
      nodejs \
      openssl \
      xxd \
      file \
      procps \
      util-linux \
      iproute2 \
      netcat-openbsd \
      curl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# /work holds the extracted rootfs and runtime state (mount a host dir or volume here
# so it survives container restarts). /repo is this repository (mount read-write).
WORKDIR /work

# util-linux supplies setpriv: emulator/scripts/lib.sh drops dangerous capabilities for
# MIPS guests and their children. Network setup uses iproute2; no manual packages.
RUN command -v setpriv && command -v ip
# Native WebSocket bridge/client, outside the MIPS rootfs; installed only at build time.
RUN python3 -c "import aiohttp; print('WebSocket transport: aiohttp', aiohttp.__version__)"

CMD ["/bin/bash"]
