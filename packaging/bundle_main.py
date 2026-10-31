"""!Entry point of the prebuilt studio bundle (D-40 RI): every tool of toolkit/env.py's TOOLS in one frozen program.

A bundle has two executables built from this file: `studio` (a windowed program on Windows and the macOS app's
main program) and `capsule-studio` (a console program). Both read their first argument:
  - a tool name from TOOLS (`studio map-editor WORLD`, `capsule-studio template list`): runs that tool, the way
    `toolkit/env.py run TOOL` does in a checkout;
  - a path ending in .py: runs that script as `python script.py ...` would; the studio starts the engine's own
    tools that way through sys.executable (the battle bench), and in a bundle sys.executable is this program;
  - --bundle-smoke WORK_DIR: the bundle's smoke test (bundle_smoke.py);
  - anything else: the executable's own tool (`studio` -> the Studio, `capsule-studio` -> the command line), with
    the arguments passed on.

The studio's Python sources (toolkit/editor/capsule_studio) and the engine checkout it reads (its tools, headers,
assets and the Starter sample) are plain files inside the bundle, not frozen: the extension loader, the plugin
rules and the engine finder (core/engine.py: ../engine beside the toolkit) read them from disk. The bundle's
layout is in packaging/README.md.

Run from the source tree (`python3 toolkit/packaging/bundle_main.py ...`) it uses the checkout's toolkit and engine
instead, for a baseline of the smoke test.
"""
from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

## The bundle's table of tools (written by build_bundle.py from toolkit/env.py TOOLS): name -> module.
TOOLS_FILE = "bundle_tools.json"
## Folder (below the bundle's data root) holding the studio's sources: toolkit/editor.
EDITOR_DIR = ("toolkit", "editor")
## The console executable's name; it runs the command line by default.
CLI_NAME = "capsule-studio"
## The tool the console executable runs by default, and the one every other executable runs.
CLI_TOOL = "capsule-studio"
GUI_TOOL = "studio"
## The argument that starts the smoke test.
SMOKE_FLAG = "--bundle-smoke"
## A Python script's suffix (run as `python script.py`).
SCRIPT_SUFFIX = ".py"
## Folders between this file and the umbrella root in a source checkout (packaging, toolkit).
SOURCE_DEPTH = 2


def data_root() -> Path:
   """!Where the bundle's data lives: PyInstaller's folder (sys._MEIPASS) when frozen, else the umbrella checkout.
   @return Path
   """
   frozen = getattr(sys, "_MEIPASS", None)
   if frozen:
      return Path(frozen)
   return Path(__file__).resolve().parents[SOURCE_DEPTH]


def tools(root: Path) -> dict[str, str]:
   """!The tool table: the bundle's JSON copy when frozen, else toolkit/env.py's TOOLS itself.
   @param root  data_root()
   @return tool name -> module
   """
   table = root / TOOLS_FILE
   if table.is_file():
      return json.loads(table.read_text(encoding="utf-8"))
   env = runpy.run_path(str(root.joinpath("toolkit", "toolkit", "env.py")))
   return {name: module for name, (module, _groups) in env["TOOLS"].items()}


def run_script(args: list[str]) -> int:
   """!Runs a Python script the way `python script.py ARGS` does (sys.argv, sys.path[0], __main__).
   @param args  [script, ARGS...]
   @return exit status (a SystemExit from the script passes through)
   """
   script = Path(args[0]).resolve()
   sys.argv = [str(script), *args[1:]]
   sys.path.insert(0, str(script.parent))
   runpy.run_path(str(script), run_name="__main__")
   return 0


def run_tool(module: str, name: str, args: list[str]) -> int:
   """!Runs a tool the way `python -m MODULE ARGS` does.
   @param module  e.g. "capsule_studio.ui.studio_app"
   @param name    the tool's name (sys.argv[0] while it runs: argparse's program name)
   @param args    its arguments
   @return exit status (the tool's SystemExit passes through)
   """
   sys.argv = [name, *args]
   runpy.run_module(module, run_name="__main__", alter_sys=True)
   return 0


def main() -> int:
   """!Picks what to run from the executable's name and its first argument (see the module docstring).
   @return exit status
   """
   root = data_root()
   # The studio's sources are files, never frozen; nothing writes .pyc files into the bundle (they are built in).
   sys.dont_write_bytecode = True
   sys.path.insert(0, str(root.joinpath(*EDITOR_DIR)))
   args = sys.argv[1:]
   if args and args[0].endswith(SCRIPT_SUFFIX) and Path(args[0]).is_file():
      return run_script(args)
   if args and args[0] == SMOKE_FLAG:
      import bundle_smoke

      return bundle_smoke.main(args[1:])
   table = tools(root)
   if args and args[0] in table:
      return run_tool(table[args[0]], args[0], args[1:])
   own = CLI_TOOL if Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).stem == CLI_NAME \
      else GUI_TOOL
   return run_tool(table[own], own, args)


if __name__ == "__main__":
   sys.exit(main())
