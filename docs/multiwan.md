# 电信 + 移动双 PPPoE 多出口（mwan3）配置与使用

适用固件：本仓库构建的 Cyber3588-AIB iStoreOS（已含 mwan3 / luci-app-mwan3 /
ppp / ppp-mod-pppoe / ip-full，策略路由内核内建）。

三个网口分工：

| 物理口 | 接口 | 用途 |
|---|---|---|
| 口1 | eth0 → `wan`（pppoe-wan） | 电信 PPPoE |
| 口2 | eth2 → `wan2`（pppoe-wan2） | 移动 PPPoE |
| 口3 | eth1 → `lan` | LAN，192.168.199.1/24 |

> 板级默认映射是 eth1=LAN、eth0=WAN，第三口为 eth2（PCIe r8169）。
> eth 编号与外壳丝印不一定一致，先按第 0 步确认。

---

## 0. 确认物理网口对应关系

SSH 登录路由器（root@192.168.199.1）后：

```sh
ip -br link
```

只插一根网线到某个口，看哪个 eth 出现 `LOWER_UP`（或 `cat /sys/class/net/eth*/carrier`
输出 1）。依次确认电信、移动、LAN 三口对应的 eth 名。下文按
电信=eth0、移动=eth2、LAN=eth1 书写，若实际不同请替换。

## 1. 网络接口（PPPoE 拨号）

把下面整段复制执行，**先替换两个账号密码**：

```sh
# 电信（默认 wan 已存在，设备 eth0，改为 PPPoE）
uci set network.wan.proto='pppoe'
uci set network.wan.username='电信宽带账号'
uci set network.wan.password='电信宽带密码'
uci set network.wan.mtu='1492'
uci set network.wan.metric='10'
uci set network.wan.ipv6='auto'

# 移动（新建 wan2，设备 eth2）
uci set network.wan2=interface
uci set network.wan2.device='eth2'
uci set network.wan2.proto='pppoe'
uci set network.wan2.username='移动宽带账号'
uci set network.wan2.password='移动宽带密码'
uci set network.wan2.mtu='1492'
uci set network.wan2.metric='20'
uci set network.wan2.ipv6='auto'

uci commit network
```

说明：
- `metric 10/20`：mwan3 停用时的兜底顺序（电信优先），不影响 mwan3 工作时的分流。
- `mtu 1492`：PPPoE 标准值；MSS 钳制由防火墙 wan zone 的 mtu_fix 完成（默认开）。
- LAN 口无需改动（出厂 99-lan-ip 已设 192.168.199.1）。

## 2. 防火墙：wan2 加入 wan zone

```sh
# 先确认 @zone[1] 是 wan（输出应为 wan）
uci get firewall.@zone[1].name
uci add_list firewall.@zone[1].network='wan2'
uci commit firewall
```

两个 WAN 共用 wan zone 的 masquerade 与 mtu_fix，LAN→任一 WAN 可转发。

## 3. mwan3 完整配置

整段复制执行：

```sh
uci -q delete mwan3.globals
uci set mwan3.globals=globals
uci set mwan3.globals.mmx_mask='0x3F00'
uci set mwan3.globals.local_source='lan'

# ---- 接口健康检查 ----
uci set mwan3.wan=interface
uci set mwan3.wan.enabled='1'
uci set mwan3.wan.family='ipv4'
uci set mwan3.wan.track_method='ping'
uci set mwan3.wan.reliability='1'
uci set mwan3.wan.count='1'
uci set mwan3.wan.timeout='2'
uci set mwan3.wan.interval='5'
uci set mwan3.wan.down='3'
uci set mwan3.wan.up='3'
uci add_list mwan3.wan.track_ip='223.5.5.5'
uci add_list mwan3.wan.track_ip='119.29.29.29'

uci set mwan3.wan2=interface
uci set mwan3.wan2.enabled='1'
uci set mwan3.wan2.family='ipv4'
uci set mwan3.wan2.track_method='ping'
uci set mwan3.wan2.reliability='1'
uci set mwan3.wan2.count='1'
uci set mwan3.wan2.timeout='2'
uci set mwan3.wan2.interval='5'
uci set mwan3.wan2.down='3'
uci set mwan3.wan2.up='3'
uci add_list mwan3.wan2.track_ip='114.114.114.114'
uci add_list mwan3.wan2.track_ip='223.6.6.6'

# ---- 成员（metric 决定主备，weight 决定同 metric 下的负载比例）----
uci set mwan3.wan_m1_w1=member
uci set mwan3.wan_m1_w1.interface='wan'
uci set mwan3.wan_m1_w1.metric='1'
uci set mwan3.wan_m1_w1.weight='1'

uci set mwan3.wan2_m1_w1=member
uci set mwan3.wan2_m1_w1.interface='wan2'
uci set mwan3.wan2_m1_w1.metric='1'
uci set mwan3.wan2_m1_w1.weight='1'

uci set mwan3.wan_m2_w1=member
uci set mwan3.wan_m2_w1.interface='wan'
uci set mwan3.wan_m2_w1.metric='2'
uci set mwan3.wan_m2_w1.weight='1'

uci set mwan3.wan2_m2_w1=member
uci set mwan3.wan2_m2_w1.interface='wan2'
uci set mwan3.wan2_m2_w1.metric='2'
uci set mwan3.wan2_m2_w1.weight='1'

# ---- 策略 ----
# 负载均衡：两条同 metric，按 weight 1:1 分担；任一离线自动全切另一条
uci set mwan3.balanced=policy
uci add_list mwan3.balanced.use_member='wan_m1_w1'
uci add_list mwan3.balanced.use_member='wan2_m1_w1'
uci set mwan3.balanced.last_resort='default'

# 主备：电信主、移动备（电信恢复自动切回）
uci set mwan3.failover=policy
uci add_list mwan3.failover.use_member='wan_m1_w1'
uci add_list mwan3.failover.use_member='wan2_m2_w1'
uci set mwan3.failover.last_resort='default'

# 单出口策略（按目的分流时引用）
uci set mwan3.telecom_only=policy
uci add_list mwan3.telecom_only.use_member='wan_m1_w1'
uci set mwan3.telecom_only.last_resort='unreachable'

uci set mwan3.mobile_only=policy
uci add_list mwan3.mobile_only.use_member='wan2_m1_w1'
uci set mwan3.mobile_only.last_resort='unreachable'

# ---- 规则 ----
# 默认全部走负载均衡；sticky 让同一源 IP 在 600 秒内固定同一出口，
# 避免网银/登录态因出口 IP 跳变异常。不需要可去掉 sticky 两行。
uci set mwan3.default_rule=rule
uci set mwan3.default_rule.dest_ip='0.0.0.0/0'
uci set mwan3.default_rule.use_policy='balanced'
uci set mwan3.default_rule.sticky='1'
uci set mwan3.default_rule.sticky_timeout='600'

uci commit mwan3
```

## 4. DNS（避免两运营商 DNS 互串）

```sh
uci -q delete dhcp.@dnsmasq[0].server
uci add_list dhcp.@dnsmasq[0].server='223.5.5.5'
uci add_list dhcp.@dnsmasq[0].server='119.29.29.29'
uci set dhcp.@dnsmasq[0].noresolv='1'
uci commit dhcp
```

`noresolv=1` 让 dnsmasq 忽略 PPPoE 下发的运营商 DNS，统一用公共 DNS，
防止解析结果与出口线路不一致。

## 5. 生效与开机自启

```sh
/etc/init.d/network restart
/etc/init.d/firewall restart
/etc/init.d/dnsmasq restart
/etc/init.d/mwan3 enable
/etc/init.d/mwan3 restart
```

## 6. 验证

```sh
# 拨号是否成功（看 "up": true 与 ipv4-address）
ifstatus wan
ifstatus wan2

# mwan3 总览：两接口应 online，policy balanced 下两成员 active
mwan3 status
mwan3 interfaces
mwan3 policies

# 策略路由表（mwan3 为每个 WAN 建独立路由表）
ip rule show
ip route show table 1
ip route show table 2

# 分别从两条线路出去，应看到不同的公网 IP
traceroute -i pppoe-wan 223.5.5.5
traceroute -i pppoe-wan2 223.5.5.5

# 日志
logread -e mwan3
```

故障切换实测：拔掉电信网线，约 15 秒（interval 5s × down 3）后
`mwan3 status` 中 wan 变 offline，流量全部走移动；插回后约 15 秒恢复。
移动侧同理。

## 7. 常用调整

切换默认策略（负载均衡 ↔ 主备）：

```sh
uci set mwan3.default_rule.use_policy='failover'   # 或 balanced
uci commit mwan3
/etc/init.d/mwan3 restart
```

按目的网段分流（示例：某网段固定走移动，规则自上而下匹配）：

```sh
uci set mwan3.to_mobile=rule
uci set mwan3.to_mobile.dest_ip='203.0.113.0/24'   # 换成实际网段
uci set mwan3.to_mobile.use_policy='mobile_only'
uci commit mwan3
/etc/init.d/mwan3 restart
```

> 规则顺序即匹配顺序，`default_rule` 必须保持在最后。LuCI 里可拖动排序。

临时停用 mwan3（恢复普通路由，电信优先，因为 metric 10<20）：

```sh
/etc/init.d/mwan3 stop
```

## 8. LuCI 网页管理

浏览器打开 `http://192.168.199.1` → **网络 → 负载均衡（mwan3）**：
接口/成员/策略/规则均可图形化编辑，状态页实时显示各线路在线情况与流量分担。
上文 UCI 配置与页面完全等价，改完点“保存并应用”即可。

## 9. 注意事项

- **IPv6 不纳入 mwan3**（支持有限）。两 WAN 的 ipv6=auto 可正常获取地址，
  但 IPv6 流量不做负载均衡；如需纯 IPv4 环境可 `uci set network.wan.ipv6='0'`
  （wan2 同理）后重启网络。
- **负载均衡与 Open-Box 都会写 ip rule**。建议先按本文验证 MWAN 正常，
  再安装 Open-Box；装完执行 `ip rule show` 核对优先级，Open-Box 面板
  “路由诊断”也会提示冲突规则。两者叠加的完整验证需在实机进行。
- 个别运营商绑定光猫 MAC 或限制并发会话：若某条拨不上，检查账号是否
  允许路由模式拨号（必要时让运营商解绑）。
- 两条宽带同时在线时，入站端口映射（UPnP/手动）只在对应 WAN 生效，
  对外服务建议固定走某一条（用 mobile_only/telecom_only 规则）。
- 本文配置在保留配置升级（sysupgrade -c）后仍在；全新刷机需重新执行。