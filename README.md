# Action-istoreos-builder

用 GitHub Actions + iStoreOS 官方 ImageBuilder 为 **Cyber Cyber3588-AIB (RK3588)** 打包固件，不编译源码，几分钟出包。支持通过 `recipe/` 增删软件包。

- 固件基线：iStoreOS 25.12（官方 IB，rockchip/armv8，设备定义与 istoreos-25.12 分支一致）
- LAN 管理地址：`192.168.199.1`（首启由 uci-defaults 写入）
- 网口：LAN=eth1、WAN=eth0（官方 base-files 内置，未做覆盖）
- 产物：`istoreos-rockchip-armv8-cyber_cyber3588-aib-squashfs-sysupgrade.img.gz` + manifest + sha256

## 使用方法

1. 在 GitHub 网页上建一个空仓库（如 `Action-istoreos-builder`），把本目录内容推上去：
   ```bash
   cd Action-istoreos-builder
   git init && git add -A && git commit -m "init: cyber3588-aib IB builder"
   git remote add origin git@github.com:<你的用户名>/Action-istoreos-builder.git
   git push -u origin main
   ```
2. 仓库页面 → Actions → `Build iStoreOS for Cyber3588-AIB` → Run workflow。
3. 构建完成后在 run 页面底部 Artifacts 下载固件包。

### workflow_dispatch 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `lan_ip` | 192.168.199.1 | LAN 管理地址 |
| `rootfs_partsize` | 4096 | rootfs 分区大小 (MB) |
| `with_gui_extras` | true | iStore 商店 / quickstart / 磁盘管理 / ttyd / argon 主题（中文） |
| `include_docker` | false | Docker + dockerman |

自动触发：push 改动 `recipe/**` 或 workflow 本身；每月 1 号定时重建（跟随官方 IB 更新）。

## 固件内置第三方 feed（files/）

固件已预置 [dllkids openwrt-feed](https://down.dllkids.xyz/openwrt-feed/25.12/)（kenzok8 系第三方包源，含 ddns-go、mosdns 壳、openclash 等 623 个包）：

- `files/etc/apk/repositories.d/dllkids-feed.list`：feed 仓库地址（aarch64_generic，对应本固件 25.12 基线）
- `files/etc/apk/keys/dllkids-feed.pub.pem`：feed 的 ECDSA 签名公钥

设备开机后 `apk update` 或在 LuCI「软件包管理」里即可直接安装该 feed 的包，等效于在设备上跑官方 `openwrt-feed-setup.sh`，但无需联网执行脚本。`files/` 目录下的所有文件构建时会原样合并进镜像 rootfs，可继续往里放其他 overlay 文件。

## 软件包增删（recipe/）

| 文件 | 作用 | 机制 |
|---|---|---|
| `recipe/packages-add.txt` | 追加安装 | 逐行追加到 `PACKAGES=` |
| `recipe/packages-remove.txt` | 剔除 | 逐行转成 `-包名` 负号语法 |

两个列表当前为空 = 构建基线固件（profile 默认包 + LuCI 管理界面套件），先验证流程，之后再按需增删。

基线固件包含：
- **profile 默认包**（IB 保证）：内核、驱动（kmod-r8169 网卡 / kmod-nvme / kmod-ata-ahci-dwc / kmod-rknpu / GPU / VPU / 风扇温控）、dnsmasq、firewall4、dropbear 等
- **管理界面底座**（显式列出，缺了进不去后台）：uhttpd、luci、luci-mod-admin-full、防火墙/PPPoE 及中文汉化
- **GUI 套件**（`with_gui_extras=true` 时）：quickstart、iStore 商店、软件包管理、磁盘管理、ttyd、WoL、UPnP、argon 主题

改完 recipe 后 push 即自动重建；构建末尾会对 manifest 逐项断言（管理页必需包必须在、剔除项必须不在、设备驱动包必须在），不满足直接 fail，避免"刷完卡才发现"。

### 后续计划包的来源备忘

- `docker / dockerd / docker-compose / luci-app-dockerman`：IB 本地仓库自带，直接写进 add 列表（或勾 `include_docker`）
- OAF（`appfilter / kmod-oaf / luci-app-oaf / luci-i18n-oaf-zh-cn`）：IB 本地仓库自带 v7 全套，内核版本匹配
- `ddns-go / luci-app-ddns-go`：dllkids feed（`https://down.dllkids.xyz/openwrt-feed/25.12/aarch64_generic/`）
- `luci-app-mosdns` + `geo2txt / v2ray-geoip / v2ray-geosite`：同上 dllkids feed
- `mosdns` 主程序：dllkids feed 没有，在 ImmortalWrt snapshots（`https://downloads.immortalwrt.org/snapshots/packages/aarch64_generic/packages/`）

第三方 .apk 的接入方式：workflow 里加一步下载到 `$IB_DIR/packages/`，IB 构建时会自动 `apk mkndx --allow-untrusted` 重建索引，无需签名。

## 刷写

- **SD 卡 / eMMC**：`gunzip -c xxx-sysupgrade.img.gz | sudo dd of=/dev/sdX bs=4M conv=fsync`，或用 balenaEtcher / Rufus
- **已有 iStoreOS/OpenWrt 系统**：系统 → 备份/升级 → 刷写 sysupgrade 镜像（保留配置）
- 首次启动后访问 `http://192.168.199.1`，root 无密码，建议立即设置

## 本地构建（不经 CI）

```bash
# 依赖：gawk（必须是 GNU awk，mawk 不行）、zstd、build-essential 等
mkdir ib && cd ib
curl -fLO https://fw.koolcenter.com/iStoreOS/ib/rk3xxx/istoreos-imagebuilder-rockchip-armv8.Linux-x86_64.tar.zst
tar --zstd -xf *.tar.zst && cd istoreos-imagebuilder-*/
make info | grep -A3 '^cyber_cyber3588-aib:'   # 确认 profile
make -j$(nproc) image PROFILE="cyber_cyber3588-aib" PACKAGES="uhttpd luci luci-mod-admin-full ..." FILES=... 
# 产物: bin/targets/rockchip/armv8/
```

## 参考项目

- [ayi3030/istoreos-r1plus-builder](https://github.com/ayi3030/istoreos-r1plus-builder)：官方 IB + GitHub Actions 的构建方式与包列表经验
- [bluise/istoreos](https://github.com/bluise/istoreos)：recipe 增删包思路（其本体是"下载官方 x86 成品镜像→解包 squashfs→增删→重打包"，绑定 x86_64_efi 分区布局；本项目改为 IB 原生 PACKAGES 机制，效果等价且适配任意 IB 支持的机型）
