# Action-istoreos-builder

用 **GitHub Actions + iStoreOS 官方 ImageBuilder** 为 **Cyber Cyber3588-AIB (RK3588)** 打包定制固件。
不编译源码、几分钟出包，通过 `recipe/` 两个清单自由增删软件包，构建完自动发布到滚动 Release，并每天检查官方 IB 更新、有更新才自动重建。

---

## 一、这是什么 / 为什么这么做

iStoreOS 官方提供了预编译的 **ImageBuilder (IB)**：内核和驱动都已编译好，`make image` 只是按你给的 `PACKAGES=` 清单从本地 apk 仓库里挑包、组装 rootfs、生成镜像。

- **快**：不编译源码，一次构建几分钟（源码全编译要 1~3 小时）。
- **稳**：内核、驱动、设备定义全部来自官方 IB，和 istoreos-25.12 分支一致，不会因自己改配置而起不来。
- **可控**：加什么包、删什么包全写在 `recipe/` 里，一目了然、可版本管理。
- **零本地依赖**：构建跑在 GitHub Actions 免费 runner 上，本机不需要任何交叉编译环境。

| 项目 | 值 |
|---|---|
| 固件基线 | iStoreOS 25.12（官方 IB，rockchip / armv8） |
| 内核版本 | 6.12（RK3588 target 锁定，官方无 6.18） |
| 目标设备 profile | `cyber_cyber3588-aib` |
| LAN 管理地址 | `192.168.199.1`（首启由 uci-defaults 写入，可改） |
| 网口 | LAN = eth1，WAN = eth0（官方 base-files 内置，未覆盖） |
| 文件系统 | SquashFS（只读根 + 可写 overlay，overlay 首启自动扩展到占满 eMMC） |
| 主要产物 | `istoreos-rockchip-armv8-cyber_cyber3588-aib-squashfs-sysupgrade.img.gz` |

---

## 二、固件里都有什么

**基线（官方 profile 默认包，IB 保证）**
内核 + RK3588 驱动（r8169 网卡 / NVMe / SATA / rknpu NPU / 风扇温控 hwmon-pwmfan+thermal）、dnsmasq、firewall4、dropbear 等。

**管理界面（显式列出，缺了进不去后台）**
uhttpd、luci、luci-mod-admin-full、防火墙 / PPPoE 完整拨号链，全套中文汉化。

**GUI 套件**（`with_gui_extras=true` 时）
iStore 商店、软件包管理、ttyd 网页终端、UPnP、argon 主题。（quickstart / diskman 已按精简需求移除）

**容器栈**（`include_docker=true` 时）
docker / dockerd / docker-compose / luci-app-dockerman 及依赖链。

**recipe 追加的 15 个包**（见 `recipe/packages-add.txt`）

| 用途 | 包 |
|---|---|
| DDNS | `ddns-go` + `luci-app-ddns-go`（第三方 feed 注入） |
| 内网穿透 | `frpc` + `frps`（第三方 feed 注入） |
| GPU（Mali-G610） | `kmod-rkgpu-bifrost-csf` + `kmod-drm-rockchip` + `libdrm` |
| 多媒体硬解（内核驱动） | `kmod-rk_vcodec`（RKMPP VPU，生成 `/dev/mpp_service`）、`kmod-rga3`（RGA 2D，生成 `/dev/rga`） |
| 传感器 / 风扇观测 | `lm-sensors`（设备带风扇；自动控温由内核完成，此包仅用于 `sensors` 读数） |
| NFS 服务器 | `luci-app-nfs` + `nfs-kernel-server` + `nfs-kernel-server-utils` + `nfs-utils`（内核态 NFS） |

**recipe 剔除的 336 个包**（见 `recipe/packages-remove.txt`）
WiFi / 3G-4G-5G 调制解调器 / NAS 网盘（linkease/samba/webdav/mergerfs/unishare）/ CIFS / x86 显卡网卡固件 / RAID / perl 全家等。其中大部分是**防御性空操作**（当前镜像本就没有，负号剔除只是防止上游 IB 更新后默认引入）。

> ⚠️ **依赖红线**：所保留包的硬依赖（`libsensors5`←lm-sensors、`rpcbind`←NFS、`libdrm`/drm-helper←GPU）已从剔除名单撤销，否则 apk 会依赖冲突、构建直接失败。

**内置第三方 feed（`files/`）**
固件已预置 [dllkids openwrt-feed](https://down.dllkids.xyz/openwrt-feed/25.12/)（kenzok8 系第三方包源，含 ddns-go / frp / mosdns 壳 / openclash 等 623 个包）的仓库地址与签名公钥。开机后 `apk update` 或在 LuCI「软件包管理」里即可直接安装该 feed 的包，等效于跑官方 `openwrt-feed-setup.sh` 但无需联网执行脚本。`files/` 下所有文件构建时原样合并进 rootfs，可继续往里放 overlay 文件。

**关于硬件加速（VPU/RGA）的取舍**
固件只装**内核驱动**，不装用户态库（`librockchip_mpp`/`librga`）——因为这些库在 musl 下没有现成 apk（社区只有 Debian/glibc 版，不兼容）。用法是：容器镜像自带用户态库（如 nyanmisaka 的 jellyfin），Docker 把 `/dev/mpp_service`、`/dev/rga`、`/dev/dri` 透传进容器即可硬解。曾用过的源码编译 workflow（`build-rkmpp.yml` → Release `rkmpp-apk`）已删除。

**Android in Docker（Redroid）**
内核已内建 binder（`CONFIG_ANDROID_BINDER_IPC=y` + `CONFIG_ANDROID_BINDERFS=y`，rockchip target 覆盖打开，非模块）。挂载 binderfs 到 `/dev/binderfs` 后可直接跑 Redroid 11+（用 memfd，无需 ashmem），无需加任何包。

**SamWaf（Web 应用防火墙）**
固件集成 [SamWaf](https://github.com/samwafgo/SamWaf)——开源轻量 WAF，官方 release 的**静态 aarch64 Go 二进制**（已实测 `statically linked`，musl 兼容，内置加密 SQLite 无外部依赖）。

- **装入方式**：`build.yml` 按 `env.SAMWAF_VERSION`（默认 `v1.3.24` 正式线）从官方 GitHub release 下载 `SamWaf_Linux_arm64.<tag>.tar.gz`，校验 sha256 + 确认「ARM aarch64 / 静态链接」后装到 `/usr/bin/samwaf`。**88M 二进制不入 git 树**，仅构建时拉取。
- **服务托管**：procd 脚本 `/etc/init.d/samwaf` 前台运行（SamWaf 自带的 `install/start/stop` 是给 systemd 的，OpenWrt 无 systemd 故不用）；工作目录 `/opt/samwaf`（可写 overlay，运行时生成 `conf/ data/ logs/ ssl/`）。首启由 `files/etc/uci-defaults/99-samwaf` 自动 `enable + start`。
- **LuCI 管理页**：自带一个轻量自定义应用（菜单「服务 → SamWaf 防火墙」，纯 overlay 的 JSON+JS+shell，不编译）。前端只渲染，所有特权操作经 rpcd `file.exec` 调后端助手 `/usr/libexec/samwafctl`（固定子命令、端口整数校验、版本号白名单，杜绝注入）。能做：
  - **服务控制**：启动 / 停止 / 重启 / 开机自启开关 / 状态（运行中、PID、版本、端口）。
  - **管理端口**：改端口写入 UCI（`/etc/config/samwaf`）并同步到 `conf/config.yml` 的 `local_port`，服务在跑则自动重启生效（端口只在 SamWaf 启动时读取）。
  - **重置密码**：调 SamWaf 的 `resetpwd` 生成**新的随机密码**并显示。注意 SamWaf 命令行只能随机生成、用户名固定 `admin`；**自定义密码 / 改名只能登录其控制台后在里面改**。
  - **升级**：填版本号 → 设备端 `curl` 从官方 release 拉 arm64 静态包、校验 sha256、原子替换 `/usr/bin/samwaf`、重启（后台执行 + 页面轮询日志）。新二进制写在 squashfs 的 overlay 层，重启保留，但恢复出厂/不带配置 sysupgrade 会回到固件内置版本。
  - **控制台直达**：「新标签页打开」始终可用；「内嵌 iframe」尽力而为——SamWaf 后台可能设 `X-Frame-Options`/CSP 防点击劫持，或 LuCI 走 HTTPS 时被混合内容拦截，打不开就用新标签页。
- **访问**：`http://<LAN_IP>:26666`，账号 `admin`，初始随机密码见 `/opt/samwaf/data/initial_password.txt`（**首次登录后立即改**）。默认只 LAN 可达（WAN 侧被防火墙挡），需要外网访问请自行开防火墙/走 frp。
- **开关**：`include_samwaf=false` 可不集成（会一并移除服务桩、LuCI 管理页与后端助手）。改版本只需改 `build.yml` 的 `SAMWAF_VERSION` 一行。

---

## 三、使用方法

### 1. 部署到你自己的仓库

在 GitHub 建一个空仓库，把本目录内容推上去：

```bash
cd Action-istoreos-builder
git init && git add -A && git commit -m "init: cyber3588-aib IB builder"
git remote add origin git@github.com:<你的用户名>/Action-istoreos-builder.git
git push -u origin main
```

> workflow 已声明 `permissions: contents: write`，用于创建/更新 `firmware` Release。

### 2. 触发构建

三种方式，任选：

- **手动**：仓库页面 → Actions → `Build iStoreOS for Cyber3588-AIB` → Run workflow（可调参数，见下表）。
- **推送**：改动 `recipe/**`、`files/**` 或 workflow 本身并 push，自动构建。
- **定时**：每天 03:23 UTC 自动检查官方 IB 是否更新，**仅有更新时才重建**（见下文「自动更新机制」）。

### 3. 取固件

构建完成后：

- **Release（推荐）**：仓库 → Releases → **`firmware`**（滚动 tag，永远是最新固件），下载 `*-squashfs-sysupgrade.img.gz`。
- **Artifacts**：run 页面底部，每次 run 的临时产物（保留 30 天）。

### workflow_dispatch 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `lan_ip` | `192.168.199.1` | LAN 管理地址（首启由 uci-defaults 写入） |
| `rootfs_partsize` | `4096` | rootfs 分区大小 (MB)；剩余空间刷完后可另建分区挂载 |
| `with_gui_extras` | `true` | iStore 商店 / 软件包管理 / ttyd / UPnP / argon 主题 |
| `include_docker` | `true` | Docker + dockerman 容器栈 |
| `include_samwaf` | `true` | SamWaf Web 应用防火墙（静态二进制 + procd 服务，端口 26666） |

---

## 四、自动更新机制

- **串行化**：所有构建进同一个 concurrency 组（`cancel-in-progress: false`），同一时刻只跑一个，其余排队，避免并发写覆盖同一个滚动 Release。
- **定时门控**（`check-upstream` job，仅 schedule 触发）：拉取官方 IB 的 `sha256sums`，与上次构建记录比对——记录存在 `firmware` Release 的 **`ib-source-sha256.txt`** 资产里（**不进 git 树**）。哈希不同或首次运行才触发构建，否则跳过。
- **push / 手动**：`check-upstream` 跳过，`build` 总是执行。
- **发布**：每次构建末尾把固件 + manifest + SHA256SUMS + ib-source-sha256.txt 用 `--clobber` 覆盖上传到 `firmware` Release。

**构建自检**：`make image` 后会对 manifest 逐项断言——管理页必需包必须在、recipe 剔除项必须不在、设备驱动包（r8169/nvme/rknpu）必须在；任一不满足直接 fail，避免「刷完卡才发现」。

---

## 五、定制软件包（recipe/）

| 文件 | 作用 | 机制 |
|---|---|---|
| `recipe/packages-add.txt` | 追加安装 | 逐行追加到 `PACKAGES=`，依赖由 apk 自动解析 |
| `recipe/packages-remove.txt` | 剔除 | 逐行转成 `-包名` 负号语法 |

- `#` 开头为注释，空行忽略。
- `PACKAGES=` 是「profile 默认包 + 追加」语义，负号项做剔除；指向不存在的包是安全的空操作。
- **写错包名会让构建失败**（no such package）。
- 只能剔除「可选包」；被其他包硬依赖的包剔不掉（apk 会报错）——这就是上面的「依赖红线」。

改完 recipe 直接 push 即自动重建。

### 包来源与注入方式

1. **官方 IB 自带 `packages/`**：直接写包名即可（docker 全家、OAF `appfilter/kmod-oaf/luci-app-oaf` 等）。
2. **第三方 feed 的 `.apk`**（如 dllkids feed）：`build.yml` 的 `Inject third-party feed packages` 步骤会按 `packages-add.txt` 下载对应 `.apk` 到 `$IB_DIR/packages/`，IB 构建时自动 `apk mkndx --allow-untrusted` 重建索引，无需签名。当前已支持注入：ddns-go / luci-app-ddns-go / frpc / frps / luci-app-frpc / luci-app-frps / luci-app-mosdns / geo2txt / v2ray-geoip / v2ray-geosite。
3. **上游快照仓库**：如 `mosdns` 主程序（dllkids feed 只有 luci 壳，主程序在 ImmortalWrt snapshots `https://downloads.immortalwrt.org/snapshots/packages/aarch64_generic/packages/`），需在 workflow 里另加一步下载。

> 在 workflow 里注入新 feed 包时，请同时更新 `build.yml` 的 `inject` 分支（用 `[>/]` 锚定文件名开头，避免 `frpc-` 误匹配到 `luci-app-frpc-`）。

---

## 六、刷写与首次启动

### SquashFS vs ext4 —— 为什么选 SquashFS

| | SquashFS（本固件） | ext4 |
|---|---|---|
| 根文件系统 | 只读、压缩 | 读写、不压缩 |
| 配置/改动 | 存到单独的可写 overlay（`rootfs_data`） | 直接写在根上 |
| 恢复出厂 | 擦掉 overlay 即可，根永远干净 | 无自动机制，改坏需重刷 |
| 断电/装坏包 | 只读根几乎不损坏，failsafe 可救 | 风险更高，可能需串口救砖 |
| 一键升级 | 语义清晰，每次刷根回到纯净态 | 语义不同，升级不可预测 |
| 128G eMMC | overlay 首启自动扩展到占满整盘，空间不浪费 | 单个大读写分区，同样占满 |

对「无人值守 + 跑容器 + 一键升级」的场景，SquashFS 更稳、更可预测，故选它。（IB 默认两种都产出，但本 workflow 只发布 squashfs。）

### 刷写方式

- **SD 卡 / eMMC 全新刷写**：
  ```bash
  gunzip -c *-squashfs-sysupgrade.img.gz | sudo dd of=/dev/sdX bs=4M conv=fsync
  ```
  或用 balenaEtcher / Rufus。（首刷厂商镜像可能需要设备专用工具。）
- **已有 iStoreOS/OpenWrt 系统（推荐，一键升级）**：从 `firmware` Release 下载 `*-squashfs-sysupgrade.img.gz` → LuCI「系统 → 备份/升级」→ 刷写 sysupgrade 镜像，保留配置。

### 首次启动

1. 访问 `http://192.168.199.1`，`root` 无密码，**建议立即设置密码**。
2. 保留配置的 sysupgrade 升级**不会**触发 uci-defaults，自定义 LAN IP 只在干净首刷时生效。

---

## 七、目录结构

```
Action-istoreos-builder/
├── .github/workflows/build.yml   # 构建 + 发布 + 定时检查的完整 CI
├── recipe/
│   ├── packages-add.txt          # 要追加安装的包（当前 15 个）
│   └── packages-remove.txt       # 要剔除的包（当前 336 项，含防御性空操作）
├── files/                        # 原样合并进镜像 rootfs 的 overlay 文件
│   ├── etc/
│   │   ├── apk/
│   │   │   ├── repositories.d/dllkids-feed.list   # 第三方 feed 仓库地址
│   │   │   └── keys/dllkids-feed.pub.pem          # feed 签名公钥
│   │   ├── config/samwaf                         # SamWaf 的 UCI 配置（管理端口）
│   │   ├── init.d/samwaf                         # SamWaf 的 procd 服务脚本（前台托管 + 端口同步）
│   │   └── uci-defaults/99-samwaf                # 首启自动 enable + start SamWaf
│   ├── usr/
│   │   ├── libexec/samwafctl                     # LuCI 管理页的后端助手（特权操作集中处）
│   │   └── share/
│   │       ├── luci/menu.d/luci-app-samwaf.json  # LuCI 菜单项「服务 → SamWaf 防火墙」
│   │       └── rpcd/acl.d/luci-app-samwaf.json   # 仅授权 file.exec samwafctl 的 ACL
│   └── www/luci-static/resources/view/samwaf.js  # LuCI 管理页前端（状态/控制/端口/密码/升级/控制台）
└── README.md
```

---

## 八、本地构建（可选，不经 CI）

```bash
# 依赖：gawk（必须 GNU awk，mawk 不行）、zstd、build-essential 等
mkdir ib && cd ib
curl -fLO https://fw.koolcenter.com/iStoreOS/ib/rk3xxx/istoreos-imagebuilder-rockchip-armv8.Linux-x86_64.tar.zst
tar --zstd -xf *.tar.zst && cd istoreos-imagebuilder-*/
make info | grep -A3 '^cyber_cyber3588-aib:'   # 确认 profile 存在
make -j$(nproc) image PROFILE="cyber_cyber3588-aib" \
  PACKAGES="uhttpd luci luci-mod-admin-full ..." FILES=...
# 产物: bin/targets/rockchip/armv8/
```

---

## 参考项目

- [ayi3030/istoreos-r1plus-builder](https://github.com/ayi3030/istoreos-r1plus-builder)：官方 IB + GitHub Actions 的构建方式与包列表经验。
- [bluise/istoreos](https://github.com/bluise/istoreos)：recipe 增删包思路（其本体是「下载官方 x86 成品镜像→解包 squashfs→增删→重打包」，绑定 x86_64_efi 分区布局；本项目改为 IB 原生 `PACKAGES` 机制，效果等价且适配任意 IB 支持的机型）。
