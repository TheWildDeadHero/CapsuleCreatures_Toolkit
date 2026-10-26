"""!The `capsule-studio` command line.

Every editor area contributes a command group through a module with a
register(subparsers) function, listed in COMMAND_MODULES; extensions add
theirs through the plugin host (capsule_studio.plugins): the studio's own
extensions always, a project's plugins with --project. This file only
builds the parser and runs the chosen command. Commands work on manifest
files directly and need no display, so they run in CI and containers.

Exit status: 0 on success, 1 when the command found problems (e.g. validate),
2 on usage errors.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .. import __version__
from ..core import engine
from ..core.document import DocumentError

if TYPE_CHECKING:
   from ..plugins.registry import Registry

## Modules (relative to this package) that register command groups.
COMMAND_MODULES = ["assets_cmds", "sprite_cmds", "text_cmds", "world_cmds", "field_cmds", "battle_cmds", "script_cmds",
                   "project_cmds", "template_cmds", "map_field_cmds", "behavior_cmds",
                   # [S2] engine I4: text tables, proportional fonts, text box styles, manifest includes
                   "text_table_cmds",
                   # [S3] engine DS1 (D-30): door assets, door bindings, the draw order rule
                   "door_cmds",
                   # [S6] engine UC / UM (D-33): screen graphics, screen plans, the GBA memory settings and report
                   "screen_cmds",
                   # [S6b] engine C13b: the world's cell interaction rules
                   "interaction_cmds",
                   # [S7] engine M4 (D-34): the audio manifest (songs, instruments, samples, MIDI, sounds)
                   "audio_cmds"]
## Modules (relative to this package) that add actions to the `battle FILE` group (each has a
## register_actions(subparsers) function; battle_cmds calls them).
BATTLE_ACTION_MODULES = ["structure_cmds", "tier_stage_cmds", "condition_cmds", "turn_progress_cmds", "logic_cmds",
                         "bench_cmds", "resource_cmds", "passive_slot_cmds", "message_cmds",
                         "species_field_cmds", "inventory_cmds", "ai_cmds", "delayed_hit_cmds", "growth_cmds",
                         "recruit_cmds", "field_effect_cmds", "field_action_cmds", "step_effect_cmds",
                         "combine_cmds", "nursery_cmds"]
## Exit status for usage errors.
USAGE_ERROR_STATUS = 2


class CommandError(Exception):
   """!A command could not do what was asked; the message says why."""
   pass


def plugin_registry(project: str | Path | None = None) -> Registry:
   """!The studio's own extensions, plus a project's plugins.
   @param project  project.json (capsule.project/1) whose "plugins" load, or None
   @return plugins.Registry
   """
   from ..plugins import loader, project as proj
   reg = loader.builtin_registry()
   if project:
      reg = reg.copy()
      path = Path(project).resolve()
      # project.json sits in the game folder's reference/ folder.
      loader.load_folders(reg, proj.plugin_folders(path, path.parent.parent))
   return reg


def add_plugin_commands(sub: argparse._SubParsersAction, reg: Registry) -> None:
   """!Adds the registered extension commands, one group per plugin.
   @param sub  argparse subparsers
   @param reg  plugins.Registry
   @return None
   """
   groups: dict[str, argparse._SubParsersAction] = {}
   for c in reg.commands():
      if c.group not in groups:
         info = reg.plugins.get(c.plugin)
         g = sub.add_parser(c.group, help=f"{info.title if info else c.plugin} (extension {c.plugin})")
         groups[c.group] = g.add_subparsers(dest=f"{c.group}_command", metavar="ACTION")
         groups[c.group].required = True
      q = groups[c.group].add_parser(c.name, help=c.help)
      c.setup(q)
      q.set_defaults(run=c.run)


def build_parser(reg: Registry | None = None) -> argparse.ArgumentParser:
   """!Creates the argument parser with every registered command.
   @param reg  plugins.Registry whose commands to add (default: the studio's own extensions)
   @return argparse.ArgumentParser
   """
   p = argparse.ArgumentParser(prog="capsule-studio", description="CapsuleCreatures Studio command line.")
   p.add_argument("--version", action="version", version=f"capsule-studio {__version__}")
   p.add_argument("--engine", metavar="DIR", help=f"engine checkout (default: ${engine.ENV_VAR}, the umbrella's "
                                                  "../engine, ../CapsuleCreatures_Engine-work, "
                                                  "../CapsuleCreatures_Engine)")
   p.add_argument("--project", metavar="FILE", help="a game's reference/project.json: also load the plugins it "
                                                    "lists (their commands, and their validators in world validate)")
   sub = p.add_subparsers(dest="command", metavar="COMMAND")
   sub.required = True
   for name in COMMAND_MODULES:
      importlib.import_module(f"{__package__}.{name}").register(sub)
   add_plugin_commands(sub, reg if reg is not None else plugin_registry())
   for where, msg in (reg.errors if reg is not None else []):
      print(f"capsule-studio: plugin not loaded: {msg}", file=sys.stderr)
   return p


def main(argv: Sequence[str] | None = None) -> int:
   """!Runs one command.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   # --project is read first: the plugins it loads add commands to the real parser.
   pre = argparse.ArgumentParser(add_help=False)
   pre.add_argument("--project")
   known, _ = pre.parse_known_args(sys.argv[1:] if argv is None else argv)
   try:
      reg = plugin_registry(known.project)
   except (OSError, ValueError) as e:
      print(f"capsule-studio: error: --project: {e}", file=sys.stderr)
      return USAGE_ERROR_STATUS
   args = build_parser(reg).parse_args(argv)
   args.registry = reg
   if args.engine:
      import os
      os.environ[engine.ENV_VAR] = args.engine
   try:
      return args.run(args) or 0
   except (CommandError, DocumentError, engine.EngineNotFound, ValueError, OSError) as e:
      print(f"capsule-studio: error: {e}", file=sys.stderr)
      return 1


if __name__ == "__main__":
   sys.exit(main())
