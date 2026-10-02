"""Emulated links: validation and the rootfs sysfs stub, with `ip`/`tc` replaced."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from emulator.runtime import network

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
ETH = {'ifname': 'eth1', 'flags': ['UP'], 'operstate': 'UP', 'address': '02:42:ac:11:00:02',
       'addr_info': [{'family': 'inet', 'local': '172.17.0.2', 'prefixlen': 16}]}
WLAN = {'ifname': 'wlan0', 'flags': [], 'operstate': 'DOWN', 'address': 'd0:31:10:00:00:01',
        'linkinfo': {'info_kind': 'dummy'}, 'addr_info': []}
TUNNEL = {'ifname': 'tunl0', 'flags': [], 'operstate': 'DOWN', 'address': '0.0.0.0', 'addr_info': []}


class LinkTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / 'rootfs'
        (self.root / 'emu').mkdir(parents=True)
        self.links = {'eth1': dict(ETH)}
        self.calls = []
        for target, replacement in (('links', lambda root: self.links), ('ip', self.ip)):
            patcher = patch.object(network, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ip(self, root, *args, **options):
        self.calls.append(args)
        if args[:2] == ('link', 'add'):
            self.links[args[2]] = dict(WLAN, ifname=args[2])
        elif args[:2] == ('link', 'del'):
            del self.links[args[2]]
        elif args[:2] == ('link', 'set') and args[3] in ('up', 'down'):
            self.links[args[2]]['flags'] = ['UP'] if args[3] == 'up' else []
        elif args[:2] == ('link', 'set') and args[3] == 'address':
            self.links[args[2]]['address'] = args[4]

    def stub(self, name):
        directory = self.root / 'sys/class/net' / name
        return {path.name: path.read_text() for path in directory.iterdir()} if directory.is_dir() else None

    def test_dummy_link_is_created_and_its_stub_follows_the_requested_state(self):
        network.link(self.root, 'wlan0', mac='d0:31:10:aa:bb:cc')
        self.assertEqual(self.stub('wlan0'), {'address': 'd0:31:10:aa:bb:cc\n', 'operstate': 'down\n'})
        network.link(self.root, 'wlan0', state='up', addr='10.0.0.2/24', gateway='10.0.0.1')
        self.assertEqual(self.stub('wlan0')['operstate'], 'up\n')        # a dummy reports "unknown"
        self.assertIn(('addr', 'add', '10.0.0.2/24', 'dev', 'wlan0'), self.calls)
        self.assertIn(('route', 'replace', 'default', 'via', '10.0.0.1', 'dev', 'wlan0'), self.calls)
        self.assertEqual(self.calls.count(('link', 'add', 'wlan0', 'type', 'dummy')), 1)
        network.link(self.root, 'wlan0', addr='none')
        self.assertEqual(self.calls[-1], ('addr', 'flush', 'dev', 'wlan0'))
        network.unlink(self.root, 'wlan0')
        self.assertIsNone(self.stub('wlan0'))

    def test_real_interfaces_and_bad_values_are_refused_before_any_change(self):
        for call in (lambda: network.link(self.root, 'eth1', state='down'),
                     lambda: network.unlink(self.root, 'eth1'),
                     lambda: network.link(self.root, 'lo', state='down'),
                     lambda: network.link(self.root, 'wlan0; reboot'),
                     lambda: network.link(self.root, 'WLAN0')):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.calls, [])
        with self.assertRaises(ValueError):
            network.link(self.root, 'wlan0', mac='not-a-mac')
        for bad in (dict(rate='fast'), dict(delay='soon'), dict(loss='1'), dict(rate='800kbit; reboot')):
            with patch('emulator.runtime.network.subprocess.run') as run, self.assertRaises(ValueError):
                network.shape(**bad)
            run.assert_not_called()

    def test_shape_builds_delay_then_rate_and_off_only_clears(self):
        with patch('emulator.runtime.network.subprocess.run') as run:
            network.shape(rate='800kbit', delay='60ms', loss='1%')
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0], ['tc', 'qdisc', 'del', 'dev', 'eth1', 'root'])
            self.assertEqual(commands[1][-5:], ['netem', 'delay', '60ms', 'loss', '1%'])
            self.assertEqual(commands[2][5:9], ['parent', '1:1', 'handle', '10:'])
            self.assertIn('800kbit', commands[2])
            run.reset_mock()
            network.shape()
            self.assertEqual([call.args[0] for call in run.call_args_list],
                             [['tc', 'qdisc', 'del', 'dev', 'eth1', 'root']])

    def test_status_lists_guest_links_not_idle_tunnels(self):
        self.links.update(wlan0=dict(WLAN), tunl0=dict(TUNNEL))
        with patch('emulator.runtime.network.subprocess.run') as run:
            run.return_value.stdout = ''
            links = network.status(self.root)['links']
        self.assertEqual(sorted(links), ['eth1', 'wlan0'])
        self.assertTrue(links['wlan0']['emulated'] and not links['eth1']['emulated'])
        self.assertEqual(links['eth1']['addresses'], ['172.17.0.2/16'])

    def test_namespace_marker_needs_a_live_namespace(self):
        self.assertIsNone(network.namespace(self.root))
        (self.root / 'emu/netns').write_text('no-such-namespace-for-tests\n')
        self.assertIsNone(network.namespace(self.root))


class GuestRunTests(unittest.TestCase):
    def test_isolated_guest_commands_enter_its_network_namespace_first(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            (base / 'rootfs/emu').mkdir(parents=True)
            (base / 'commands').mkdir()
            for name in ('nsenter', 'timeout'):
                (base / 'commands' / name).write_text(f'#!/bin/sh\necho {name} "$@"\n')
                (base / 'commands' / name).chmod(0o755)
            lib = (SCRIPTS / 'lib.sh').read_text().replace('/run/netns/', f'{base}/netns/')
            (base / 'lib.sh').write_text(lib)
            environment = dict(os.environ, PATH=f'{base}/commands:{os.environ["PATH"]}', ROOTFS=str(base / 'rootfs'),
                               WORK=str(base), REPO=str(SCRIPTS.parents[1]), FW_VERSION='2.57')
            run = lambda: subprocess.check_output(  # noqa: E731
                ['bash', '-c', f'source {base}/lib.sh; guest_run 5 /bin/true'], env=environment, text=True).split()
            (base / 'rootfs/emu/netns').write_text('disc-guest\n')
            self.assertEqual(run()[0], 'timeout')                      # marker without a namespace
            (base / 'netns').mkdir()
            (base / 'netns/disc-guest').touch()
            self.assertEqual(run()[:4], ['nsenter', f'--net={base}/netns/disc-guest', '--', 'timeout'])


if __name__ == '__main__':
    unittest.main()
