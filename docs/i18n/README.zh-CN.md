# Sleeper

[English](../../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [Português](README.pt-BR.md) · [Español](README.es.md) · [Deutsch](README.de.md)

![Sleeper 浏览器控制工具](../../assets/repository-hero.png)

<p align="center">
  <a href="../../docs/agent-skill.md#mcp"><img alt="MCP" src="https://img.shields.io/badge/MCP-supported-8B5CF6?style=flat-square&amp;labelColor=000000&amp;logo=modelcontextprotocol&amp;logoColor=white"></a>
  <a href="https://skills.sh/shy-tangerine/Sleeper"><img alt="skills.sh" src="https://img.shields.io/badge/skills.sh-install-06B6D4?style=flat-square&amp;labelColor=000000"></a>
  <a href="../../plugins/codex/sleeper/skills/sleeper/SKILL.md"><img alt="Agent skill" src="https://img.shields.io/badge/agent_skill-included-84CC16?style=flat-square&amp;labelColor=000000"></a>
  <br>
  <a href="https://github.com/shy-tangerine/Sleeper/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/shy-tangerine/Sleeper?style=flat-square&amp;labelColor=000000&amp;color=FACC15&amp;logo=github&amp;logoColor=white"></a>
  <a href="https://github.com/shy-tangerine/Sleeper/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/shy-tangerine/Sleeper/total?style=flat-square&amp;labelColor=000000&amp;color=38BDF8"></a>
  <a href="../../LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-A78BFA?style=flat-square&amp;labelColor=000000"></a>
  <a href="https://github.com/sponsors/shy-tangerine"><img alt="Sponsor" src="https://img.shields.io/badge/Sponsor-%E2%99%A5-F472B6?style=flat-square&amp;labelColor=000000&amp;logo=githubsponsors&amp;logoColor=white"></a>
</p>

让你的 Agent 操作你在桌面或 Android 手机上使用的浏览器。通过 Sleeper 的 CLI 或 MCP，它可以浏览网站、读取页面、填写表单、截图并提取结构化数据，无需将会话凭据复制到 Agent 配置中。

[安装](#安装) · [功能](#功能) · [命令](../commands.md) · [Agent 设置](../agent-skill.md) · [隐私](../../PRIVACY.md) · [安全](../../SECURITY.md) · [基准测试](#基准测试) · [贡献](#贡献)

## 安装

请先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后在受支持的桌面平台 **Linux 或 macOS** 的 checkout 中运行：

```bash
./install.sh
```

在 Windows 上仅提供尽力支持，不属于发布时支持的平台；请在 PowerShell 中运行：

```powershell
py scripts/install.py
```

选择 **Everything** 或 **Customize**（全部安装或自定义），按需安装 MCP、原生 Agent 插件和独立技能。安装程序会启动 daemon、安装 CLI，将 Chromium 扩展保存在固定文件夹中，并将浏览器安装包复制到 Downloads。

Firefox for Android 通过 Tailscale Serve 连接（**测试版**）。运行 `sleeper mobile setup`，然后在 Firefox 中打开二维码；请参阅 [Android 设置指南](../android.md)。daemon 始终只绑定到 loopback。

### Codex 和 Claude Code

手动设置时，请先安装 Sleeper 运行时，然后在仓库根目录运行对应命令。

**Codex**

```bash
codex plugin marketplace add .
codex plugin add sleeper --marketplace sleeper-local
```

**Claude Code**

```bash
claude plugin marketplace add . --scope user
claude plugin install sleeper@sleeper --scope user
```

<details>
<summary>公开发布后安装 Agent 插件</summary>

```bash
# Codex
codex plugin marketplace add https://github.com/shy-tangerine/Sleeper.git
codex plugin add sleeper --marketplace sleeper-local

# Claude Code
claude plugin marketplace add https://github.com/shy-tangerine/Sleeper.git --scope user
claude plugin install sleeper@sleeper --scope user
```

</details>

安装后请重启 Agent，使其加载随附的 skill 和 MCP 服务器。[Agent 设置指南](../agent-skill.md#native-plugins)介绍了从公开 GitHub 安装、验证、更新和移除的方法。

| 浏览器 | 完成安装 |
|---|---|
| Chromium | 打开扩展页面，启用 **Developer mode**，选择 **Load unpacked**，然后选择安装程序打印的文件夹。 |
| Firefox | 通过 **Add-ons → Install Add-on From File** 安装已签名的 `sleeper-firefox.xpi` 发布资源。已签名的发布版本正在等待 Mozilla 签名凭据。 |

浏览器权限只需批准一次。[安装、更新和卸载](../installation.md)。

希望手动设置客户端？请使用已验证的 [Codex 和 Claude Code 插件命令](../agent-skill.md#native-plugins)。

<details>
<summary>公开发布后从 GitHub 安装</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/shy-tangerine/Sleeper/main/install.sh | bash
```

</details>


检查打开的标签页和当前页面：

```bash
sleeper tabs
sleeper snapshot
sleeper type --role textbox --name Search 'your query' --clear
sleeper press Enter
```

随附的 [agent skill](../../plugins/codex/sleeper/skills/sleeper/SKILL.md) 介绍会话选择、操作验证和连接恢复。Agent 可以直接使用 MCP 工具；[命令指南](../commands.md) 介绍标签页目标、提取、配方和 API 调用。

| 等待 | 工作中 |
|:---:|:---:|
| <img src="../../extension/icon.svg" width="48" alt="闭眼的 Sleeper"> | <img src="../../extension/icon-active.svg" width="48" alt="睁眼的 Sleeper"> |

## 功能

- 📱 **Firefox for Android（测试版）：** 通过与桌面 daemon 的私有 Tailscale Serve 连接在 Android 上运行 Sleeper。无需 Caddy、路由器端口或公共 listener。
- 🖥️ **Firefox + Chromium desktop:** 通过扩展控制现有浏览器会话中的页面。支持 Linux 和 macOS；Windows 为尽力支持。
- 🗂️ **配置文件和标签页：** 每个浏览器安装都有自己的持久 ID。Agent 可发现已连接的浏览器并定位目标标签页。
- 🎯 **元素定位：** 通过 CSS 选择器、无障碍角色和名称，或 `snapshot` 返回的引用查找控件。
- 📝 **页面交互：** 填写输入框、按键、点击控件，并在下一步前等待选择器或文本。
- 📋 **结构化提取：** 读取单个元素、收集匹配元素或提取 JSON 映射。将可重复的工作保存为配方和模式。
- 📸 **截图：** 捕获视口或整页，可选标注。PNG 输出有大小限制；[捕获选项](../commands.md#use-the-cli) 对此作出说明。
- 🌐 **网络和 API：** 检查捕获的请求，并调用允许的 HTTPS API。凭据保留在浏览器中，并绑定到其源主机。
- 🔒 **密钥遮蔽：** 结构化结果在到达 CLI 或 MCP 客户端前会尽力脱敏。截图仍可能包含私密信息。
- 🔌 **CLI 和 MCP：** 通过本地 daemon 运行 shell 命令或调用 MCP 工具。
- 📖 **随附 skill：** 向 agent 提供会话选择、操作验证和连接恢复的说明。



## 基准测试

每个接口在一台机器上验证运行五次。每个序列都会导航、读取标题、输入、点击、等待文本并读取结果。

测试环境为 Linux，浏览器为 **Helium 0.17.0.1（Chromium 153.0.8010.36）**。所有接口均使用同一浏览器版本和全新配置文件。

<table>
  <tr>
    <td align="center" valign="top" width="33%"><h3>76.7%</h3>序列耗时降低<br><sub>Sleeper CLI 对比 OpenCLI</sub></td>
    <td align="center" valign="top" width="33%"><h3>86.1%</h3>序列耗时降低<br><sub>Sleeper MCP 对比 Playwright MCP</sub></td>
    <td align="center" valign="top" width="33%"><h3>98.6%</h3>协议文本 token 减少<br><sub>Sleeper CLI 对比 OpenCLI</sub></td>
  </tr>
</table>

百分比根据表中四舍五入后的中位数计算。

| 接口 | 序列中位数 | 浏览器 RSS 中位数 | 任务文本 token | 协议文本 token |
|---|---:|---:|---:|---:|
| Sleeper CLI | 934 ms | 1,139 MiB | 441 | 409 (HTTP JSON) |
| Sleeper MCP | 227 ms | 1,152 MiB | 502 | 695 (JSON-RPC) |
| OpenCLI | 4,011 ms | 1,218 MiB | 364 | 29,152 (HTTP JSON) |
| Playwright MCP | 1,635 ms | 1,027 MiB | 536 | 734 (JSON-RPC) |
| Direct CDP | 291 ms | 1,038 MiB | 不适用 | 956 (CDP) |

任务文本 token 使用 `o200k_base` 估算 agent 可见的输入和输出。协议 token 统计内部 HTTP JSON、JSON-RPC 或 CDP 流量；它们不是模型用量。Direct CDP 没有面向 agent 的任务文本接口。

浏览器 RSS 汇总浏览器进程内存，可能会重复计算共享页面，并且不包括 daemon。计时和协议捕获使用独立运行。这些结果来自单台机器、单一浏览器版本和单次运行日期（2026-09-11），测量的是确定性的浏览器原语，而非 agent 任务完成度或总体速度；请参阅[基准方法注意事项](../benchmarks/matched-browser-interface.md#canonical-caveat-block)——引用这些数字时必须附上该说明。[原始样本、方法、发现成本和功能比较](../benchmarks/matched-browser-interface.md)。

<details>
<summary>Linux 浏览器兼容性检查</summary>

| 浏览器 | 版本 | 结果 |
|---|---|---|
| Firefox | 155.0.1 | 通过 |
| Chrome | 151.0.7922.47 | 通过 |
| Zen | 1.22b | 通过 |
| Helium | 0.17.0.1 (Chromium 153.0.8010.36) | 通过 |

Chrome 测试使用了面向自动化的 Google Chrome for Testing，具体版本见上表。

</details>

## 贡献

[构建和测试](../installation.md#development) · [变更日志](../../CHANGELOG.md) · [第三方声明](../../THIRD_PARTY_NOTICES.md) · [隐私](../../PRIVACY.md) · [安全](../../SECURITY.md) · [MIT 许可证](../../LICENSE) · [赞助](../SPONSORS.md)

<details>
<summary>仓库布局</summary>

| 目录 | 内容 |
|---|---|
| `extension/` | 浏览器清单、页面处理程序、弹窗、图标 |
| `daemon/` | HTTP/WebSocket 中继和 MCP 服务器 |
| `cli/` | CLI、配方、适配器支持 |
| `plugins/codex/sleeper/skills/` | Agent 说明 |
| `examples/` | 配方和提取模式 |
| `test/` | 行为、传输和软件包检查 |

</details>

## Star 历史

[在公开仓库发布后查看 star-history 图表](https://www.star-history.com/#shy-tangerine/Sleeper&Date)。

## Python 软件包构建（PyPI）

浏览器扩展发布流程与 Python 打包分开。Python 软件包元数据位于 `pyproject.toml`；`uv.lock` 管理开发环境。运行 `uv lock --check`、`uv sync --locked` 和 `uv build`，在 `dist/` 中生成 sdist 和 wheel。只有所有者批准发布并配置 PyPI 凭据或可信发布后，`uv publish` 才能上传这些构件。构建不代表已获发布授权。
