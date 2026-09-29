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

Deja que tu agente controle el navegador que ya utilizas, tanto en tu escritorio como en Android. Con Sleeper puede navegar por sitios web, leer páginas, rellenar formularios, hacer capturas y extraer datos estructurados mediante CLI o MCP, sin copiar las credenciales de sesión a la configuración del agente.

[Instalar](#instalar) · [Funciones](#funciones) · [Comandos](../../docs/commands.md) · [Configuración del agente](../../docs/agent-skill.md) · [Privacidad](../../PRIVACY.md) · [Seguridad](../../SECURITY.md) · [Benchmarks](#benchmarks) · [Contribuir](#contribuir)

## Instalar

Instala primero [uv](https://docs.astral.sh/uv/getting-started/installation/) y ejecuta el instalador desde una copia del repositorio en **Linux o macOS** (las plataformas de escritorio compatibles):

```bash
./install.sh
```

En Windows, funciona sobre la base del mejor esfuerzo y no es una plataforma compatible en el lanzamiento; ejecuta en PowerShell:

```powershell
py scripts/install.py
```

Elige **Everything** o **Customize** (Todo o Personalizar) para seleccionar MCP, plugins nativos e instrucciones independientes. El instalador inicia el daemon, instala la CLI, guarda la extensión de Chromium en una carpeta permanente y copia los paquetes de los navegadores a Descargas.

Firefox para Android se conecta mediante Tailscale Serve (**beta**). Ejecuta `sleeper mobile setup` y abre el código QR en Firefox; consulta la [guía de configuración de Android](../../docs/android.md). El daemon permanece vinculado únicamente a loopback.

### Codex y Claude Code

Para la configuración manual, instala primero el runtime de Sleeper y ejecuta los comandos correspondientes desde la raíz del repositorio.

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
<summary>Instalar el plugin del agente después del lanzamiento público</summary>

```bash
# Codex
codex plugin marketplace add https://github.com/shy-tangerine/Sleeper.git
codex plugin add sleeper --marketplace sleeper-local

# Claude Code
claude plugin marketplace add https://github.com/shy-tangerine/Sleeper.git --scope user
claude plugin install sleeper@sleeper --scope user
```

</details>

Reinicia el agente después de instalarlo para que cargue la skill incluida y el servidor MCP. La [configuración del agente](../../docs/agent-skill.md#native-plugins) explica la instalación pública desde GitHub, la verificación, las actualizaciones y la eliminación.

| Navegador | Completar la instalación |
|---|---|
| Chromium | Abre la página de extensiones, activa **Developer mode**, elige **Load unpacked** y selecciona la carpeta indicada por el instalador. |
| Firefox | Instala el paquete firmado `sleeper-firefox.xpi` desde **Complementos → Instalar complemento desde archivo**. La publicación de paquetes firmados está pendiente de las credenciales de firma de Mozilla. |

La aprobación de permisos del navegador se realiza una vez. [Instalación, actualizaciones y eliminación](../../docs/installation.md).

¿Prefieres configurar el cliente manualmente? Usa los [comandos verificados de los plugins de Codex y Claude Code](../../docs/agent-skill.md#native-plugins).

<details>
<summary>Instalar desde GitHub después del lanzamiento público</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/shy-tangerine/Sleeper/main/install.sh | bash
```

</details>


Consulta las pestañas abiertas y la página actual:

```bash
sleeper tabs
sleeper snapshot
sleeper type --role textbox --name Search 'your query' --clear
sleeper press Enter
```

La [skill incluida](../../skills/sleeper/SKILL.md) explica cómo seleccionar la sesión, verificar las acciones y recuperar la conexión. Los agentes pueden usar directamente las herramientas MCP; la [guía de comandos](../../docs/commands.md) cubre pestañas, extracción, recetas y llamadas a APIs.

| En espera | Trabajando |
|:---:|:---:|
| <img src="../../extension/icon.svg" width="48" alt="Sleeper with closed eyes"> | <img src="../../extension/icon-active.svg" width="48" alt="Sleeper with open eyes"> |

## Funciones

- 📱 **Firefox for Android (beta):** Ejecuta Sleeper en Android mediante una conexión privada de Tailscale Serve con el daemon de tu escritorio. No necesitas Caddy, un puerto del router ni un listener público.
- 🖥️ **Firefox + Chromium desktop:** Controla páginas de una sesión existente mediante la extensión. Linux y macOS son compatibles; Windows es de mejor esfuerzo.
- 🗂️ **Perfiles y pestañas:** Cada instalación tiene su propio ID persistente. Los agentes descubren los navegadores conectados y seleccionan la pestaña adecuada.
- 🎯 **Selección de elementos:** Encuentra controles por selector CSS, rol y nombre accesibles o una referencia devuelta por `snapshot`.
- 📝 **Interacción con páginas:** Rellena campos, pulsa teclas, haz clic y espera selectores o texto antes de la siguiente acción.
- 📋 **Extracción estructurada:** Lee un elemento, recopila coincidencias o extrae un mapa JSON. Guarda tareas repetibles como recetas y esquemas.
- 📸 **Capturas de pantalla:** Captura el área visible o la página completa, con anotaciones opcionales. El PNG tiene un límite de tamaño; consulta las [opciones de captura](../../docs/commands.md#use-the-cli).
- 🌐 **Red y APIs:** Inspecciona peticiones capturadas y llama a APIs HTTPS permitidas con credenciales que permanecen en el navegador y vinculadas a su host de origen.
- 🔒 **Ocultación de secretos:** Los resultados estructurados pasan por un filtro de datos sensibles antes de llegar a la CLI o al cliente MCP. El filtrado no es infalible y las capturas pueden contener información privada.
- 🔌 **CLI y MCP:** Ejecuta comandos o llama a herramientas MCP mediante el daemon local.
- 📖 **Skill incluida:** Proporciona instrucciones al agente para seleccionar sesiones, verificar acciones y recuperar la conexión.



## Benchmarks

Cinco ejecuciones verificadas por interfaz, en una sola máquina. Cada secuencia navega, lee un encabezado, escribe, hace clic, espera texto y lee el resultado.

Probado en Linux con **Helium 0.17.0.1 (Chromium 153.0.8010.36)**. Todas las interfaces usaron la misma versión del navegador y un perfil nuevo.

<table>
  <tr>
    <td align="center" valign="top" width="33%"><h3>76.7%</h3>menos tiempo de secuencia<br><sub>Sleeper CLI frente a OpenCLI</sub></td>
    <td align="center" valign="top" width="33%"><h3>86.1%</h3>menos tiempo de secuencia<br><sub>Sleeper MCP frente a Playwright MCP</sub></td>
    <td align="center" valign="top" width="33%"><h3>98.6%</h3>menos tokens de texto del protocolo<br><sub>Sleeper CLI frente a OpenCLI</sub></td>
  </tr>
</table>

Los porcentajes usan las medianas redondeadas de la tabla.

| Interfaz | Mediana de secuencia | Mediana de RSS del navegador | Tokens de texto de tarea | Tokens de texto de protocolo |
|---|---:|---:|---:|---:|
| Sleeper CLI | 934 ms | 1,139 MiB | 441 | 409 (HTTP JSON) |
| Sleeper MCP | 227 ms | 1,152 MiB | 502 | 695 (JSON-RPC) |
| OpenCLI | 4,011 ms | 1,218 MiB | 364 | 29,152 (HTTP JSON) |
| Playwright MCP | 1,635 ms | 1,027 MiB | 536 | 734 (JSON-RPC) |
| Direct CDP | 291 ms | 1,038 MiB | No aplicable | 956 (CDP) |

Los tokens de tarea estiman la entrada y salida visibles para el agente mediante `o200k_base`. Los tokens de protocolo cuentan el tráfico interno HTTP JSON, JSON-RPC o CDP; no representan el consumo del modelo. CDP directo no tiene una interfaz de texto de tarea para agentes.

El RSS suma la memoria de los procesos del navegador, puede contar páginas compartidas más de una vez y excluye los daemons. El tiempo y el protocolo se capturan en ejecuciones separadas. Estos resultados provienen de una sola máquina, una sola compilación del navegador y una sola fecha de ejecución (2026-09-11), y miden primitivas deterministas del navegador, no la finalización de tareas por agentes ni la velocidad general; consulte las [advertencias canónicas de metodología](../../docs/benchmarks/matched-browser-interface.md#canonical-caveat-block), que deben acompañar estas cifras dondequiera que se citen. [Muestras, metodología, costes de descubrimiento y comparación de funciones](../../docs/benchmarks/matched-browser-interface.md).

<details>
<summary>Comprobaciones de navegadores en Linux</summary>

| Navegador | Versión | Resultado |
|---|---|---|
| Firefox | 155.0.1 | Correcto |
| Chrome | 151.0.7922.47 | Correcto |
| Zen | 1.22b | Correcto |
| Helium | 0.17.0.1 (Chromium 153.0.8010.36) | Correcto |

La prueba de Chrome utilizó Google Chrome for Testing, la distribución de Chrome para automatización. La versión exacta aparece arriba.

</details>

## Contribuir

[Compilar y probar](../../docs/installation.md#development) · [Registro de cambios](../../CHANGELOG.md) · [Avisos de terceros](../../THIRD_PARTY_NOTICES.md) · [Privacidad](../../PRIVACY.md) · [Seguridad](../../SECURITY.md) · [Licencia MIT](../../LICENSE) · [Patrocinio](../../docs/SPONSORS.md)

<details>
<summary>Estructura del repositorio</summary>

| Directorio | Contenido |
|---|---|
| `extension/` | Manifiestos, controladores de página, ventana emergente e iconos |
| `daemon/` | Relay HTTP/WebSocket y servidor MCP |
| `cli/` | CLI, recetas y adaptadores |
| `skills/` | Instrucciones para agentes |
| `examples/` | Recetas y esquemas de extracción |
| `test/` | Pruebas de comportamiento, transporte y paquetes |

</details>

## Historial de estrellas

[Consulta el gráfico de estrellas](https://www.star-history.com/#shy-tangerine/Sleeper&Date) cuando se publique el repositorio.

## Compilación del paquete Python (PyPI)

El flujo de lanzamiento de la extensión del navegador es independiente del empaquetado de Python. Los metadatos del paquete Python están en `pyproject.toml`; `uv.lock` gestiona el desarrollo. Ejecuta `uv lock --check`, `uv sync --locked` y `uv build` para generar un sdist y un wheel en `dist/`. `uv publish` solo puede subir esos artefactos después de la aprobación del propietario y de configurar las credenciales de PyPI o Trusted Publishing. Compilar no equivale a autorizar el lanzamiento.
