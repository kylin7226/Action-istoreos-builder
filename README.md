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
3. 构建完成后取固件：
   - **Release（推荐）**：仓库 → Releases → `firmware`（滚动 tag，始终是最新固件），下载 `*-squashfs-sysupgrade.img.gz`
   - 或 run 页面底部 Artifacts（每次 run 的临时产物，保留 30 天）

### workflow_dispatch 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `lan_ip` | 192.168.199.1 | LAN 管理地址 |
| `rootfs_partsize` | 4096 | rootfs 分区大小 (MB) |
| `with_gui_extras` | true | iStore 商店 / quickstart / 磁盘管理 / ttyd / argon 主题（中文） |
| `include_docker` | true | Docker + dockerman |

自动触发：push 改动 `recipe/**` 或 workflow 本身立即构建；**每天定时**（03:23 UTC）拉取官方 IB 的 sha256 与上次构建记录比对，**仅当官方 IB 有更新时才自动重建**（记录存于 `firmware` Release 的 `ib-source-sha256.txt` 资产）。因发布到固定滚动 Release，多个构建用 concurrency 串行化，避免互相覆盖。

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

两个列表当前内容：

- **add**：ddns-go + luci-app-ddns-go（feed 注入）；frpc + frps（内网穿透，feed 注入）；RK3588 GPU 驱动 `kmod-rkgpu-bifrost-csf`（Mali-G610，自动带 CSF 固件）+ `kmod-drm-rockchip` + `libdrm`；多媒体内核驱动 `kmod-rk_vcodec`（RKMPP VPU）+ `kmod-rga3`（RGA 2D，仅内核驱动，用户态库交给容器）；`lm-sensors`（风扇/温度监控，设备带风扇）；NFS 服务器全套 `luci-app-nfs` + `nfs-kernel-server` 等
- **remove**：对照 bluise 精简清单的 300+ 项负号剔除（WiFi/调制解调器/NAS 网盘/SMB/x86 驱动等；均不在镜像中的为防御性空操作，防上游 IB 更新后默认引入）。注意：所保留包的硬依赖（如 `libsensors5` ← lm-sensors、`rpcbind` ← NFS、`libdrm`/drm-helper ← GPU）已从剔除名单撤销，否则 apk 依赖冲突构建失败

基线固件包含：
- **profile 默认包**（IB 保证）：内核、驱动（kmod-r8169 网卡 / kmod-nvme / kmod-ata-ahci-dwc / kmod-rknpu / 风扇温控）、dnsmasq、firewall4、dropbear 等
- **管理界面底座**（显式列出，缺了进不去后台）：uhttpd、luci、luci-mod-admin-full、防火墙/PPPoE（ppp/ppp-mod-pppoe/kmod-pppoe 完整拨号链）及中文汉化
- **GUI 套件**（`with_gui_extras=true` 时）：iStore 商店、软件包管理、ttyd、UPnP、argon 主题（quickstart/diskman 已按需求移除）
- **容器栈**（`include_docker=true` 时）：docker/dockerd/docker-compose/dockerman 及依赖链

改完 recipe 后 push 即自动重建；构建末尾会对 manifest 逐项断言（管理页必需包必须在、剔除项必须不在、设备驱动包必须在），不满足直接 fail，避免"刷完卡才发现"。

### 后续计划包的来源备忘

- `docker / dockerd / docker-compose / luci-app-dockerman`：IB 本地仓库自带，直接写进 add 列表（或勾 `include_docker`）
- OAF（`appfilter / kmod-oaf / luci-app-oaf / luci-i18n-oaf-zh-cn`）：IB 本地仓库自带 v7 全套，内核版本匹配
- `ddns-go / luci-app-ddns-go`：dllkids feed（`https://down.dllkids.xyz/openwrt-feed/25.12/aarch64_generic/`）
- `luci-app-mosdns` + `geo2txt / v2ray-geoip / v2ray-geosite`：同上 dllkids feed
- `mosdns` 主程序：dllkids feed 没有，在 ImmortalWrt snapshots（`https://downloads.immortalwrt.org/snapshots/packages/aarch64_generic/packages/`）
- **mpp/librga 用户态库**（`librockchip_mpp` / `librga`）：IB、dllkids feed、ImmortalWrt 官方仓库都没有现成 apk；社区只有 Debian/glibc 版（如 tsukumijima/librga-rockchip），与本固件 musl 不兼容。**已决定采用 Docker 方案**：固件只保留内核驱动 `kmod-rk_vcodec` + `kmod-rga3`（生成 `/dev/mpp_service`、`/dev/rga`），用户态库由容器镜像自带（如 nyanmisaka 的 jellyfin 镜像），把 `/dev/mpp_service`、`/dev/rga`、`/dev/dri` 映射进容器即可硬解。曾经用过的源码编译 workflow（`build-rkmpp.yml` → Release `rkmpp-apk`）已删除，不再维护。
- **Android in Docker（Redroid 等）**：内核已内建 binder（`CONFIG_ANDROID_BINDER_IPC=y` + `CONFIG_ANDROID_BINDERFS=y`，rockchip target 覆盖打开，非模块），binderfs 挂载 `/dev/binderfs` 后可直接跑 Redroid 11+（用 memfd，无需 ashmem）。binder 是内建的，无需加任何包。

第三方 .apk 的接入方式：workflow 里加一步下载到 `$IB_DIR/packages/`，IB 构建时会自动 `apk mkndx --allow-untrusted` 重建索引，无需签名。

## 刷写

- **SD 卡 / eMMC**：`gunzip -c xxx-sysupgrade.img.gz | sudo dd of=/dev/sdX bs=4M conv=fsync`，或用 balenaEtcher / Rufus
- **已有 iStoreOS/OpenWrt 系统**：从 `firmware` Release 下载 `*-squashfs-sysupgrade.img.gz` → 系统 → 备份/升级 → 刷写 sysupgrade 镜像（保留配置，一键升级）。注意保留配置的升级不会触发 uci-defaults，自定义 LAN IP 只在干净首刷时生效
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
