# OpenWrt Parental Control for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://github.com/hacs/default)
[![GitHub Release](https://img.shields.io/github/v/release/bingooo/hass-openwrt-parental-control?style=flat-square)](https://github.com/bingooo/hass-openwrt-parental-control/releases)
[![License](https://img.shields.io/github/license/bingooo/hass-openwrt-parental-control?style=flat-square)](LICENSE)

A lightweight and elegant Home Assistant integration for OpenWrt parental controls via native ubus JSON-RPC.

> **This fork (`tvctl` edition)**: blocking is delegated to a router-side `tvctl` script (dual-write: fw4 `no_tv_rule` REJECT + OpenClash `lan_ac_black_macs`). The integration pushes the full MAC list to `tvctl sync` over the existing ubus session — see [Router setup](#router-setup-tvctl).

[English](#english) | [简体中文](#简体中文)

---

## English

### Overview

**OpenWrt Parental Control** allows you to easily manage internet access for family members and devices on your OpenWrt router directly from Home Assistant. 

### Key Features

* **⚡ Native ubus + tvctl**: Communicates through OpenWrt's asynchronous `ubus JSON-RPC` API. Blocking is enforced by the small `tvctl` script on the router — no extra daemons, and OpenClash-bypassing traffic is covered too (unlike a plain firewall rule).
* **⏸️ Instant Internet Pause**: Dedicated one-click switch per member profile to instantly pause or resume internet access.
* **⏰ Bedtime & Curfew Schedule**: Cross-midnight scheduling (e.g. 22:00 to 06:30) with Weekdays and Everyday presets, plus adjustable start and end times.
* **📱 Clean HA Integration**: Full UI configuration flow, intuitive device cards, and real-time blocking status reporting.

### Installation

#### Via HACS (Recommended)

1. In Home Assistant, open **HACS -> Integrations**.
2. Click the top-right menu (three dots) -> **Custom repositories**.
3. Add Repository: `https://github.com/bingooo/hass-openwrt-parental-control`, Category: **Integration**.
4. Search for **OpenWrt Parental Control**, download and restart Home Assistant.

#### Manual Installation

Copy `custom_components/openwrt_parental_control` to your Home Assistant `config/custom_components/` directory and restart Home Assistant.

### Quick Start

1. Go to **Settings -> Devices & Services -> Add Integration** and search for **OpenWrt Parental Control**.
2. Enter your OpenWrt router's IP, port, username, and password.
3. Click **Configure** on the integration entry to create member profiles and assign devices.

### Router setup (tvctl)

This fork enforces blocks through a router-side `tvctl` script, which must be installed once on the OpenWrt router. It dual-writes an fw4 `REJECT` rule (`no_tv_rule`) and the OpenClash MAC blacklist (`lan_ac_black_macs`), so devices cannot bypass the block via the proxy.

```sh
# 1. Install the tvctl script (from this repo's router/ directory)
scp router/tvctl root@<router-ip>:/usr/bin/tvctl
ssh root@<router-ip> 'chmod 755 /usr/bin/tvctl'

# 2. Grant rpcd permission so HA can invoke tvctl via ubus `file exec`
scp router/30-openwrt-parental-control.json \
    root@<router-ip>:/usr/share/rpcd/acl.d/30-openwrt-parental-control.json
ssh root@<router-ip> '/etc/init.d/rpcd restart'

# 3. Verify
ssh root@<router-ip> 'tvctl list'
```

The script requires an fw4 rule section named `no_tv_rule` (a `config rule 'no_tv_rule'` with `src='*'`, `dest='*'`, `target='REJECT'`, `proto='all'`). It will still work if the section does not exist yet — `tvctl` creates the MAC entries, but for the rule to actually block, create the section once in `/etc/config/firewall`.

`tvctl` commands: `list`, `list-json`, `status`, `add <MAC|name>`, `del <MAC|name>`, `sync [MAC...]` (set the full blocklist — used by HA), `off`, `on`.

---

## 简体中文

### 简介

**OpenWrt Parental Control** 是一款轻量、优雅的 Home Assistant 集成插件，用于直接在 Home Assistant 中便捷管理家庭 OpenWrt 路由器的上网控制规则。

### 核心特性

* **⚡ 原生 ubus + tvctl**：通过 OpenWrt 原生异步 `ubus JSON-RPC` 接口通信，封禁由路由器上的轻量 `tvctl` 脚本执行——无需常驻后台服务，且能封堵经 OpenClash 代理绕行的流量（纯防火墙规则做不到）。
* **⏸️ 随时一键暂停上网**：为每个家庭成员提供独立的手动暂停开关，轻按一次即可即时封锁或恢复名下所有设备。
* **⏰ 灵活时段计划控制**：支持跨午夜定时断网（如每晚 22:00 至次日 06:30），提供工作日/每日预设及自由调节的起止时间。
* **📱 原生 UI 体验**：全图形化配置向导（Config Flow），自动生成成员设备实体卡片，状态实时同步汇报。

### 安装方式

#### 通过 HACS 安装（推荐）

1. 在 Home Assistant 中打开 **HACS -> 集成**。
2. 点击右上角菜单（三个点） -> **自定义存储库**。
3. 添加存储库地址：`https://github.com/bingooo/hass-openwrt-parental-control`，类别选择 **集成**。
4. 搜索 **OpenWrt Parental Control** 下载并重启 Home Assistant。

#### 手动安装

将 `custom_components/openwrt_parental_control` 目录复制到 Home Assistant 配置目录的 `custom_components/` 下，并重启 Home Assistant。

### 快速开始

1. 前往 **设置 -> 设备与服务 -> 添加集成**，搜索 **OpenWrt Parental Control**。
2. 输入 OpenWrt 路由器的 IP 地址、端口、用户名及密码完成连接。
3. 点击集成卡片上的 **配置** 按钮，添加成员档案并分配绑定的受控设备。

### 路由器端部署（tvctl）

本分支通过路由器上的 `tvctl` 脚本执行封禁，需在 OpenWrt 上一次性安装。它双写 fw4 的 `REJECT` 规则（`no_tv_rule`）与 OpenClash 的 MAC 黑名单（`lan_ac_black_macs`），避免设备经代理绕过封禁。

```sh
# 1. 安装 tvctl 脚本（来自本仓库 router/ 目录）
scp router/tvctl root@<路由器IP>:/usr/bin/tvctl
ssh root@<路由器IP> 'chmod 755 /usr/bin/tvctl'

# 2. 授权 rpcd，使 HA 可通过 ubus `file exec` 调用 tvctl
scp router/30-openwrt-parental-control.json \
    root@<路由器IP>:/usr/share/rpcd/acl.d/30-openwrt-parental-control.json
ssh root@<路由器IP> '/etc/init.d/rpcd restart'

# 3. 验证
ssh root@<路由器IP> 'tvctl list'
```

脚本依赖 `/etc/config/firewall` 中名为 `no_tv_rule` 的规则段（`config rule 'no_tv_rule'`，含 `src='*'`、`dest='*'`、`target='REJECT'`、`proto='all'`）。若该段不存在，tvctl 仍能写入 MAC 条目，但要真正生效需先建好该规则段。

`tvctl` 命令：`list`、`list-json`、`status`、`add <MAC|设备名>`、`del <MAC|设备名>`、`sync [MAC...]`（一次性设置完整名单，HA 集成使用）、`off`、`on`。

---

### License

[GNU General Public License v3.0](LICENSE)
