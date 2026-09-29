# Sleeper

[English](../../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [Português](README.pt-BR.md) · [Español](README.es.md) · [Deutsch](README.de.md)

![Sleeper browser control for agents](../../assets/repository-hero.png)

<p align="center">
  <a href="../../docs/agent-skill.md#mcp"><img alt="MCP" src="https://img.shields.io/badge/MCP-supported-8B5CF6?style=flat-square&amp;labelColor=000000&amp;logo=modelcontextprotocol&amp;logoColor=white"></a>
  <a href="https://skills.sh/shy-tangerine/Sleeper"><img alt="skills.sh" src="https://img.shields.io/badge/skills.sh-install-06B6D4?style=flat-square&amp;labelColor=000000"></a>
  <a href="../../skills/sleeper/SKILL.md"><img alt="Agent skill" src="https://img.shields.io/badge/agent_skill-included-84CC16?style=flat-square&amp;labelColor=000000"></a>
  <br>
  <a href="https://github.com/shy-tangerine/Sleeper/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/shy-tangerine/Sleeper?style=flat-square&amp;labelColor=000000&amp;color=FACC15&amp;logo=github&amp;logoColor=white"></a>
  <a href="https://github.com/shy-tangerine/Sleeper/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/shy-tangerine/Sleeper/total?style=flat-square&amp;labelColor=000000&amp;color=38BDF8"></a>
  <a href="../../LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-A78BFA?style=flat-square&amp;labelColor=000000"></a>
  <a href="https://github.com/sponsors/shy-tangerine"><img alt="Sponsor" src="https://img.shields.io/badge/Sponsor-%E2%99%A5-F472B6?style=flat-square&amp;labelColor=000000&amp;logo=githubsponsors&amp;logoColor=white"></a>
</p>

Deixe seu agente controlar o navegador que você já usa, no desktop ou no Android. Com o Sleeper, ele pode navegar por sites, ler páginas, preencher formulários, fazer capturas de tela e extrair dados estruturados pela CLI ou pelo MCP, sem copiar credenciais de sessão para a configuração do agente.

[Instalar](#instalar) · [Recursos](#recursos) · [Comandos](../../docs/commands.md) · [Configuração do agente](../../docs/agent-skill.md) · [Privacidade](../../PRIVACY.md) · [Segurança](../../SECURITY.md) · [Benchmarks](#benchmarks) · [Contribuir](#contribuir)

## Instalar

Instale primeiro o [uv](https://docs.astral.sh/uv/getting-started/installation/) e execute o instalador a partir de um checkout no **Linux ou macOS** (as plataformas de desktop suportadas):

```bash
./install.sh
```

No Windows, o funcionamento é de melhor esforço e não é uma plataforma suportada no lançamento; execute no PowerShell:

```powershell
py scripts/install.py
```

Escolha **Everything** ou **Customize** (Tudo ou Personalizar) para selecionar MCP, plugins nativos e instruções independentes. O instalador inicia o daemon, instala a CLI, mantém a extensão do Chromium em uma pasta permanente e copia os pacotes dos navegadores para Downloads.

O Firefox para Android se conecta pelo Tailscale Serve (**beta**). Execute `sleeper mobile setup` e abra o QR code no Firefox; consulte o [guia de configuração do Android](../../docs/android.md). O daemon continua vinculado somente ao loopback.

### Codex e Claude Code

Na configuração manual, instale primeiro o runtime do Sleeper e execute os comandos correspondentes na raiz do repositório.

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
<summary>Instalar o plugin do agente após o lançamento público</summary>

```bash
# Codex
codex plugin marketplace add https://github.com/shy-tangerine/Sleeper.git
codex plugin add sleeper --marketplace sleeper-local

# Claude Code
claude plugin marketplace add https://github.com/shy-tangerine/Sleeper.git --scope user
claude plugin install sleeper@sleeper --scope user
```

</details>

Reinicie o agente após a instalação para que ele carregue a skill incluída e o servidor MCP. A [configuração do agente](../../docs/agent-skill.md#native-plugins) explica a instalação pública pelo GitHub, a verificação, as atualizações e a remoção.

| Navegador | Concluir a instalação |
|---|---|
| Chromium | Abra a página de extensões, ative **Developer mode**, escolha **Load unpacked** e selecione a pasta indicada pelo instalador. |
| Firefox | Instale o pacote assinado `sleeper-firefox.xpi` em **Extensões → Instalar extensão de arquivo**. A publicação de pacotes assinados depende das credenciais de assinatura da Mozilla. |

A aprovação das permissões do navegador é necessária uma vez. [Instalação, atualizações e remoção](../../docs/installation.md).

Prefere configurar o cliente manualmente? Use os [comandos verificados dos plugins do Codex e do Claude Code](../../docs/agent-skill.md#native-plugins).

<details>
<summary>Instalar pelo GitHub após o lançamento público</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/shy-tangerine/Sleeper/main/install.sh | bash
```

</details>


Consulte as abas abertas e a página atual:

```bash
sleeper tabs
sleeper snapshot
sleeper type --role textbox --name Search 'your query' --clear
sleeper press Enter
```

A [skill incluída](../../skills/sleeper/SKILL.md) explica como selecionar a sessão, verificar ações e recuperar a conexão. Agentes podem usar as ferramentas MCP diretamente; o [guia de comandos](../../docs/commands.md) cobre abas, extração, receitas e chamadas de API.

| Aguardando | Trabalhando |
|:---:|:---:|
| <img src="../../extension/icon.svg" width="48" alt="Sleeper with closed eyes"> | <img src="../../extension/icon-active.svg" width="48" alt="Sleeper with open eyes"> |

## Recursos

- 📱 **Firefox for Android (beta):** Execute o Sleeper no Android por meio de uma conexão privada do Tailscale Serve com o daemon do desktop. Não é necessário Caddy, uma porta do roteador ou um listener público.
- 🖥️ **Firefox + Chromium desktop:** Controle páginas de uma sessão existente pela extensão. Linux e macOS são suportados; Windows é melhor esforço.
- 🗂️ **Perfis e abas:** Cada instalação tem seu próprio ID persistente. Agentes descobrem os navegadores conectados e selecionam a aba desejada.
- 🎯 **Seleção de elementos:** Encontre controles por seletor CSS, papel e nome acessíveis ou uma referência retornada por `snapshot`.
- 📝 **Interação com páginas:** Preencha campos, pressione teclas, clique em controles e aguarde seletores ou texto antes da próxima ação.
- 📋 **Extração estruturada:** Leia um elemento, reúna correspondências ou extraia um mapa JSON. Salve tarefas repetíveis como receitas e esquemas.
- 📸 **Capturas de tela:** Capture a área visível ou a página inteira, com anotações opcionais. O PNG tem um limite de tamanho; consulte as [opções de captura](../../docs/commands.md#use-the-cli).
- 🌐 **Rede e APIs:** Inspecione requisições capturadas e chame APIs HTTPS permitidas com credenciais mantidas no navegador e vinculadas ao host de origem.
- 🔒 **Ocultação de segredos:** Os resultados estruturados passam por um filtro de dados sensíveis antes de chegar à CLI ou ao cliente MCP. O filtro não é infalível, e as capturas podem conter informações privadas.
- 🔌 **CLI e MCP:** Execute comandos ou chame ferramentas MCP pelo daemon local.
- 📖 **Skill incluída:** Fornece instruções ao agente para selecionar sessões, verificar ações e recuperar a conexão.



## Benchmarks

Cinco execuções verificadas por interface, em uma única máquina. Cada sequência navega, lê um título, digita, clica, aguarda um texto e lê o resultado.

Testado no Linux com **Helium 0.17.0.1 (Chromium 153.0.8010.36)**. Todas as interfaces usaram a mesma versão do navegador e um perfil novo.

<table>
  <tr>
    <td align="center" valign="top" width="33%"><h3>76.7%</h3>menos tempo de sequência<br><sub>Sleeper CLI vs OpenCLI</sub></td>
    <td align="center" valign="top" width="33%"><h3>86.1%</h3>menos tempo de sequência<br><sub>Sleeper MCP vs Playwright MCP</sub></td>
    <td align="center" valign="top" width="33%"><h3>98.6%</h3>menos tokens de texto do protocolo<br><sub>Sleeper CLI vs OpenCLI</sub></td>
  </tr>
</table>

Os percentuais usam as medianas arredondadas da tabela.

| Interface | Mediana da sequência | Mediana do RSS do navegador | Tokens de texto da tarefa | Tokens de texto do protocolo |
|---|---:|---:|---:|---:|
| Sleeper CLI | 934 ms | 1,139 MiB | 441 | 409 (HTTP JSON) |
| Sleeper MCP | 227 ms | 1,152 MiB | 502 | 695 (JSON-RPC) |
| OpenCLI | 4,011 ms | 1,218 MiB | 364 | 29,152 (HTTP JSON) |
| Playwright MCP | 1,635 ms | 1,027 MiB | 536 | 734 (JSON-RPC) |
| Direct CDP | 291 ms | 1,038 MiB | Não se aplica | 956 (CDP) |

Os tokens da tarefa estimam a entrada e a saída visíveis ao agente com `o200k_base`. Os tokens de protocolo contam o tráfego interno HTTP JSON, JSON-RPC ou CDP; não representam o consumo do modelo. O CDP direto não tem uma interface de texto de tarefa voltada ao agente.

O RSS soma a memória dos processos do navegador, pode contar páginas compartilhadas mais de uma vez e exclui os daemons. Tempo e protocolo são capturados em execuções separadas. Estes resultados vêm de uma única máquina, um único build de navegador e uma única data de execução (2026-09-11), medindo primitivas determinísticas do navegador, não conclusão de tarefas por agentes nem velocidade geral; consulte as [ressalvas canônicas de metodologia](../../docs/benchmarks/matched-browser-interface.md#canonical-caveat-block), que devem acompanhar estes números ondequer que sejam citados. [Amostras, metodologia, custos de descoberta e comparação de recursos](../../docs/benchmarks/matched-browser-interface.md).

<details>
<summary>Verificação dos navegadores no Linux</summary>

| Navegador | Versão | Resultado |
|---|---|---|
| Firefox | 155.0.1 | Aprovado |
| Chrome | 151.0.7922.47 | Aprovado |
| Zen | 1.22b | Aprovado |
| Helium | 0.17.0.1 (Chromium 153.0.8010.36) | Aprovado |

O teste do Chrome usou o Google Chrome for Testing, a distribuição do Chrome para automação. A versão exata está na tabela.

</details>

## Contribuir

[Compilar e testar](../../docs/installation.md#development) · [Histórico de alterações](../../CHANGELOG.md) · [Avisos de terceiros](../../THIRD_PARTY_NOTICES.md) · [Privacidade](../../PRIVACY.md) · [Segurança](../../SECURITY.md) · [Licença MIT](../../LICENSE) · [Patrocínio](../../docs/SPONSORS.md)

<details>
<summary>Estrutura do repositório</summary>

| Diretório | Conteúdo |
|---|---|
| `extension/` | Manifestos, handlers de página, popup e ícones |
| `daemon/` | Relay HTTP/WebSocket e servidor MCP |
| `cli/` | CLI, receitas e adaptadores |
| `skills/` | Instruções para agentes |
| `examples/` | Receitas e esquemas de extração |
| `test/` | Testes de comportamento, transporte e pacotes |

</details>

## Histórico de estrelas

[Veja o gráfico de estrelas](https://www.star-history.com/#shy-tangerine/Sleeper&Date) quando o repositório público for lançado.

## Build do pacote Python (PyPI)

O fluxo de lançamento da extensão do navegador é separado do empacotamento Python. Os metadados do pacote Python estão em `pyproject.toml`; o ambiente de desenvolvimento é gerenciado por `uv.lock`. Execute `uv lock --check`, `uv sync --locked` e `uv build` para produzir um sdist e um wheel em `dist/`. Somente após a aprovação do proprietário e a configuração das credenciais do PyPI ou do Trusted Publishing, `uv publish` poderá enviar esses artefatos. Fazer o build não autoriza o lançamento.
