"""Local connection configuration and bounded passive discovery on the host."""
import ipaddress
import json
import platform
import shutil
import subprocess
import threading

from controller import DeviceConfig
from controller.fiio_discovery import listen, observe
from experiments.disc_web.backend.device import BusyError

NETWORKS = tuple(ipaddress.IPv4Network(value) for value in
                 ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '127.0.0.0/8'))


def local_address(value):
    address = ipaddress.IPv4Address('127.0.0.1' if value == 'localhost' else value)
    if (address.is_unspecified or address.is_multicast or address.is_reserved
            or not any(address in network for network in NETWORKS)):
        raise ValueError('Use a local IPv4 address')
    return str(address)


def connection_config(body):
    host = body.get('host')
    if not isinstance(host, str):
        raise ValueError('A player IPv4 address is required')
    return DeviceConfig(local_address(host), body.get('tcp_port'), body.get('http_port'))


def parse_interfaces(text):
    result, name, up = [], '', False
    for line in text.splitlines():
        if line and not line[0].isspace() and ':' in line:
            name = line.split(':', 1)[0]
            up = '<UP,' in line or '<UP>' in line
        parts = line.split()
        if up and len(parts) > 1 and parts[0] == 'inet':
            result.append({'name': name, 'address': parts[1]})
    return result


def interfaces():
    try:
        if platform.system() == 'Darwin':
            output = subprocess.run(['/sbin/ifconfig'], capture_output=True, text=True, timeout=3, check=True)
            values = parse_interfaces(output.stdout)
        else:
            executable = shutil.which('ip')
            if not executable:
                return []
            output = subprocess.run([executable, '-j', '-4', 'addr', 'show', 'up'],
                                    capture_output=True, text=True, timeout=3, check=True)
            values = [{'name': row['ifname'], 'address': info['local']}
                      for row in json.loads(output.stdout) for info in row.get('addr_info', [])
                      if info.get('family') == 'inet']
        result = []
        for value in values:
            try:
                address = local_address(value['address'])
            except ValueError:
                continue
            if (not ipaddress.IPv4Address(address).is_loopback
                    and not value['name'].startswith(('utun', 'tun', 'tap', 'docker', 'veth'))):
                result.append({'name': value['name'], 'address': address})
        return result
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return []


class Discovery:
    def __init__(self):
        self.lock = threading.Lock()

    def search(self, interface):
        if not self.lock.acquire(False):
            raise BusyError('Discovery is already running')
        try:
            if interface not in {row['address'] for row in interfaces()}:
                raise ValueError('Choose a current local network interface')
            found = {}
            with listen(interface) as sock:
                for _, item in observe(sock, 6):
                    try:
                        host = local_address(item['host'])
                    except ValueError:
                        continue
                    found[host] = dict(host=host, name=item['name'], tcp_port=12100, http_port=12103)
                    if len(found) >= 32:
                        break
            return {'devices': list(found.values())}
        finally:
            self.lock.release()
