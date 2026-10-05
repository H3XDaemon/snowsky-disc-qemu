#!/usr/bin/env python3
"""Opt-in host-side LAN exposure of the loopback viewer, for one trusted client.

Run on the host, NOT inside the container. The viewer has no authentication: the
allowed address can drive the screen, the physical buttons and power. An IP filter
is not authentication. No persistent service or automatic startup.

This exists because a Docker published port is not always reachable from the LAN.
On the Windows 11 host with Docker Desktop and WSL where this was written, a port
published to 0.0.0.0 or to the LAN address was not reachable from another device,
while binding the LAN address here did work. Keep the viewer's own publication on
loopback. Needs Python 3.11 or newer (asyncio.timeout).

  python3 -m viewer.lan_relay --interface 192.0.2.10 --allow-client 192.0.2.50
"""
import argparse
import asyncio
import contextlib
import ipaddress

# A diagnostic adapter policy, not a viewer timeout. Each direction is bounded
# independently; the frame stream is long-lived, so this is generous.
READ_IDLE_TIMEOUT = 300


def interface_address(value):
    """An IPv4 literal, so a hostname can never widen the bind or the allowlist."""
    return str(ipaddress.IPv4Address(value))


async def pump(reader, writer):
    while True:
        async with asyncio.timeout(READ_IDLE_TIMEOUT):
            data = await reader.read(65536)
        if not data:
            if writer.can_write_eof():
                writer.write_eof()
            return
        writer.write(data)
        async with asyncio.timeout(30):
            await writer.drain()


class Relay:
    def __init__(self, allowed, upstream_port):
        self.allowed = interface_address(allowed)
        self.upstream_port = upstream_port
        self.tasks = set()

    async def handle(self, reader, writer):
        peer = writer.get_extra_info('peername')
        if not peer or peer[0] != self.allowed:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            return
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        pumps = []
        try:
            remote, upstream = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', self.upstream_port), 3)
            pumps = [asyncio.create_task(pump(reader, upstream)),
                     asyncio.create_task(pump(remote, writer))]
            await asyncio.gather(*pumps)
        except (OSError, asyncio.TimeoutError):
            print('viewer: connection closed/unavailable', flush=True)
        finally:
            for child in pumps:
                child.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (writer, upstream):
                if stream is not None:
                    stream.close()
                    with contextlib.suppress(OSError):
                        await stream.wait_closed()
            self.tasks.discard(task)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run(interface, port, allowed, upstream_port, seconds):
    relay = Relay(allowed, upstream_port)
    server = await asyncio.start_server(relay.handle, interface, port)
    try:
        print(f'viewer relay on {interface}:{port} -> 127.0.0.1:{upstream_port}; '
              f'only {allowed} allowed; auto-stop in {seconds}s. No authentication.', flush=True)
        await asyncio.sleep(seconds)
    finally:
        server.close()
        await relay.close()
        await server.wait_closed()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--interface', required=True, type=interface_address)
    parser.add_argument('--allow-client', required=True, type=interface_address)
    parser.add_argument('--port', type=int, default=8100)
    parser.add_argument('--upstream-port', type=int, default=8080,
                        help="the viewer's published loopback port")
    parser.add_argument('--seconds', type=int, default=900)
    parser.add_argument('--acknowledge-unauthenticated-control', action='store_true')
    args = parser.parse_args()
    if not args.acknowledge_unauthenticated_control:
        parser.error('explicit --acknowledge-unauthenticated-control is required')
    asyncio.run(run(args.interface, args.port, args.allow_client,
                    args.upstream_port, args.seconds))


if __name__ == '__main__':
    main()
