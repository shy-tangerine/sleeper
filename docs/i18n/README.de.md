# Sleeper

[English](../../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [Português](README.pt-BR.md) · [Español](README.es.md) · [Deutsch](README.de.md)

![Sleeper-Browsersteuerung für Agenten](../../assets/repository-hero.png)

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

Lass deinen Agenten deinen Browser auf dem Desktop oder Android-Telefon steuern. Mit Sleeper kann er über CLI oder MCP Websites aufrufen, Seiten lesen, Formulare ausfüllen, Screenshots erstellen und strukturierte Daten extrahieren, ohne Sitzungsdaten in die Agent-Konfiguration zu kopieren.

[Installation](#installation) · [Funktionen](#funktionen) · [Kommandos](../commands.md) · [Agent-Einrichtung](../agent-skill.md) · [Datenschutz](../../PRIVACY.md) · [Sicherheit](../../SECURITY.md) · [Benchmarks](#benchmarks) · [Mitwirken](#mitwirken)

## Installation

Installiere zuerst [uv](https://docs.astral.sh/uv/getting-started/installation/) und führe den Installer aus einem Checkout unter **Linux oder macOS** (den unterstützten Desktop-Plattformen) aus:

```bash
./install.sh
```

Windows funktioniert nach Best-Effort und ist keine zum Start unterstützte Plattform; führe in PowerShell aus:

```powershell
py scripts/install.py
```

Wähle **Everything** oder **Customize** (Alles bzw. Anpassen), um MCP, native Agent-Plugins und eigenständige Anleitungen auszuwählen. Der Installer startet den Daemon, installiert die CLI, legt die Chromium-Erweiterung dauerhaft ab und kopiert die Browser-Pakete nach Downloads.

Firefox für Android verbindet sich über Tailscale Serve (**Beta**). Führe `sleeper mobile setup` aus und öffne anschließend den QR-Code in Firefox; siehe den [Android-Einrichtungsleitfaden](../android.md). Der Daemon bleibt ausschließlich an Loopback gebunden.

### Codex und Claude Code

Installiere bei der manuellen Einrichtung zuerst die Sleeper-Laufzeit und führe anschließend die passenden Befehle im Stammverzeichnis des Repositorys aus.

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
<summary>Agent-Plugin nach der öffentlichen Veröffentlichung installieren</summary>

```bash
# Codex
codex plugin marketplace add https://github.com/shy-tangerine/Sleeper.git
codex plugin add sleeper --marketplace sleeper-local

# Claude Code
claude plugin marketplace add https://github.com/shy-tangerine/Sleeper.git --scope user
claude plugin install sleeper@sleeper --scope user
```

</details>

Starte den Agenten nach der Installation neu, damit er den enthaltenen Skill und MCP-Server lädt. Der [Einrichtungsleitfaden für Agenten](../agent-skill.md#native-plugins) beschreibt öffentliche GitHub-Installation, Prüfung, Updates und Entfernung.

| Browser | Installation abschließen |
|---|---|
| Chromium | Öffne die Erweiterungsseite, aktiviere den **Entwicklermodus**, wähle **Entpackte Erweiterung laden** und wähle den vom Installationsprogramm ausgegebenen Ordner. |
| Firefox | Installiere das signierte Release-Asset `sleeper-firefox.xpi` über **Add-ons → Add-on aus Datei installieren**. Signierte Releases stehen erst nach Einrichtung der Mozilla-Signierungszugangsdaten bereit. |

Die Browserberechtigung muss einmal bestätigt werden. Siehe [Installation, Updates und Entfernung](../installation.md).

Möchtest du den Client manuell einrichten? Verwende die geprüften [Plugin-Befehle für Codex und Claude Code](../agent-skill.md#native-plugins).

<details>
<summary>Installation aus GitHub nach dem öffentlichen Start</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/shy-tangerine/Sleeper/main/install.sh | bash
```

</details>


Offene Tabs und die aktuelle Seite untersuchen:

```bash
sleeper tabs
sleeper snapshot
sleeper type --role textbox --name Search 'your query' --clear
sleeper press Enter
```

Der enthaltene [Agent-Skill](../../plugins/codex/sleeper/skills/sleeper/SKILL.md) behandelt Sitzungswahl, Aktionsprüfung und Wiederherstellung der Verbindung. Agenten können MCP-Werkzeuge direkt verwenden; der [Kommando-Leitfaden](../commands.md) erklärt Tab-Ziele, Extraktion, Rezepte und API-Aufrufe.

| Wartend | Aktiv |
|:---:|:---:|
| <img src="../../extension/icon.svg" width="48" alt="Sleeper mit geschlossenen Augen"> | <img src="../../extension/icon-active.svg" width="48" alt="Sleeper mit offenen Augen"> |

## Funktionen

- 📱 **Firefox for Android (Beta):** Nutze Sleeper auf Android über eine private Tailscale-Serve-Verbindung zu deinem Desktop-Daemon. Caddy, ein Router-Port und ein öffentlicher Listener sind nicht erforderlich.
- 🖥️ **Firefox + Chromium desktop:** Steuere Seiten in einer bestehenden Browser-Sitzung über die Erweiterung. Linux und macOS werden unterstützt; Windows ist Best-Effort.
- 🗂️ **Profile und Tabs:** Jede Browserinstallation hat eine eigene dauerhafte Kennung. Agenten erkennen verbundene Browser und wählen den beabsichtigten Tab.
- 🎯 **Elementauswahl:** Finde Steuerelemente über CSS-Selektoren, zugängliche Rolle und Namen oder die von `snapshot` zurückgegebene Referenz.
- 📝 **Seiteninteraktion:** Fülle Eingaben aus, drücke Tasten, klicke Steuerelemente und warte vor der nächsten Aktion auf Selektoren oder Text.
- 📋 **Strukturierte Extraktion:** Lies ein Element, sammle passende Elemente und extrahiere JSON-Zuordnungen. Speichere wiederholbare Arbeit als Rezepte und Schemas.
- 📸 **Screenshots:** Erfasse den sichtbaren Bereich oder die ganze Seite, optional mit Anmerkungen. Für die PNG-Ausgabe gilt eine Größenbegrenzung; die [Aufnahmeoptionen](../commands.md#use-the-cli) erklären sie.
- 🌐 **Netzwerk und APIs:** Prüfe aufgezeichnete Anfragen und rufe erlaubte HTTPS-APIs auf. Zugangsdaten bleiben im Browser und an ihren Ursprungshost gebunden.
- 🔒 **Maskierung von Geheimnissen:** Strukturierte Ergebnisse werden in CLI und MCP nach bestem Bemühen geschwärzt. Screenshots können weiterhin private Informationen enthalten.
- 🔌 **CLI und MCP:** Führe Shell-Kommandos aus oder rufe MCP-Werkzeuge über den lokalen Daemon auf.
- 📖 **Enthaltener Skill:** Gibt Agenten Anweisungen für Sitzungswahl, Aktionsprüfung und Verbindungswiederherstellung.



## Benchmarks

Fünf verifizierte Durchläufe pro Schnittstelle auf einem Rechner. Jede Sequenz navigiert, liest eine Überschrift, tippt, klickt, wartet auf Text und liest das Ergebnis.

Getestet unter Linux mit **Helium 0.17.0.1 (Chromium 153.0.8010.36)**. Alle Schnittstellen verwendeten denselben Browser-Build und ein neues Profil.

<table>
  <tr>
    <td align="center" valign="top" width="33%"><h3>76.7%</h3>weniger Sequenzzeit<br><sub>Sleeper CLI vs. OpenCLI</sub></td>
    <td align="center" valign="top" width="33%"><h3>86.1%</h3>weniger Sequenzzeit<br><sub>Sleeper MCP vs. Playwright MCP</sub></td>
    <td align="center" valign="top" width="33%"><h3>98.6%</h3>weniger Protokolltext-Tokens<br><sub>Sleeper CLI vs. OpenCLI</sub></td>
  </tr>
</table>

Die Prozentwerte basieren auf den gerundeten Medianen der Tabelle.

| Schnittstelle | Median der Sequenz | Median Browser-RSS | Task-Text-Tokens | Protokoll-Text-Tokens |
|---|---:|---:|---:|---:|
| Sleeper CLI | 934 ms | 1,139 MiB | 441 | 409 (HTTP JSON) |
| Sleeper MCP | 227 ms | 1,152 MiB | 502 | 695 (JSON-RPC) |
| OpenCLI | 4,011 ms | 1,218 MiB | 364 | 29,152 (HTTP JSON) |
| Playwright MCP | 1,635 ms | 1,027 MiB | 536 | 734 (JSON-RPC) |
| Direct CDP | 291 ms | 1,038 MiB | Nicht anwendbar | 956 (CDP) |

Task-Text-Tokens schätzen Agenten-Eingaben und -Ausgaben mit `o200k_base`. Protokoll-Tokens zählen internen HTTP-JSON-, JSON-RPC- oder CDP-Verkehr; sie sind keine Modellnutzung. Direct CDP hat keine Agenten-Schnittstelle für Task-Text.

Browser-RSS summiert den Speicher der Browserprozesse, kann gemeinsam genutzte Seiten doppelt zählen und schließt Daemons aus. Zeit- und Protokollaufzeichnungen stammen aus getrennten Durchläufen. Diese Ergebnisse stammen von einer einzelnen Maschine, einem einzelnen Browser-Build und einem einzelnen Ausführungsdatum (2026-09-11) und messen deterministische Browser-Primitiven, nicht die Erledigung von Agentenaufgaben oder allgemeine Geschwindigkeit; siehe die [kanonischen Methodik-Hinweise](../benchmarks/matched-browser-interface.md#canonical-caveat-block), die diese Zahlen überall dort begleiten müssen, wo sie zitiert werden. [Rohdaten, Methodik, Erkennungskosten und Funktionsvergleich](../benchmarks/matched-browser-interface.md).

<details>
<summary>Browser-Prüfungen unter Linux</summary>

| Browser | Version | Ergebnis |
|---|---|---|
| Firefox | 155.0.1 | Bestanden |
| Chrome | 151.0.7922.47 | Bestanden |
| Zen | 1.22b | Bestanden |
| Helium | 0.17.0.1 (Chromium 153.0.8010.36) | Bestanden |

Der Chrome-Test verwendete Google Chrome for Testing, die Chrome-Distribution für Automatisierung. Die genaue Version steht in der Tabelle.

</details>

## Mitwirken

[Entwickeln und testen](../installation.md#development) · [Änderungsprotokoll](../../CHANGELOG.md) · [Hinweise zu Drittanbietern](../../THIRD_PARTY_NOTICES.md) · [Datenschutz](../../PRIVACY.md) · [Sicherheit](../../SECURITY.md) · [MIT-Lizenz](../../LICENSE) · [Sponsoring](../SPONSORS.md)

<details>
<summary>Repository-Struktur</summary>

| Verzeichnis | Inhalt |
|---|---|
| `extension/` | Browser-Manifeste, Seiten-Handler, Popup, Symbole |
| `daemon/` | HTTP/WebSocket-Relay und MCP-Server |
| `cli/` | CLI, Rezepte, Adapter-Unterstützung |
| `plugins/codex/sleeper/skills/` | Agenten-Anweisungen |
| `examples/` | Rezepte und Extraktionsschemas |
| `test/` | Verhaltens-, Transport- und Paketprüfungen |

</details>

## Star-Verlauf

[Star-History-Diagramm ansehen](https://www.star-history.com/#shy-tangerine/Sleeper&Date), sobald das öffentliche Repository startet.

## Python-Paket bauen (PyPI)

Der Veröffentlichungsprozess der Browser-Erweiterung ist vom Python-Paketieren getrennt. Die Metadaten des Python-Pakets stehen in `pyproject.toml`; `uv.lock` verwaltet die Entwicklungsumgebung. Führe `uv lock --check`, `uv sync --locked` und `uv build` aus, um ein sdist und ein wheel in `dist/` zu erzeugen. Erst nach der Freigabe durch den Eigentümer und der Einrichtung von PyPI-Anmeldedaten oder Trusted Publishing darf `uv publish` diese Artefakte hochladen. Ein Build ist keine Veröffentlichungserlaubnis.
