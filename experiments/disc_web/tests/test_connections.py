import unittest
from unittest.mock import Mock, patch

from controller import DeviceConfig
from controller.tests.session_fixture import Server as Peer
from experiments.disc_web.backend.connections import connection_config, parse_interfaces, interfaces, Discovery
from experiments.disc_web.backend.device import Device, BusyError


class ConnectionTests(unittest.TestCase):
    def test_config_accepts_local_ips_and_rejects_urls_public_addresses_and_bad_ports(self):
        self.assertEqual(connection_config({'host': 'localhost', 'tcp_port': 12100, 'http_port': 12113}),
                         DeviceConfig('127.0.0.1', 12100, 12113))
        for host in ('0.0.0.0', '224.0.0.255', '255.255.255.255', '8.8.8.8', 'https://192.168.1.1', '192.168.1.1/path', None):
            with self.assertRaises(ValueError):
                connection_config({'host': host, 'tcp_port': 12100, 'http_port': 12103})
        for port in (True, '12100', 0, 65536, None):
            with self.assertRaises(ValueError):
                connection_config({'host': '192.168.2.10', 'tcp_port': port, 'http_port': 12103})

    def test_interface_inventory_filters_loopback_vpn_down_and_invalid_addresses(self):
        text = ('lo0: flags=8049<UP,LOOPBACK>\n\tinet 127.0.0.1 netmask 0xff000000\n'
                'en0: flags=8863<UP,BROADCAST>\n\tinet 192.168.2.10 netmask 0xffffff00\n'
                'en1: flags=8862<BROADCAST>\n\tinet 192.168.2.11 netmask 0xffffff00\n'
                'utun0: flags=8051<UP,POINTOPOINT>\n\tinet 10.0.1.2 netmask 0xffffff00\n')
        self.assertEqual(len(parse_interfaces(text)), 3)
        with patch('experiments.disc_web.backend.connections.platform.system', return_value='Darwin'), \
             patch('experiments.disc_web.backend.connections.subprocess.run', return_value=Mock(stdout=text)):
            self.assertEqual(interfaces(), [{'name': 'en0', 'address': '192.168.2.10'}])

    def test_discovery_is_passive_bounded_deduplicated_and_uses_a_current_interface(self):
        discovery = Discovery()
        rows = [{'name': 'en0', 'address': '192.168.2.10'}]
        candidate = {'host': '192.168.2.11', 'name': 'SNOWSKY DISC'}
        with patch('experiments.disc_web.backend.connections.interfaces', return_value=rows), \
             patch('experiments.disc_web.backend.connections.listen') as listen, \
             patch('experiments.disc_web.backend.connections.observe', return_value=[(1, candidate), (2, candidate)]) as observe:
            with self.assertRaises(ValueError):
                discovery.search('192.168.2.99')
            listen.assert_not_called()
            result = discovery.search('192.168.2.10')
            self.assertEqual(len(result['devices']), 1)
            listen.assert_called_once_with('192.168.2.10')
            self.assertEqual(observe.call_args.args[1], 6)
        with discovery.lock, self.assertRaises(BusyError):
            discovery.search('192.168.2.10')

    def test_reconfigure_closes_old_owner_preserves_generation_and_rejects_stale_work(self):
        first, second = Peer(), Peer()
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        config = DeviceConfig('127.0.0.1', first.server_address[1], timeout=.3)
        other = DeviceConfig('127.0.0.1', second.server_address[1], timeout=.3)
        with Device(config) as device:
            device.configure(config, device.state()['generation'])
            self.assertTrue(device.session.wait_ready(2))
            generation = device.state()['generation']
            old = device.session
            device.sources['stale'] = {'generation': generation}
            with device.lock, self.assertRaises(BusyError):
                device.configure(other, generation)
            with self.assertRaises(ValueError):
                device.configure(other, generation + 1)
            self.assertEqual(second.accepts, 0)
            device.configure(other, generation)
            self.assertFalse(old.worker.is_alive())
            self.assertTrue(device.session.wait_ready(2))
            self.assertGreater(device.state()['generation'], generation)
            self.assertEqual(device.sources, {})
            current = device.state()['generation']
            self.assertEqual(device.protocol_generation(current), device.session.snapshot().generation)
            for action in ('pause', 'disconnect'):
                with self.assertRaises(ValueError):
                    device.action({'action': action, 'generation': generation})
            device.configure(other, current)
            self.assertEqual(second.accepts, 1)
            self.assertEqual((first.writes, second.writes), (0, 0))


if __name__ == '__main__':
    unittest.main()
