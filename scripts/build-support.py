#!/usr/bin/env python3
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'uhttpd uhttpd-mod-ubus rpcd-mod-luci luci luci-light luci-mod-admin-full luci-app-firewall luci-i18n-firewall-zh-cn luci-proto-ppp luci-i18n-base-zh-cn'.split()
GUI = 'istoreos-files luci-app-store luci-lib-taskd taskd luci-app-package-manager luci-i18n-package-manager-zh-cn luci-app-ttyd luci-i18n-ttyd-zh-cn luci-app-upnp luci-i18n-upnp-zh-cn luci-theme-argon luci-app-argon-config luci-i18n-argon-zh-cn luci-i18n-argon-config-zh-cn'.split()
DOCKER = 'docker dockerd docker-compose luci-app-dockerman luci-i18n-dockerman-zh-cn'.split()
SAMWAF = 'curl ca-bundle jshn jsonfilter'.split()
DRIVERS = 'kmod-r8169 kmod-nvme kmod-rknpu kmod-hwmon-pwmfan kmod-thermal'.split()


def recipe(name):
    entries = [line.strip() for line in (ROOT / 'recipe' / name).read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    if any(not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9+_.-]*', p) for p in entries):
        raise ValueError(f'Invalid package name in {name}')
    if len(entries) != len(set(entries)):
        raise ValueError(f'Duplicate package in {name}')
    return entries


def configuration():
    lan = str(ipaddress.IPv4Address(os.environ.get('LAN_IP') or '192.168.199.1'))
    address = ipaddress.IPv4Address(lan)
    if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_reserved:
        raise ValueError('LAN_IP must be a unicast IPv4 address')
    if int(lan.rsplit('.', 1)[1]) in (0, 255):
        raise ValueError('LAN_IP must be a host address for the default /24 LAN')
    size = os.environ.get('ROOTFS_PARTSIZE') or '4096'
    if not re.fullmatch(r'[0-9]{3,5}', size) or not 512 <= int(size) <= 32768:
        raise ValueError('ROOTFS_PARTSIZE must be between 512 and 32768 MB')
    options = {}
    for key in ('WITH_GUI_EXTRAS', 'INCLUDE_DOCKER', 'INCLUDE_SAMWAF'):
        value = os.environ.get(key) or 'true'
        if value not in ('true', 'false'):
            raise ValueError(f'Invalid boolean: {key}')
        options[key] = value == 'true'
    return lan, str(int(size)), options


def configure():
    lan, size, options = configuration()
    added, removed = recipe('packages-add.txt'), recipe('packages-remove.txt')
    if set(added) & set(removed):
        raise ValueError('A package is both added and removed')
    wanted = BASE + added
    if options['WITH_GUI_EXTRAS']:
        wanted += GUI
    if options['INCLUDE_DOCKER']:
        wanted += DOCKER
    else:
        removed += DOCKER
    if options['INCLUDE_SAMWAF']:
        wanted += SAMWAF
    wanted += DRIVERS
    if set(wanted) & set(removed):
        raise ValueError('A required package is explicitly removed')
    wanted = sorted(set(wanted))
    removed = sorted(set(removed))
    overlay = Path(os.environ['RUNNER_TEMP']) / 'files-overlay'
    shutil.copytree(ROOT / 'files', overlay, dirs_exist_ok=True)
    if not options['INCLUDE_SAMWAF']:
        for relative in ('etc/init.d/samwaf', 'etc/config/samwaf', 'etc/uci-defaults/99-samwaf',
                         'usr/libexec/samwafctl', 'usr/share/luci/menu.d/luci-app-samwaf.json',
                         'usr/share/rpcd/acl.d/luci-app-samwaf.json', 'www/luci-static/resources/view/samwaf.js'):
            (overlay / relative).unlink()
    init = overlay / 'etc/uci-defaults/99-lan-ip'
    init.parent.mkdir(parents=True, exist_ok=True)
    # config_generate creates network in upper even on a clean boot; use iStoreOS's upgrade marker.
    init.write_text('#!/bin/sh\n[ -f /etc/uci-defaults/.upgrading ] && exit 0\n'
                    f"uci -q set network.lan.ipaddr='{lan}' && uci -q commit network\n")
    init.chmod(0o755)
    config = {'lan_ip': lan, 'rootfs_partsize': size, 'options': options,
              'required': wanted, 'removed': removed}
    (Path(os.environ['RUNNER_TEMP']) / 'build-config.json').write_text(json.dumps(config, indent=2) + '\n')
    with open(os.environ['GITHUB_ENV'], 'a') as output:
        output.write(f'PACKAGES={" ".join(wanted + ["-" + p for p in removed])}\n')
        output.write(f'ROOTFS_PARTSIZE={size}\nINCLUDE_SAMWAF={str(options["INCLUDE_SAMWAF"]).lower()}\n')


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_gzip(path):
    proc = subprocess.run(['gzip', '-t', str(path)], capture_output=True, text=True)
    if proc.returncode == 0:
        return
    # sysupgrade images append a metadata trailer after the gzip stream.
    if proc.returncode == 2 and 'decompression OK, trailing garbage ignored' in proc.stderr:
        return
    raise ValueError(f'gzip integrity check failed for {path.name}: {proc.stderr.strip()}')


def collect():
    temp = Path(os.environ['RUNNER_TEMP'])
    config = json.loads((temp / 'build-config.json').read_text())
    ib = Path(os.environ['IB_DIR'])
    target = ib / 'bin/targets/rockchip/armv8'
    stem = 'istoreos-rockchip-armv8-' + os.environ['PROFILE']
    image, manifest = target / (stem + '-squashfs-sysupgrade.img.gz'), target / (stem + '.manifest')
    for path in (image, manifest):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Missing or empty artifact: {path.name}')
    verify_gzip(image)
    installed = {line.split()[0] for line in manifest.read_text().splitlines() if line.strip()}
    missing = set(config['required']) - installed
    forbidden = set(config['removed']) & installed
    if missing or forbidden:
        raise ValueError(f'Missing packages: {sorted(missing)}; forbidden packages: {sorted(forbidden)}')
    roots = list((ib / 'build_dir').glob('target-*/root-rockchip'))
    if len(roots) != 1:
        raise ValueError('Cannot identify the built root filesystem')
    root = roots[0]
    def executable(relative):
        path = root / relative
        if path.is_symlink():
            link = os.readlink(path)
            path = root / link.lstrip('/') if link.startswith('/') else path.parent / link
        return path.is_file() and bool(path.stat().st_mode & 0o111)
    if config['options']['INCLUDE_SAMWAF']:
        for command in ('usr/bin/samwaf', 'etc/init.d/samwaf', 'usr/libexec/samwafctl',
                        'usr/bin/flock', 'usr/bin/hexdump', 'usr/bin/jshn', 'usr/bin/jsonfilter',
                        'usr/bin/curl', 'bin/ubus'):
            if not executable(command):
                raise ValueError(f'Missing runtime executable: {command}')
        for relative in ('usr/share/luci/menu.d/luci-app-samwaf.json', 'usr/share/rpcd/acl.d/luci-app-samwaf.json',
                         'www/luci-static/resources/view/samwaf.js', 'etc/config/samwaf',
                         'usr/share/samwaf/VERSION'):
            if not (root / relative).is_file():
                raise ValueError(f'Missing SamWaf file: {relative}')
    elif (root / 'usr/bin/samwaf').exists() or (root / 'etc/init.d/samwaf').exists():
        raise ValueError('SamWaf present despite INCLUDE_SAMWAF=false')
    out = ROOT / 'out'
    out.mkdir(exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Output directory must be empty')
    for path in (image, manifest, temp / 'build-config.json', temp / 'source-checksums.txt'):
        shutil.copy2(path, out / path.name)
    (out / 'ib-source-sha256.txt').write_text(os.environ['IB_SHA'] + '\n')
    (out / 'build-commit.txt').write_text(os.environ['GITHUB_SHA'] + '\n')
    with (out / 'SHA256SUMS.txt').open('w') as output:
        for path in sorted(out.iterdir()):
            if path.name != 'SHA256SUMS.txt':
                output.write(f'{checksum(path)}  {path.name}\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['configure', 'collect'])
    args = parser.parse_args()
    try:
        {'configure': configure, 'collect': collect}[args.command]()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
