import fnmatch
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_support', ROOT / 'scripts/build-support.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_inputs(self):
        for value in ('999.0.0.1', '$(printf injected)', '127.0.0.1', '192.168.1.0', '224.0.0.1'):
            with self.subTest(value=value), patch.dict(os.environ, {'LAN_IP': value}):
                with self.assertRaises(ValueError): build.configuration()
        for value in ('0', '4096;true', '-1', '999999999999999999999'):
            with self.subTest(value=value), patch.dict(os.environ, {'ROOTFS_PARTSIZE': value}):
                with self.assertRaises(ValueError): build.configuration()

    def test_recipes(self):
        added, removed = build.recipe('packages-add.txt'), build.recipe('packages-remove.txt')
        self.assertFalse(set(added) & set(removed))
        for name in ('quickstart', 'luci-app-quickstart', 'luci-app-diskman', 'parted', 'kmod-bluetooth'):
            self.assertIn(name, removed)
        self.assertFalse(set(build.DRIVERS + build.DOCKER + ['rpcbind', 'libsensors5', 'libdrm']) & set(removed))

    def test_mwan3_recipe_entries_have_pinned_workflow_hashes(self):
        workflow = (ROOT / '.github/workflows/build.yml').read_text()
        self.assertIn('OWRT_RELEASE:', workflow)
        pinned = re.findall(r'^\s*(?:packages|luci)/(\S+\.apk)\s+([0-9a-f]{64})\s*$', workflow, re.M)
        for name in ('mwan3', 'luci-app-mwan3', 'luci-i18n-mwan3-zh-cn'):
            self.assertIn(name, build.recipe('packages-add.txt'))
            matches = [h for f, h in pinned if f.startswith(name + '-')]
            self.assertEqual(len(matches), 1, f'{name} must have exactly one pinned apk')

    def test_option_matrix(self):
        for gui in ('true', 'false'):
            for docker in ('true', 'false'):
                for samwaf in ('true', 'false'):
                    with self.subTest(gui=gui, docker=docker, samwaf=samwaf), tempfile.TemporaryDirectory() as td:
                        env = {'RUNNER_TEMP': td, 'GITHUB_ENV': td + '/env', 'WITH_GUI_EXTRAS': gui,
                               'INCLUDE_DOCKER': docker, 'INCLUDE_SAMWAF': samwaf}
                        with patch.dict(os.environ, env): build.configure()
                        config = json.loads((Path(td) / 'build-config.json').read_text())
                        self.assertEqual('docker' in config['required'], docker == 'true')
                        self.assertEqual('docker' in config['removed'], docker == 'false')
                        self.assertEqual('luci-app-store' in config['required'], gui == 'true')
                        self.assertEqual((Path(td) / 'files-overlay/etc/init.d/samwaf').exists(), samwaf == 'true')
                        script = (Path(td) / 'files-overlay/etc/uci-defaults/99-lan-ip').read_text()
                        self.assertIn('/etc/uci-defaults/.upgrading', script)
                        self.assertNotIn('/upper/etc/config/network', script)

    def test_lan_defaults_only_apply_on_clean_boot(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            with patch.dict(os.environ, {'RUNNER_TEMP': td, 'GITHUB_ENV': td + '/env'}): build.configure()
            script = (temp / 'files-overlay/etc/uci-defaults/99-lan-ip').read_text().replace('/etc/uci-defaults/.upgrading', td + '/upgrading')
            stub = 'uci() { printf "%s\\n" "$*"; };\n'
            result = subprocess.run(['sh', '-s'], input=stub + script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('network.lan.ipaddr=192.168.199.1', result.stdout)
            (temp / 'upgrading').touch()
            result = subprocess.run(['sh', '-s'], input=stub + script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_missing_image_fails(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            (temp / 'build-config.json').write_text('{}')
            with patch.dict(os.environ, {'RUNNER_TEMP': td, 'IB_DIR': td, 'PROFILE': 'test'}):
                with self.assertRaisesRegex(ValueError, 'artifact'): build.collect()

    def test_gzip_accepts_sysupgrade_trailer_but_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / 'image.img.gz'
            with gzip.open(image, 'wb') as stream: stream.write(b'firmware')
            build.verify_gzip(image)
            with image.open('ab') as stream: stream.write(b'sysupgrade-metadata-trailer')
            build.verify_gzip(image)
            image.write_bytes(b'not gzip at all')
            with self.assertRaisesRegex(ValueError, 'gzip integrity'): build.verify_gzip(image)

    def test_exact_artifacts_and_checksums(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            target = temp / 'bin/targets/rockchip/armv8'; target.mkdir(parents=True)
            (temp / 'build_dir/target-test/root-rockchip').mkdir(parents=True)
            stem = 'istoreos-rockchip-armv8-test'
            with gzip.open(target / (stem + '-squashfs-sysupgrade.img.gz'), 'wb') as stream: stream.write(b'firmware')
            (target / (stem + '.manifest')).write_text('base - 1\n')
            (temp / 'build-config.json').write_text(json.dumps({'required': ['base'], 'removed': ['forbidden'], 'options': {'INCLUDE_SAMWAF': False}}))
            (temp / 'source-checksums.txt').write_text('source fixture\n')
            env = {'RUNNER_TEMP': td, 'IB_DIR': td, 'PROFILE': 'test', 'IB_SHA': 'a' * 64, 'GITHUB_SHA': 'b' * 40}
            with patch.object(build, 'ROOT', temp), patch.dict(os.environ, env): build.collect()
            files = {p.name for p in (temp / 'out').iterdir()}
            listed = {line.split('  ')[1] for line in (temp / 'out/SHA256SUMS.txt').read_text().splitlines()}
            self.assertEqual(files - {'SHA256SUMS.txt'}, listed)
            subprocess.run(['sha256sum', '-c', 'SHA256SUMS.txt'], cwd=temp / 'out', check=True, capture_output=True)

    def test_archive_extraction_does_not_traverse(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            with tarfile.open(temp / 'test.tar.gz', 'w:gz') as archive:
                member = tarfile.TarInfo('../../SamWafLinux_arm64'); member.size = 6
                archive.addfile(member, io.BytesIO(b'binary'))
            subprocess.run(['python3', str(ROOT / 'scripts/extract-samwaf.py'), str(temp / 'test.tar.gz'), str(temp / 'output')], check=True)
            self.assertEqual((temp / 'output').read_bytes(), b'binary')

    def test_acl(self):
        acl = json.loads((ROOT / 'files/usr/share/rpcd/acl.d/luci-app-samwaf.json').read_text())['luci-app-samwaf']
        readonly = acl['read']['file']
        for command in ('start', 'stop', 'restart', 'set_port 1234', 'upgrade v1.3.24', '_upgrade v1.3.24'):
            self.assertFalse(any(fnmatch.fnmatch('/usr/libexec/samwafctl ' + command, pattern) for pattern in readonly))
        self.assertFalse(any(fnmatch.fnmatch('/usr/libexec/samwafctl _upgrade v1.3.24', pattern) for pattern in acl['write']['file']))

    def test_local_auxiliary_scripts_preserve_config_and_failures(self):
        workspace = ROOT.parent
        if not (workspace / 'step3-build.sh').is_file():
            self.skipTest('Local workspace helpers are outside the firmware repository')
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            source = temp / 'istoreos'; source.mkdir()
            mocks = temp / 'hosttools/usr/bin'; mocks.mkdir(parents=True)
            for name in ('step2-config.sh', 'step3-build.sh'):
                shutil.copy2(workspace / name, temp / name)
            (mocks / 'make').write_text('#!/bin/sh\ncase "$*" in *"$FAIL_TARGET"*) exit 23;; esac\n')
            (mocks / 'make').chmod(0o755)
            for target in ('prereq', 'toolchain/install', 'package/compile'):
                result = subprocess.run(['bash', str(temp / 'step3-build.sh')], env={**os.environ, 'FAIL_TARGET': target}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 23)
                self.assertNotIn('completed successfully', result.stdout)
            definitions = source / 'target/linux/rockchip/image'; definitions.mkdir(parents=True)
            (definitions / 'test.mk').write_text('define Device/cyber_cyber3588-aib\n')
            (source / '.config').write_text('original config\n')
            result = subprocess.run(['bash', str(temp / 'step2-config.sh')], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((source / '.config').read_text(), 'original config\n')
            (mocks / 'make').write_text('#!/bin/sh\nexit 0\n')
            result = subprocess.run(['bash', str(temp / 'step2-config.sh'), '--replace-config'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(next(source.glob('.config.before-rkmpp.*')).read_text(), 'original config\n')

    def test_syntax(self):
        for path in [ROOT / 'files/etc/init.d/samwaf', ROOT / 'files/etc/uci-defaults/99-samwaf', ROOT / 'files/usr/libexec/samwafctl', ROOT / 'scripts/publish.sh']:
            subprocess.run(['bash' if path.name == 'publish.sh' else 'sh', '-n', str(path)], check=True)


class ReleaseTests(unittest.TestCase):
    def test_attempt_tags_commit_binding_and_marker_order(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            out = temp / 'out'; out.mkdir()
            mock = temp / 'mocks'; mock.mkdir()
            (out / 'test-squashfs-sysupgrade.img.gz').write_bytes(b'firmware')
            (out / 'ib-source-sha256.txt').write_text('a' * 64 + '\n')
            (out / 'SHA256SUMS.txt').write_text(''.join(build.checksum(p) + '  ' + p.name + '\n' for p in out.iterdir()))
            stub = '''#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ['GITHUB_WORKSPACE'])
with (root / 'calls').open('a') as stream: stream.write(json.dumps(args) + '\\n')
if args[:2] == ['release', 'view']: sys.exit(1)
if args[:2] == ['release', 'download']:
    if os.environ.get('FAIL_RELEASE_DOWNLOAD'): sys.exit(1)
    dest = Path(args[args.index('--dir') + 1])
    for source in (root / 'out').iterdir():
        if source.name != 'ib-source-sha256.txt': shutil.copyfile(source, dest / source.name)
'''
            (mock / 'gh').write_text(stub); (mock / 'gh').chmod(0o755)
            env = {**os.environ, 'PATH': str(mock) + ':' + os.environ['PATH'], 'GITHUB_WORKSPACE': td,
                   'RUNNER_TEMP': td, 'GITHUB_REPOSITORY': 'test/test', 'GITHUB_SHA': 'b' * 40,
                   'IB_SHA': 'a' * 64, 'GITHUB_RUN_NUMBER': '101'}
            tags = []
            for attempt in ('1', '2'):
                (temp / 'calls').write_text('')
                result = subprocess.run(['bash', str(ROOT / 'scripts/publish.sh')], env={**env, 'GITHUB_RUN_ATTEMPT': attempt}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = [json.loads(line) for line in (temp / 'calls').read_text().splitlines()]
                create = next(call for call in calls if call[:2] == ['release', 'create'])
                self.assertEqual(create[create.index('--target') + 1], env['GITHUB_SHA'])
                self.assertIn('--draft', create)
                tags.append(create[2])
                self.assertEqual(calls[-1][-1], 'ib-source-sha256.txt')
            self.assertNotEqual(*tags)
            (temp / 'calls').write_text('')
            result = subprocess.run(['bash', str(ROOT / 'scripts/publish.sh')], env={**env, 'GITHUB_RUN_ATTEMPT': '3', 'FAIL_RELEASE_DOWNLOAD': '1'}, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            calls = [json.loads(line) for line in (temp / 'calls').read_text().splitlines()]
            self.assertFalse(any(call[:3] == ['release', 'upload', 'firmware'] and call[-1] == 'ib-source-sha256.txt' for call in calls))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ('usr/bin', 'opt/samwaf/data', 'usr/share/samwaf', 'var/lock', 'mocks'):
            (self.root / directory).mkdir(parents=True)
        self.state = self.root / 'state.json'
        self.state.write_text(json.dumps({'port': '26666', 'running': True, 'enabled': True}))
        self.binary = self.root / 'usr/bin/samwaf'; self.binary.write_bytes(b'OLD_BINARY'); self.binary.chmod(0o755)
        (self.root / 'usr/share/samwaf/VERSION').write_text('v1.3.24')
        (self.root / 'opt/samwaf/data/database').write_text('original')
        for name in ('uci', 'ubus', 'jsonfilter', 'init', 'curl', 'hexdump', 'sleep'):
            path = self.root / 'mocks' / name
            path.write_text(f'#!/bin/sh\nexec python3 "{ROOT / "tests/runtime_stub.py"}" {name} "$@"\n')
            path.chmod(0o755)
        jshn = self.root / 'jshn.sh'
        script = f'json_cmd() {{ JSON=$(printf "%s" "$JSON" | python3 "{ROOT / "tests/runtime_stub.py"}" json "$@"); }}\n'
        script += 'json_init() { JSON=\'{"value":{},"stack":[]}\'; };\n'
        for kind in ('string', 'int', 'boolean', 'null', 'array', 'object'):
            script += f'json_add_{kind}() {{ json_cmd {kind} "$@"; }};\n'
        script += 'json_close_array() { json_cmd close; }; json_close_object() { json_cmd close; };\n'
        script += f'json_dump() {{ printf "%s" "$JSON" | python3 "{ROOT / "tests/runtime_stub.py"}" json dump; }}\n'
        jshn.write_text(script)
        helper = (ROOT / 'files/usr/libexec/samwafctl').read_text()
        for old, new in {'/usr/share/libubox/jshn.sh': str(jshn), '/usr/bin/samwaf': str(self.binary),
                         '/opt/samwaf': str(self.root / 'opt/samwaf'), '/etc/init.d/samwaf': str(self.root / 'mocks/init'),
                         '/usr/share/samwaf/VERSION': str(self.root / 'usr/share/samwaf/VERSION'),
                         '/var/lock/samwafctl.lock': str(self.root / 'var/lock/ctl.lock')}.items():
            helper = helper.replace(old, new)
        self.helper = self.root / 'helper'; self.helper.write_text(helper)
        self.env = {**os.environ, 'TEST_ROOT': str(self.root), 'PATH': str(self.root / 'mocks') + ':' + os.environ['PATH']}
        binary = bytearray(120)
        binary[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HH', binary, 16, 2, 183)
        struct.pack_into('<Q', binary, 32, 64)
        struct.pack_into('<HH', binary, 54, 56, 1)
        struct.pack_into('<I', binary, 64, 1)
        binary.extend(b'NEW_BINARY')
        self.new_binary = bytes(binary)
        self.make_archive(self.new_binary)

    def make_archive(self, binary):
        with tarfile.open(self.root / 'download.tar.gz', 'w:gz') as archive:
            member = tarfile.TarInfo('SamWafLinux_arm64'); member.size = len(binary)
            archive.addfile(member, io.BytesIO(binary))
        digest = hashlib.sha256((self.root / 'download.tar.gz').read_bytes()).hexdigest()
        (self.root / 'checksums').write_text(digest + '  SamWaf_Linux_arm64 v1.3.25.tar.gz\n')

    def run_helper(self, *args, **env):
        return subprocess.run([*shlex.split(os.environ.get('TEST_SHELL', 'sh')), str(self.helper), *args], env={**self.env, **env}, text=True, capture_output=True, timeout=45)

    def test_port_validation_and_json(self):
        for value in ('', '0', '65536', '99999999999999999999', '12;echo'):
            result = self.run_helper('set_port', value)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(json.loads(result.stdout)['ok'])
        result = self.run_helper('set_port', '08080')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['port'], 8080)

    def test_uci_failure(self):
        result = self.run_helper('set_port', '8080', FAIL_COMMIT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)['ok'])
        self.assertEqual(json.loads(self.state.read_text())['port'], '26666')

    def test_port_rollback(self):
        result = self.run_helper('set_port', '8080', BAD_PORT='8080')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(self.state.read_text())['port'], '26666')
        self.assertTrue(json.loads(self.state.read_text())['running'])

    def test_status_json_escaping(self):
        (self.root / 'usr/share/samwaf/VERSION').write_text('version"\\\n')
        result = self.run_helper('status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"', json.loads(result.stdout)['version'])

    def test_upgrade_launch_and_worker_exclusion(self):
        result = self.run_helper('upgrade', '1.3.25')
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.state.read_text())
        self.assertEqual(state['launch']['instances']['worker']['command'][-1], 'v1.3.25')
        self.assertNotEqual(self.run_helper('stop').returncode, 0)
        self.assertNotEqual(self.run_helper('upgrade', 'v1.3.25').returncode, 0)

    def test_lock_blocks_concurrent_controls(self):
        import fcntl
        with (self.root / 'var/lock/ctl.lock').open('w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_helper('set_port', '8080')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(json.loads(result.stdout)['ok'])
        self.assertEqual(json.loads(self.state.read_text())['port'], '26666')

    def test_bad_checksum_and_dynamic_elf(self):
        (self.root / 'checksums').write_text('0' * 64 + '  Linux_arm64\n')
        self.assertNotEqual(self.run_helper('_upgrade', 'v1.3.25').returncode, 0)
        self.assertEqual(self.binary.read_bytes(), b'OLD_BINARY')
        dynamic = bytearray(self.new_binary)
        struct.pack_into('<I', dynamic, 64, 3)
        self.make_archive(dynamic)
        self.assertNotEqual(self.run_helper('_upgrade', 'v1.3.25').returncode, 0)
        self.assertEqual(self.binary.read_bytes(), b'OLD_BINARY')

    def test_launch_failure_reports_error(self):
        result = self.run_helper('upgrade', 'v1.3.25', FAIL_LAUNCH='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)['ok'])

    def test_invalid_worker_and_argument_count(self):
        self.assertNotEqual(self.run_helper('_upgrade', '../../file').returncode, 0)
        self.assertNotEqual(self.run_helper('set_port', '1234', 'extra').returncode, 0)

    def test_upgrade_success(self):
        result = self.run_helper('_upgrade', 'v1.3.25')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.binary.read_bytes(), self.new_binary)
        self.assertEqual((self.root / 'opt/samwaf/.upgrade/result').read_text().strip(), 'ok')
        self.assertEqual((self.root / 'usr/share/samwaf/VERSION').read_text().strip(), 'v1.3.25')

    def test_upgrade_rolls_back_binary_and_database(self):
        result = self.run_helper('_upgrade', 'v1.3.25', FAIL_NEW_START='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.binary.read_bytes(), b'OLD_BINARY')
        self.assertEqual((self.root / 'opt/samwaf/data/database').read_text(), 'original')
        self.assertEqual((self.root / 'usr/share/samwaf/VERSION').read_text(), 'v1.3.24')
        self.assertTrue(json.loads(self.state.read_text())['running'])
        self.assertEqual((self.root / 'opt/samwaf/.upgrade/result').read_text().strip(), 'fail')

    def test_bad_elf_and_download_do_not_stop_service(self):
        self.make_archive(b'not an ELF')
        for env in ({}, {'FAIL_DOWNLOAD': '1'}):
            result = self.run_helper('_upgrade', 'v1.3.25', **env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.binary.read_bytes(), b'OLD_BINARY')
            self.assertTrue(json.loads(self.state.read_text())['running'])

    def test_upgrade_preserves_stopped_state(self):
        state = json.loads(self.state.read_text()); state['running'] = False; self.state.write_text(json.dumps(state))
        self.assertEqual(self.run_helper('_upgrade', 'v1.3.25').returncode, 0)
        self.assertFalse(json.loads(self.state.read_text())['running'])

    def test_dead_worker_reports_failure(self):
        directory = self.root / 'opt/samwaf/.upgrade'; directory.mkdir()
        (directory / 'result').write_text('pending')
        result = self.run_helper('upgrade_status')
        self.assertFalse(json.loads(result.stdout)['done'])


if __name__ == '__main__':
    unittest.main()
