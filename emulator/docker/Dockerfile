# Reproducible environment for emulating the FiiO Snowsky Disc firmware
# (Ingenic X2000, MIPS32 LE) under qemu-user on any host via Docker.
#
# Build:  docker build -t snowsky-disc-qemu emulator/docker/
# Run:    see emulator/docs/running.md  (needs --privileged for binfmt_misc + POSIX mqueue + qemu VA reservation)
#
# Works on both amd64 and arm64 Docker hosts (Debian is multi-arch; qemu-user-static
# runs the MIPS guest regardless of host arch).

# Stage 1: Debian's own qemu 7.2 source, rebuilt for mipsel user mode with one patch
# (qemu/snowsky-disc-devices.patch): a statically linked guest program gets the
# emulated framebuffer/input ioctls that the preload shim gives dynamic ones, and
# getsockopt(SO_ERROR) returns guest errnos. The dated snapshot below pins the source;
# the explicit version makes a snapshot change fail here, not at runtime.
FROM debian:12@sha256:6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443 AS qemu
ENV DEBIAN_FRONTEND=noninteractive
COPY debian.sources /etc/apt/sources.list.d/debian.sources
RUN sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/debian.sources \
 && apt-get update && apt-get install -y --no-install-recommends \
      dpkg-dev build-essential ninja-build meson python3 pkg-config \
      libglib2.0-dev libpcre2-dev zlib1g-dev libffi-dev libmount-dev libblkid-dev \
      libselinux1-dev libcap-ng-dev libattr1-dev \
 && mkdir /build && cd /build \
 && apt-get source --only-source qemu=1:7.2+dfsg-7+deb12u18 \
 && rm -rf /var/lib/apt/lists/*
COPY qemu/snowsky-disc-devices.patch /build/
RUN cd /build/qemu-7.2+dfsg \
 && patch -p1 < ../snowsky-disc-devices.patch \
 && ./configure --static --disable-system --disable-tools --disable-guest-agent --disable-docs \
      --disable-werror --target-list=mipsel-linux-user \
      --with-pkgversion='Debian 1:7.2+dfsg-7+deb12u18, snowsky-disc-devices' \
 && ninja -C build qemu-mipsel \
 # The binfmt entry is shared by the Docker VM and the kernel keeps the interpreter it
 # opened at registration: a path that names the build lets setup see a rebuilt one.
 && build="$(sha256sum build/qemu-mipsel | cut -c1-12)" \
 && install -D -m 755 build/qemu-mipsel "/out/usr/local/lib/qemu-mipsel-$build/qemu-mipsel-static" \
 && mkdir -p /out/usr/local/bin \
 && ln -s "../lib/qemu-mipsel-$build/qemu-mipsel-static" /out/usr/local/bin/qemu-mipsel-static \
 && /out/usr/local/bin/qemu-mipsel-static -version | grep -q snowsky-disc-devices

# Stage 2: the runtime image.
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

# The patched interpreter (stage 1): /usr/local/bin/qemu-mipsel-static links to the build-named
# file that emulator/scripts/lib.sh registers; Debian's /usr/bin/qemu-mipsel-static stays for
# QEMU=/usr/bin/qemu-mipsel-static.
COPY --from=qemu /out/usr/local/ /usr/local/
RUN readlink -f /usr/local/bin/qemu-mipsel-static | grep -q '^/usr/local/lib/qemu-mipsel-[0-9a-f]*/qemu-mipsel-static$' \
 && /usr/local/bin/qemu-mipsel-static -version | grep -q snowsky-disc-devices

# /work holds the extracted rootfs and runtime state (mount a host dir or volume here
# so it survives container restarts). /repo is this repository (mount read-write).
WORKDIR /work

# util-linux supplies setpriv: emulator/scripts/lib.sh drops dangerous capabilities for
# MIPS guests and their children. Network setup uses iproute2; no manual packages.
RUN command -v setpriv && command -v ip
# Native WebSocket bridge/client, outside the MIPS rootfs; installed only at build time.
RUN python3 -c "import aiohttp; print('WebSocket transport: aiohttp', aiohttp.__version__)"

CMD ["/bin/bash"]
