# Simcenter Amesim MCP — Codex / Amesim 2404

An independent MCP server for creating, editing, compiling and simulating Siemens
Simcenter Amesim circuits. Default target: **2404 on Windows x64**.

> Unofficial project; not affiliated with or endorsed by Siemens.
> "Simcenter Amesim" is a Siemens trademark.
> Based on [SometingGBBB/Simcenter-amesim-MCP](https://github.com/SometingGBBB/Simcenter-amesim-MCP).
> See [LICENSE](LICENSE) for project and bundled dependency notices.

## Быстрый старт / Quick start

Требуются Windows x64, лицензированная установка Amesim 2404 и Codex.
Python 3.12/3.13 x64 нужен для MCP; встроенный Python Amesim используется
отдельно для Circuit API. Запускать графический интерфейс Amesim не требуется.

```powershell
git clone <ваш-форк>
cd Simcenter-Amesim-MCP
.\install.ps1
.\configure-codex.ps1 -AmesimHome "D:\Programs\Simcenter\2404\Amesim"
```

Если PowerShell запрещает запуск локальных скриптов, для каждого скрипта используйте
`powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1`
и аналогичную команду для `configure-codex.ps1` с нужными аргументами.
Это не меняет постоянную политику выполнения.

Установщик ищет Python через реестр и стандартные каталоги, создаёт `.venv`,
устанавливает зависимости и запускает базовый doctor. Если Python отсутствует,
он автоматически устанавливает Python 3.13 x64 через winget в профиль пользователя.
Интернет требуется для установки зависимостей. Можно задать
`.\install.ps1 -Python "C:\path\to\python.exe"`.

**Перезапустите Codex после конфигурации.** Затем попросите:
«Через Amesim MCP выполни doctor, подключись к 2404 и проверь status.
После проверки отключись».

Конфигурация хранится в `~/.codex/config.toml` (или `CODEX_HOME/config.toml`).
Перед изменением создаётся резервная копия с датой.
Существующий сервер `amesim` заменяется только с `-Force`.
Другие настройки сохраняются.

### English setup

Install licensed Amesim 2404 and Codex, then run the quick-start commands above.
`install.ps1` discovers Python 3.12/3.13 x64 without relying on PATH, creates
a virtual environment, installs the project and runs diagnostics. If necessary,
it installs Python 3.13 using winget. Restart Codex after configuration.
The Amesim GUI does not need to be running; the worker checks out its own license.

## Amesim discovery

Set `AMESIM_HOME` to the directory containing `win64/AMEPython.exe`.
A parent installation directory containing an `Amesim` folder is also accepted.
The configure script records this path only in the MCP environment; it does not
modify system environment variables.

Without `AMESIM_HOME`, discovery checks `AME`, installation registry entries,
and common Simcenter locations on C:, D: and E:. Invalid explicit
`AMESIM_HOME` fails clearly instead of silently choosing another installation.

License settings `LMS_LICENSE` and `SC1D_LICENSING_TYPE` are inherited or
read from user/machine environment registry values. Doctor reports only whether
they are present. A deep doctor actually initializes the API, so an occupied or
unavailable license can still prevent connection.

## Diagnostics and real simulation test

```powershell
.\.venv\Scripts\amesim-mcp-doctor.exe
.\.venv\Scripts\amesim-mcp-doctor.exe --deep
.\.venv\Scripts\amesim-mcp-smoke.exe
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For the two additional live license/RPC/process-lifecycle tests:

```powershell
$env:AMESIM_MCP_LIVE_TESTS = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:AMESIM_MCP_LIVE_TESTS
```

The smoke test reads the registered Codex `amesim` configuration and talks
through the MCP STDIO protocol. It creates a new mass–spring–damper circuit using
SIN0, FORC, MECMAS21, SD0000 and V001; sets mass 10 kg, stiffness 1000 N/m,
damping 20 N/(m/s), sine amplitude 100 N and frequency 1 Hz; compiles it and runs
5 seconds with a 0.01 s output interval.
Before connecting ports, it rotates the force and spring-damper icons, aligns
the four signal/mechanical ports at one sketch height using their actual port
coordinates, and routes the final line to ground with a right-angle bend.

It verifies finite, nonzero displacement and velocity, increasing sample times
and the final time; saves the .ame model, results.csv, results.json and
summary.json; reopens the saved model, checks the saved line geometry and reruns
the simulation; then disconnects. Default results:
`%LOCALAPPDATA%\amesim-mcp\smoke-tests\<timestamp>`.
Use `amesim-mcp-smoke --output "C:\new\empty-directory"` for a custom NEW directory.
Logs are in `%LOCALAPPDATA%\amesim-mcp\logs`.
The exact resolved output/log paths are printed; Windows packaged apps may
redirect LocalAppData into their package cache.

## Tools and approvals

Workflow: `connect` → `create_circuit` / `open_ame_file` → add components,
assign submodels, connect zero-based ports, set parameters → `generate_code`
→ `run_simulation` → read/export results → save → `disconnect`.

`connect_two_ports` requires a unique `line_alias` and creates a visible line
in the sketch. Older models built with `AMEConnectTwoPorts` have invisible
DIRECT connections; rebuild them to display the wiring. Use `get_line_geometry`
to verify a visible line's endpoints. Optional `bend_points=[[x, y], ...]`
routes a line through the given sketch pixels. `get_component_geometry` reads
the component position, size and port coordinates so icons can be aligned before
connecting them. `rotate_component` turns an icon by 90 degrees per step; moving
an already-connected component does not move its line geometry.

When an archive shares its folder with stale expanded Amesim files, open it
with `open_ame_file(path, fresh=True)`. This copies the archive into a unique
temporary folder and leaves the original and its expanded files untouched.
Edits to the isolated circuit must be saved with `save_circuit_as` to a new path.

- `connect(version="2404")`: owns a fresh worker and checks out a license.
- `doctor(deep=False)`: installation checks; deep mode briefly uses a license.
- `get_api_help(function_name)`: documentation from the installed API.
- `save_circuit_as(path)`: save to a NEW .ame file; refuses existing targets.
- `export_results_csv(data_paths, output_path)`: NEW CSV plus JSON summary;
  requires aligned time grids and refuses existing outputs.
- Ordinary construction, parameter changes, code generation and simulation run
  without confirmation.
- Codex prompts for component/line removal, `save_circuit` (potential overwrite),
  `close_circuit` (potential loss), and enabled `execute_python`.

`execute_python` is absent by default. To explicitly enable arbitrary local
Python execution inside the Amesim worker:

```powershell
.\configure-codex.ps1 -AmesimHome "D:\Programs\Simcenter\2404\Amesim" -EnableUnsafePython -Force
```

Restart Codex afterward. It prompts before this tool, limits output to 65536
characters, and stops the worker after 30 seconds if execution does not return.
A timeout loses unsaved worker state. To disable it, configure again without
`-EnableUnsafePython`, using `-Force`.

Approvals are enforced by the Codex client configuration. MCP annotations alone
are descriptive hints; other clients must configure their own approval policy.
See [official Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp).

## Architecture and lifecycle

The MCP process runs ordinary Python 3.12/3.13 and exposes STDIO.
It launches Amesim's `AMEPython.exe` with stdout/stderr redirected to a log.
A loopback RPyC OneShotServer invokes API functions on the worker's main thread.
Only a JSON request endpoint and an allowlist of Amesim functions are exposed;
there is no SlaveService, module access or pickle loading. Each connection
uses a random session secret and challenge verification on an OS-selected port.

Disconnect closes the API, the RPyC connection and the owned process.
Communication failures clean up the worker. A worker watchdog exits if its
owning MCP process disappears. Calls are serialized; simulation/RPC timeout
is 300 seconds, Codex tool timeout is 360 seconds.

Bundled `vendor/` dependencies are used only inside Amesim's interpreter;
the MCP virtual environment installs its own dependencies. Keep the checkout
in place after installing with `pip install -e .`. On another computer,
clone and rerun both scripts with that computer's Amesim path.
Docker is not required.
