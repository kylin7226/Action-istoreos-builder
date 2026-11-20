# Cyber3588-AIB iStoreOS 固件构建

使用官方 iStoreOS ImageBuilder，为 Cyber Cyber3588-AIB（RK3588）组装固件，不修改或编译上游源码。

## 固件内容

- 目标：`rockchip/armv8`，profile `cyber_cyber3588-aib`。
- 官方 IB 当前基线为 iStoreOS 25.12 / Linux 6.12；下载地址会更新，每次记录实际 IB SHA256。
- 默认 LAN：`192.168.199.1`；默认网口沿用官方配置，不自行修改网口映射。
- LuCI 管理界面与中文语言包。
- 可选 iStore、软件包管理、ttyd、UPnP、argon。
- 可选 Docker、dockerd、Compose、dockerman。
- ddns-go、frpc/frps、NFS 服务、GPU/VPU/RGA 内核驱动、传感器工具。
- 可选 SamWaf `v1.3.24` 静态 ARM64 二进制及自有 LuCI 管理页。
- Open-Box 原生部署所需内核模块（tun/nft-queue/tproxy/socket/macvlan/ipvlan）、ip-full、BBR（开机启用）。
- mwan3 + LuCI 负载均衡界面，支持双 PPPoE 多出口，配置见 [docs/multiwan.md](docs/multiwan.md)。

容器硬件加速还需要容器内配套的用户态库和设备透传；安装内核驱动不等于已验证转码或 Redroid 能运行。

## 构建

在 GitHub Actions 中运行 `Build iStoreOS for Cyber3588-AIB`，或推送涉及 workflow、recipe、files、scripts、tests 的改动。

| 参数 | 默认 | 说明 |
|---|---|---|
| `lan_ip` | `192.168.199.1` | 全新刷写的 IPv4 管理地址，按默认 /24 校验；保留的网络配置不覆盖 |
| `rootfs_partsize` | `4096` | 镜像 rootfs 分区大小，512–32768 MB |
| `with_gui_extras` | `true` | iStore / ttyd / UPnP / argon 等附加界面 |
| `include_docker` | `true` | Docker 容器管理栈；关闭时显式排除顶层包 |
| `include_samwaf` | `true` | SamWaf 二进制、服务、配置和 LuCI 页面 |

push 和定时任务使用默认选项。每天 03:23 UTC 比较官方 IB 哈希，只有变化时重建；它不会检测第三方 feed 的单独更新，更新这些包请手动构建。

所有发布共用 concurrency 组，不同时覆盖滚动 Release；GitHub 的 pending 队列可能合并等待中的运行，并非无限 FIFO 队列。PR 只跑测试，不发布固件。

## 下载与回滚

- 日期历史：`vYYYY.MM.DD.<run_number>.<run_attempt>`，不覆盖历史版本。重跑使用新的 attempt，避免撞名。
- `firmware`：滚动下载入口。多文件替换不是原子操作；要求一致性时优先下载已完成的日期 Release。
- 下载 `*-squashfs-sysupgrade.img.gz`。同一 Release 的其余文件也下载后运行 `sha256sum -c SHA256SUMS.txt`；仅下载镜像时，核对清单中的镜像行。
- `build-commit.txt` 是实际构建提交；`build-config.json` 记录选项和包清单；`source-checksums.txt` 记录 IB、第三方 APK、SamWaf 下载哈希。
- 日期标签绑定实际构建 SHA；滚动标签本身不表示最新源码提交。
- 临时 Actions artifact 保留 30 天，内容与发布文件集合一致。

历史镜像可用于回刷，但保留配置回刷并不保证应用数据库向后兼容。刷写前独立备份配置、SamWaf 数据和容器数据；设备型号或分区布局不同不可直接套用升级步骤。

## SquashFS 与磁盘空间

发布 SquashFS 镜像：只读根文件系统加可写 overlay，便于恢复固件原始文件。

`rootfs_partsize` 不是“128 GB eMMC 最终可用空间”的保证。分区扩容、overlay 容量及升级保留行为由实际官方镜像、启动介质和升级方式决定。首次启动请在设备上检查：

```sh
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS
df -h / /overlay
mount
```

若 `lsblk` 不可用，可使用 `block info` 和 `cat /proc/partitions`。不要在未确认现有分区布局前新建分区。

全新刷写与 sysupgrade 都会清理或覆盖设备数据，先备份，再按设备和 iStoreOS 的对应升级流程操作。启动后立即检查管理地址、设置管理员密码并确认 WAN 防火墙策略。

`uci-defaults` 可能在升级时运行，不能笼统认为只运行于首次刷机。自定义 LAN 脚本使用 iStoreOS 的升级标记避免覆盖保留配置；SamWaf 首启脚本不覆盖已有配置，升级时不强行重新启用被关闭的服务。

## SamWaf

入口：LuCI「服务 → SamWaf 防火墙」。默认控制台为设备管理地址的 HTTP 26666 端口。

- 服务由 procd 托管，固定工作目录 `/opt/samwaf`；不使用 systemd 的 install/start 子命令。
- 管理端口写入 UCI，并在服务启动时同步到 `conf/config.yml`。运行中的服务改端口会检查进程与 HTTP 响应，失败尝试恢复原端口。
- 查询权限与写权限分离；只读账号不能通过助手启动、停止、改端口或升级。
- 修改用户名、自定义密码在 SamWaf 控制台完成。用户名不保证一直是 `admin`。
- 初始密码由 SamWaf 生成，通常在 `/opt/samwaf/data/initial_password.txt`；忘记密码时使用页面提供的 SSH/终端恢复指引。交互式 `resetpwd` 不通过 RPC 自动喂输入，以免误重置账号或卡住请求。
- iframe 按需加载。HTTPS 混合内容或 SamWaf 防嵌入策略可能阻止显示，此时使用新标签页。

### 设备端升级

填写官方版本号并确认。后台任务由 procd 托管，使用互斥锁阻止与其他控制操作冲突；下载校验 SHA256 并检查 ARM64 静态 ELF，不依赖 `nohup`、`base64`、`timeout`、`file`。

替换前停止服务并备份二进制及 `conf/data/ssl`。新版本通过进程和 HTTP 健康检查后才记录成功；失败尝试恢复原二进制、数据和原运行状态。原先停止的服务在验证后仍保持停止。回滚失败会保留备份路径并在日志中提示，不谎报成功。

升级需要足够的可写空间容纳下载、旧二进制及数据备份。断电、磁盘故障或应用深层功能故障不能由一次 HTTP 检查排除，请始终保留独立备份。设备端升级文件写在 overlay；恢复出厂或不保留数据刷写可能回到固件内置版本。

## 软件包与信任边界

- `recipe/packages-add.txt`：追加包。
- `recipe/packages-remove.txt`：显式剔除包，包含 defensive no-op 条目。
- 禁止同名重复、追加/剔除冲突和无效名称；保留 Docker/NFS/GPU/风扇相关必要依赖。
- 第三方包通过 APK 的签名索引选择版本并下载，使用仓库内 dllkids 公钥验证索引，再由 `apk fetch` 按索引中的身份校验包内容，不再解析 HTML 或按字符串猜版本。该源的单个 APK 不一定带可独立验证的签名，不能将索引信任误写成逐包签名。
- mwan3 / luci-app-mwan3 / luci-i18n-mwan3-zh-cn 不在 iStoreOS IB 与 dllkids feed 中，取自官方 OpenWrt `25.12.6` release 的 noarch APK（架构无关脚本，与 iStoreOS 25.12 同代）。workflow 固定版本与整文件 SHA256（已交叉核对官方服务器和清华镜像），官方源失败时回退清华镜像，哈希记录进 `source-checksums.txt`。这是 SamWaf 式的 HTTPS+校验和完整性模型，不是逐包签名验证；升级 OpenWrt 基线时需重新固定版本与哈希。
- 构建仍信任官方 IB 和被信任的包发布者；校验和用于完整性，不代表安全审计。
- 用户添加新的第三方包时，需更新 workflow 的支持映射；依赖仍由 IB 的 APK 求解器处理。

## 验证与本地测试

CI 检查精确型号的非空镜像、gzip 完整性、全部要求安装的包、禁止包、关键设备驱动，以及 SamWaf 运行命令和页面文件，之后才生成发布校验清单。

```sh
python3 -m unittest discover -s tests -v
node tests/samwaf.test.js
# 浏览器模拟预览（不连接设备）：http://127.0.0.1:8765
python3 tests/preview.py
```

这些测试不能替代真机验证。部署前仍需验证网口、风扇、Docker/NFS、硬件加速、SamWaf 初始配置、升级与密码恢复。浏览器测试中的模拟 RPC 也不等于已验证设备上的 rpcd/procd。
