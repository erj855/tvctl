# OpenWrt Parental Control for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://github.com/hacs/default)
[![GitHub Release](https://img.shields.io/github/v/release/bingooo/hass-openwrt-parental-control?style=flat-square)](https://github.com/bingooo/hass-openwrt-parental-control/releases)
[![License](https://img.shields.io/github/license/bingooo/hass-openwrt-parental-control?style=flat-square)](LICENSE)

A lightweight and elegant Home Assistant integration for OpenWrt parental controls via native ubus JSON-RPC.

[English](#english) | [简体中文](#简体中文)

---

## English

### Overview

**OpenWrt Parental Control** allows you to easily manage internet access for family members and devices on your OpenWrt router directly from Home Assistant. 

### Key Features

* **⚡ Native & Zero Agent**: Communicates directly through OpenWrt's asynchronous `ubus JSON-RPC` API. No extra packages, daemons, or scripts needed on your router.
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

---

## 简体中文

### 简介

**OpenWrt Parental Control** 是一款轻量、优雅的 Home Assistant 集成插件，用于直接在 Home Assistant 中便捷管理家庭 OpenWrt 路由器的上网控制规则。

### 核心特性

* **⚡ 路由器原生免客户端**：通过 OpenWrt 原生异步 `ubus JSON-RPC` 接口通信，无需在路由器上安装任何第三方后台软件、脚本或依赖。
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

---

### License

[GNU General Public License v3.0](LICENSE)
