# Sleeper

[English](../../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [Português](README.pt-BR.md) · [Español](README.es.md) · [Deutsch](README.de.md)

![Sleeper ブラウザー操作エージェント](../../assets/repository-hero.png)

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

デスクトップや Android スマートフォンで普段使っているブラウザーを、エージェントに操作させましょう。Sleeper は CLI または MCP 経由で Web サイトの移動、ページの読み取り、フォーム入力、スクリーンショット取得、構造化データの抽出を行います。セッション資格情報をエージェント設定へコピーする必要はありません。

[インストール](#インストール) · [機能](#機能) · [コマンド](../commands.md) · [Agent の設定](../agent-skill.md) · [プライバシー](../../PRIVACY.md) · [セキュリティ](../../SECURITY.md) · [ベンチマーク](#ベンチマーク) · [コントリビュート](#コントリビュート)

## インストール

まず [uv](https://docs.astral.sh/uv/getting-started/installation/) をインストールし、サポート対象のデスクトッププラットフォームである **Linux または macOS** の checkout から実行します。

```bash
./install.sh
```

Windows はベストエフォートであり、リリース時点でサポート対象のプラットフォームではありません。PowerShell で実行します。

```powershell
py scripts/install.py
```

**Everything** または **Customize**（すべて／カスタマイズ）を選び、MCP、ネイティブプラグイン、単独のスキルを選択できます。インストーラーは daemon を起動し、CLI をインストールし、Chromium 拡張機能を永続フォルダーに配置して、ブラウザーパッケージを Downloads にコピーします。

Android 版 Firefox は Tailscale Serve 経由で接続します（**ベータ**）。`sleeper mobile setup` を実行してから Firefox で QR コードを開いてください。[Android 設定ガイド](../android.md)も参照してください。daemon は loopback にのみバインドされたままです。

### Codex と Claude Code

手動設定では、まず Sleeper ランタイムをインストールし、リポジトリのルートで該当するコマンドを実行します。

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
<summary>公開後に Agent プラグインをインストールする</summary>

```bash
# Codex
codex plugin marketplace add https://github.com/shy-tangerine/Sleeper.git
codex plugin add sleeper --marketplace sleeper-local

# Claude Code
claude plugin marketplace add https://github.com/shy-tangerine/Sleeper.git --scope user
claude plugin install sleeper@sleeper --scope user
```

</details>

インストール後にエージェントを再起動すると、同梱の skill と MCP サーバーが読み込まれます。[エージェント設定](../agent-skill.md#native-plugins)では、公開 GitHub からのインストール、検証、更新、削除を説明しています。

| ブラウザー | インストールを完了する手順 |
|---|---|
| Chromium | 拡張機能ページを開き、**Developer mode** を有効にして **Load unpacked** を選び、インストーラーが表示したフォルダーを選択します。 |
| Firefox | **Add-ons → Install Add-on From File** から署名済みの `sleeper-firefox.xpi` リリースアセットをインストールします。署名済みリリースは Mozilla の署名資格情報を待っています。 |

ブラウザー権限の承認は一度だけ必要です。[インストール、更新、削除](../installation.md)。

クライアントを手動で設定する場合は、検証済みの [Codex および Claude Code プラグインコマンド](../agent-skill.md#native-plugins)を使用してください。

<details>
<summary>公開後に GitHub からインストールする</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/shy-tangerine/Sleeper/main/install.sh | bash
```

</details>


開いているタブと現在のページを確認します。

```bash
sleeper tabs
sleeper snapshot
sleeper type --role textbox --name Search 'your query' --clear
sleeper press Enter
```

付属の [agent skill](../../plugins/codex/sleeper/skills/sleeper/SKILL.md) は、セッション選択、操作の検証、接続の復旧を扱います。Agent は MCP ツールを直接使用できます。[コマンドガイド](../commands.md) はタブの対象指定、抽出、recipes、API 呼び出しを扱います。

| 待機中 | 実行中 |
|:---:|:---:|
| <img src="../../extension/icon.svg" width="48" alt="目を閉じた Sleeper"> | <img src="../../extension/icon-active.svg" width="48" alt="目を開けた Sleeper"> |

## 機能

- 📱 **Firefox for Android（ベータ）:** デスクトップ daemon へのプライベートな Tailscale Serve 接続を通じて Android 上で Sleeper を実行します。Caddy、ルーターのポート、公開 listener は不要です。
- 🖥️ **Firefox + Chromium desktop:** 拡張機能を通じて既存のブラウザーセッション内のページを操作します。Linux と macOS がサポート対象で、Windows はベストエフォートです。
- 🗂️ **プロファイルとタブ：** ブラウザーの各インストールには固有の永続 ID があります。Agent は接続済みブラウザーを見つけ、意図したタブを対象にできます。
- 🎯 **要素の指定：** CSS セレクター、アクセシブルな role と name、または `snapshot` が返す参照でコントロールを見つけます。
- 📝 **ページ操作：** 入力欄への記入、キー入力、コントロールのクリックを行い、次の操作の前にセレクターまたはテキストを待ちます。
- 📋 **構造化抽出：** 1 つの要素を読み、合致する要素を収集し、JSON マップを抽出します。反復作業は recipes と schemas として保存できます。
- 📸 **スクリーンショット：** ビューポートまたはページ全体を撮影し、必要に応じて注釈を追加します。PNG 出力にはサイズ制限があります。[撮影オプション](../commands.md#use-the-cli) を参照してください。
- 🌐 **ネットワークと API：** 取得したリクエストを調べ、許可された HTTPS API を呼び出します。認証情報はブラウザーに保持され、送信元ホストに結び付けられます。
- 🔒 **シークレットのマスキング：** 構造化結果は CLI または MCP クライアントに届く前に可能な限り秘匿化されます。スクリーンショットには依然として個人情報が含まれる場合があります。
- 🔌 **CLI と MCP：** ローカル daemon を通じてシェルコマンドを実行するか、MCP ツールを呼び出します。
- 📖 **付属 skill：** Agent にセッション選択、操作検証、接続復旧の手順を提供します。



## ベンチマーク

各インターフェースを 1 台のマシンで 5 回検証しました。各シーケンスは移動、見出しの読み取り、入力、クリック、テキストの待機、結果の読み取りを行います。

Linux 上の **Helium 0.17.0.1（Chromium 153.0.8010.36）** でテストしました。すべてのインターフェースで同じブラウザービルドと新規プロファイルを使用しています。

<table>
  <tr>
    <td align="center" valign="top" width="33%"><h3>76.7%</h3>シーケンス時間を短縮<br><sub>Sleeper CLI 比較対象： OpenCLI</sub></td>
    <td align="center" valign="top" width="33%"><h3>86.1%</h3>シーケンス時間を短縮<br><sub>Sleeper MCP 比較対象： Playwright MCP</sub></td>
    <td align="center" valign="top" width="33%"><h3>98.6%</h3>プロトコルテキストのトークン数を削減<br><sub>Sleeper CLI 比較対象： OpenCLI</sub></td>
  </tr>
</table>

割合は表の丸めた中央値から算出しています。

| インターフェース | シーケンス中央値 | ブラウザー RSS 中央値 | タスクテキストトークン | プロトコルテキストトークン |
|---|---:|---:|---:|---:|
| Sleeper CLI | 934 ms | 1,139 MiB | 441 | 409 (HTTP JSON) |
| Sleeper MCP | 227 ms | 1,152 MiB | 502 | 695 (JSON-RPC) |
| OpenCLI | 4,011 ms | 1,218 MiB | 364 | 29,152 (HTTP JSON) |
| Playwright MCP | 1,635 ms | 1,027 MiB | 536 | 734 (JSON-RPC) |
| Direct CDP | 291 ms | 1,038 MiB | 該当なし | 956 (CDP) |

タスクテキストトークンは、`o200k_base` を用いて agent が受け取る入力と出力を推定したものです。プロトコルトークンは内部の HTTP JSON、JSON-RPC、CDP トラフィックを数えたもので、モデル使用量ではありません。Direct CDP には agent 向けのタスクテキストインターフェースがありません。

ブラウザー RSS はブラウザープロセスのメモリー合計であり、共有ページを二重計上することがあり、daemon は含みません。時間とプロトコルの取得には別々の実行を使用しています。これらの結果は 1 台のマシン、1 つのブラウザービルド、1 つの実行日（2026-09-11）に基づくもので、決定論的なブラウザープリミティブを測定するものであり、agent のタスク達成度や一般的な速度ではありません。[ベンチマーク手法に関する注意書き](../benchmarks/matched-browser-interface.md#canonical-caveat-block)を参照してください。これらの数値を引用する際は、必ずこの注意書きを添えてください。[生サンプル、手法、検出コスト、機能比較](../benchmarks/matched-browser-interface.md)。

<details>
<summary>Linux でのブラウザー動作確認</summary>

| ブラウザー | バージョン | 結果 |
|---|---|---|
| Firefox | 155.0.1 | 合格 |
| Chrome | 151.0.7922.47 | 合格 |
| Zen | 1.22b | 合格 |
| Helium | 0.17.0.1 (Chromium 153.0.8010.36) | 合格 |

Chrome の確認には、自動化向けの Google Chrome for Testing を使用しました。正確なバージョンは上の表に記載しています。

</details>

## コントリビュート

[ビルドとテスト](../installation.md#development) · [変更履歴](../../CHANGELOG.md) · [第三者通知](../../THIRD_PARTY_NOTICES.md) · [プライバシー](../../PRIVACY.md) · [セキュリティ](../../SECURITY.md) · [MIT ライセンス](../../LICENSE) · [スポンサー](../SPONSORS.md)

<details>
<summary>リポジトリ構成</summary>

| ディレクトリ | 内容 |
|---|---|
| `extension/` | ブラウザーマニフェスト、ページハンドラー、ポップアップ、アイコン |
| `daemon/` | HTTP/WebSocket リレーと MCP サーバー |
| `cli/` | CLI、recipes、アダプター対応 |
| `plugins/codex/sleeper/skills/` | Agent 向けの手順 |
| `examples/` | recipes と抽出 schemas |
| `test/` | 振る舞い、通信、パッケージのチェック |

</details>

## Star 履歴

[公開リポジトリの開始後に star-history グラフを表示する](https://www.star-history.com/#shy-tangerine/Sleeper&Date)。

## Python パッケージのビルド（PyPI）

ブラウザー拡張機能のリリースフローは Python のパッケージングとは別です。Python パッケージのメタデータは `pyproject.toml` にあり、開発環境は `uv.lock` で管理します。`uv lock --check`、`uv sync --locked`、`uv build` を実行すると、`dist/` に sdist と wheel が生成されます。所有者がリリースを承認し、PyPI の認証情報または Trusted Publishing を設定した後に限り、`uv publish` でこれらの成果物をアップロードできます。ビルドはリリース承認を意味しません。
