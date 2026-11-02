"""!Guard (review F8): the engine's choice lists are never copied into the
studio. Each name below is the engine's (battle_compiler, effect_compiler,
bench_scenario re-exports); a studio module that assigns one again (a copy
that drifts when the engine changes) fails this test. The studio reads them
from the engine through core.engine.tool() instead.

Guard (A15): the Content pages (ui/editors/content/**) build every
widget from the compiled structure. Their module and class constants are
presentation only (pixels, colours, columns, notes): a new constant fails
until it is added to CONTENT_CONSTANTS here, and a literal list of names in
their code (a closed list such as a category, flag, stat or target list)
fails unless CONTENT_LITERALS names it (table headings, widget and manifest
keys the page itself writes). Former closed lists stay refused by name.

Guard (exports): the point handler owner lists, still motions,
stat input roles, presenter texts and message rules are read from the engine
(battle_compiler's re-exports where it has them), never copied.

Guard (the imported maps / the imported events and sprites, the world format): the movements and their settings, the
warp triggers, on_shift and the map, object, vehicle class and sprite limits are the engine's.

Guard (the engine's exports): the manifest handler lists, the once / at
most once phases, record_inputs(), the species field pattern, the hit's type
(move_type_of(), point_runner(move_type=)), the logic kinds, the ruleset's
unary operators, the bench's owner texts key and the map limits and cell
fields are the engine's. A studio module reads a battlec part only for names
battle_compiler does not re-export (INTERNAL_READS); when the engine starts
re-exporting one, the guard fails until the module switches.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.core import engine  # noqa: E402

## The studio package.
PACKAGE = Path(__file__).resolve().parent.parent / "capsule_studio"
## Names no studio module may assign (the engine's lists; the studio's former copies).
ENGINE_NAMES = ("TARGETS", "AI_FLAGS", "SUBJECTS", "BATTLER_SUBJECTS", "DECISIVE", "DRAWS_PER_ELEMENT",
                "DRAWS_PER_KIND", "EACH_PHASES", "LOGIC_KINDS", "TRACES", "CONTROLLERS", "PARTY_FLAGS",
                "ANSWER_KINDS", "STOP_KINDS", "PASSIVE_SLOTS", "MAX_PASSIVE_SLOT", "DEFAULT_PASSIVE_SLOTS",
                "COUNTER_ALIASES", "COUNTER_ALIAS_KEYS", "GENERATOR_NAME", "RNG_NAME", "OPTIONAL_MESSAGES",
                "REGEN_RANGE", "MAX_FORMULAS",
                # The effect handlers' exports: the point handler owner lists and the former copies of them, the still
                # motions, the stat input roles, the presenter texts, the retired messages, the layers' priority
                "OWNER_SOURCES", "OWNER_KINDS", "HANDLER_OWNERS", "POINT_OWNER_LISTS", "HANDLER_LISTS",
                "HANDLER_KINDS", "STILL_MOTIONS", "STAT_INPUT_ROLES", "PRESENTER_TEXTS", "BATTLE_ENTRY_TEXTS",
                "RETIRED_MESSAGES", "MAX_PRIORITY",
                # The engine's exports: the former copies and guesses of them
                "MANIFEST_HANDLER_LISTS", "EFFECT_RECORD", "ONCE_PHASES", "AT_MOST_ONCE_PHASES", "SPECIES_FIELD_NAME",
                "KIND_LISTS", "UNARY_OPERATORS", "INVERT", "OWNER_TEXTS_KEY", "MAX_LAYERS", "MAX_METATILES",
                "MAX_BEHAVIORS", "MAX_BORDER", "MAX_BORDER_SIZE", "CELL_FIELDS", "MAX_LAYER_PRIORITY",
                "MAX_COLLISION", "ATTRIBUTE_TOPS",
                # The AI rules and their numbers, bound_to, the delayed hits' names
                "AI_RULES", "AI_SWITCH_RULES", "AI_RULE_ARGS", "AI_SWITCH_ARGS", "MAX_AI_PROFILES", "MAX_AI_RULES",
                "AI_DEFAULT_PROFILE", "BOUND_TO", "DELAYED_AT_USE", "DELAYED_HIT_FLAGS", "DELAYED_DEFAULT_FLAGS",
                "DEFAULT_MISS_MESSAGE", "DELAYED_MAX_ACCURACY",
                # The growth triggers and limits, the form and training names
                "ITEM_TRIGGERS", "UNCANCELLABLE", "TIME_OF_DAY", "CONTEXT_SOURCES", "MAX_CONTEXT_VALUES",
                "MAX_TRANSFORMS", "MAX_FORMS", "BASE_FORM", "TRAIN_GAIN_ARGS", "MAX_TRAINING",
                # The world format: the movements and their settings, the warp triggers, the animation
                # shift words and the map, object, vehicle and sprite limits (core.objects / events / tilesets / maps /
                # field_rules / sprites read them; objects.py's MOVEMENTS / MAX_OBJECTS / MAX_RANGE copies are gone)
                "MOVEMENTS", "MOVEMENT_ARGS", "DELAYS", "PACES", "WARP_TRIGGERS", "DYNAMIC_TO", "ON_SHIFT",
                "MAX_ANIMATIONS", "MAX_RANGE", "MAX_OBJECTS", "MAX_VIEW_OBJECTS", "MAX_TURN_FRAMES", "MAX_VIEW_CELLS",
                "MAX_FLIP", "STEP_ENTRIES", "MAX_TILES", "MAX_PALETTES", "BANK_COLORS", "MAX_ENTRY")
## Names only some modules may not assign (another module's name means something else): {name: module paths}.
## MESSAGE_KEY: the engine's message key pattern in core/messages.py (core.structure.conditions' is a text key).
## FIELDS / BEHAVIOR_MASK: the map compiler's cell fields in core/maps.py (other modules' FIELDS are their own).
MODULE_NAMES = {"KINDS": ("core/structure/conditions.py",), "MESSAGE_KEY": ("core/messages.py",),
                "FIELDS": ("core/maps.py",), "BEHAVIOR_MASK": ("core/maps.py",),
                # The growth triggers (the map objects' and encounters' TRIGGERS are their own)
                "TRIGGERS": ("core/species_growth.py", "core/structure/transformation.py",
                             "ui/editors/content/species_growth.py", "ui/editors/structure/transformation.py",
                             "cli/growth_cmds.py")}
## Studio modules that read an engine export through battle_compiler (its re-exports), not the battlec part that
## defines it: {module path: battlec modules it must not import}.
REEXPORTED = {"core/messages.py": ("battlec.texts",), "core/battle.py": ("battlec.presenters",),
              "core/codepage.py": ("battlec.presenters",), "core/structure/record.py": ("battlec.rules",),
              # The after-battle screens
              "core/structure/turn.py": ("battlec.turn",), "core/structure/progression.py": ("battlec.progression",),
              "core/structure/record_preview.py": ("battlec.progression",),
              "core/structure/species_fields.py": ("battlec.content",), "core/pipelines.py": ("battlec.pipelines",),
              "core/logic.py": ("battlec.pipelines", "battlec.logic"), "core/holders.py": ("battlec.pipelines",)}
## The studio modules that read a battlec part, with the names they read there: none of them is re-exported by
## battle_compiler (a re-exported one is read from battle_compiler instead): {module path: (part, names)}.
INTERNAL_READS = {"core/structure/resources.py": ("battlec.resources", ("RESOURCE_NAME", "STORAGE_ROLE_BITS")),
                  "core/structure/record.py": ("battlec.layout", ("MAX_ROLE_BITS", "ROLE_SHAPES", "CUSTOM_NAME",
                                                                  "role_key", "stat_key", "ROLE_KEY_PREFIX")),
                  "core/structure/conditions.py": ("battlec.layout", ("status_id_bits",)),
                  "core/structure/chart.py": ("battlec.chart", ("DEFAULT_TYPES_PER_SPECIES", "exponent_of")),
                  "core/structure/passive_slots.py": ("battlec.content", ("PASSIVE_SLOT_NAME",)),
                  # The per-stat roles a field rule's expression reads (ROLE.NAME of a stat)
                  "core/structure/field_expressions.py": ("battlec.layout", ("PER_STAT_ROLES",))}
## A read of a battlec part through core.engine.tool().
BATTLEC_READ = re.compile(r'tool\("(?P<part>battlec\.[a-z_]+)"\)')
## The Content pages' package.
CONTENT = PACKAGE / "ui" / "editors" / "content"
## The constants the Content pages may define, by file: presentation only (no engine or game data). A new one is
## reviewed and added here; a list, count or range of the engine's or the game's comes from the compiled data.
CONTENT_CONSTANTS = {
   "data.py": {"JSON_LISTS", "JSON_OBJECTS"},
   # The Items tab's bag box (presentation) and the Test save (Bag) page's table, file filter and colours
   # The Items tab's Recruit row starts at a bonus of x1 (presentation: the bonus the spin shows first)
   "holders.py": {"NO_POCKET", "FLAG_BOXES", "USE_TEXT_HEIGHT", "NEW_RECRUIT_BONUS"},
   "test_save.py": {"SLOT_COLUMNS", "ITEM_COLUMN", "COUNT_COLUMN", "IMAGE_FILTER", "PROBLEM_COLOR", "OK_COLOR",
                    # The Boxes box's table
                    "BOXED_COLUMNS", "SLOT_COLUMN", "BOX_COLUMN", "SPECIES_COLUMN", "LEVEL_COLUMN",
                    # The Step counters box's table
                    "STEP_COLUMNS", "STEP_NAME_COLUMN", "STEP_COUNT_COLUMN", "STEP_EVERY_COLUMN",
                    "STEP_LEFT_COLUMN",
                    # The boxed egg column and the Nursery box's table
                    "EGG_COLUMN", "HELD_COLUMNS", "EMPTY_SLOT", "MAX_GAINED_SPIN",
                    # The Game box's size spin (Qt's int), hex rows shown and save file filter
                    "MAX_BLOCK_SPIN", "GAME_HEX_ROWS", "SAVE_FILE_FILTER"},
   "messages.py": {"COLUMNS", "ID_COLUMN", "KEY_COLUMN", "KIND_COLUMN", "ARGS_COLUMN", "TEXT_COLUMN",
                   "PROBLEM_COLUMN", "ABSENT_TEXT", "ABSENT_COLOR", "PROBLEM_COLOR", "WITHIN_COLOR", "NOTE"},
   "moves.py": {"DEFAULT_TARGET_INDEX", "COST_HEADINGS", "COST_COLUMN", "FROM_COLUMN", "FROM_MOVE", "FROM_DEFAULT",
                "FROM_FREE", "DEFAULT_COLOR", "COST_ROW_HEIGHT", "FALLBACK_NOTE", "LOGIC_POINTER"},
   "parties.py": {"PRESENTER_ROW_HEIGHT", "PRESENTER_LIST_FRAME"},
   "presenters.py": {"NO_PARTY", "PREVIEW_CUES", "HOLD_FRAMES", "FRAME_MS", "PREVIEW_ZOOM", "BATTLER_BOX",
                     "STAND_MARK", "UNKNOWN_SIZE", "PREVIEW_COLORS", "LABEL_OFFSET", "CAPTION_MARGIN", "OPAQUE"},
   "type_chart.py": {"CHART_HEADER_LETTERS"},
   # The Species page's growth tabs (headings, typed-text separators, colours, table height)
   "species_growth.py": {"RULE_HEADINGS", "FORM_HEADINGS", "LIST_SEPARATOR", "ASSIGN", "STAT_DOT", "FIRES_COLOR",
                         "TABLE_ROWS", "ROW_PIXELS"},
}
## The former closed lists, counts and ranges of the Content pages (A15): never defined again.
RETIRED_CONTENT_NAMES = ("CATEGORIES", "MOVE_FLAGS", "STAT_LABELS", "TYPE_SLOTS", "ABILITY_SLOTS", "MAX_GENES",
                         "MEMBER_MOVES", "MAX_CRIT_STAGE", "CHART_TEXT", "MAX_EXP_YIELD", "MAX_LEVEL",
                         "MIN_LEVEL_MAX", "DEFAULT_PREVIEW_LEVEL", "MAX_ACCURACY", "DEFAULT_ACCURACY", "MAX_BASE",
                         "MAX_PRIORITY", "MAX_REWARD", "DEFAULT_RANK", "DEFAULT_RANK_MAX", "MAX_RANK",
                         "DEFAULT_PARTY_LEVEL", "PRESENTER_LIST_HEIGHT", "MIN_OFFSET", "MAX_OFFSET", "AT_VALUES",
                         "MAX_FRAMES", "TEXT_KEYS", "TEXT_PLACEHOLDERS", "MAX_COLOR_INDEX", "OWNER_KINDS")
## Literal lists of names the Content pages' code may hold, by file (ast.unparse() text): table headings and the
## widget or manifest keys the page itself reads and writes; every other list of two or more names fails.
CONTENT_LITERALS = {
   "data.py": {"['traits']", "['rules', 'stats', 'growth', 'monster_layout']"},
   "messages.py": {"['Id', 'Key', 'Kind', 'Takes', 'Text', 'Engine says']"},
   "moves.py": {"('Resource', 'Cost', 'From')"},
   "presenters.py": {"('enter', 'exit')", "('sequence', 'choose')", "('frames', 'from', 'sequence')"},
   "species.py": {"['Level', 'Move']", "['?', '?']"},
   "test_save.py": {"['Item', 'Count']", "['Slot', 'Box', 'Species', 'Level', 'Egg (steps left)']",
                    "['Step effect', 'Counted', 'Every', 'Next run in']",
                    "['Slot', 'Species', 'Level when left', 'Experience gained']"},
   "species_growth.py": {"('#', 'Becomes', 'When', 'On (given)', 'Looked at on', 'Item used up', 'Also')",
                         "('Form', 'Name', 'Overrides', 'When', 'On')"},
}
## Fewest names a literal list has to count as a closed list.
CLOSED_LIST_MIN = 2
## An assignment of a name at the start of a line (module, class or function level; annotated or not).
ASSIGNMENT = re.compile(r"^\s*(?P<name>[A-Z_][A-Z0-9_]*)\s*(?::[^=]*)?=(?!=)")


def assignments(path: Path) -> list[tuple[int, str]]:
   """!The upper-case names a file assigns.
   @param path  a .py file
   @return (line number, name) per assignment
   """
   out = []
   for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
      m = ASSIGNMENT.match(line)
      if m is not None:
         out.append((n, m.group("name")))
   return out


def content_constants(path: Path) -> list[tuple[int, str]]:
   """!The upper-case names a Content page assigns at module or class level.
   @param path  a .py file
   @return (line number, name) per assignment
   """
   out = []
   tree = ast.parse(path.read_text(encoding="utf-8"))
   scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
   for scope in scopes:
      for node in scope.body:
         targets = node.targets if isinstance(node, ast.Assign) else [node.target] \
             if isinstance(node, ast.AnnAssign) else []
         for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
               out.append((node.lineno, target.id))
   return out


def name_literals(path: Path) -> list[tuple[int, str]]:
   """!The literal lists, tuples and sets of names (two or more string constants, nothing else) in a file's code
   (docstrings and f-strings are not lists).
   @param path  a .py file
   @return (line number, ast.unparse() text) per literal
   """
   out = []
   for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
      items = node.elts if isinstance(node, (ast.List, ast.Tuple, ast.Set)) else []
      strings = [e for e in items if isinstance(e, ast.Constant) and isinstance(e.value, str)]
      if len(strings) >= CLOSED_LIST_MIN and len(strings) == len(items):
         out.append((node.lineno, ast.unparse(node)))
   return out


class EngineListGuardTests(unittest.TestCase):
   """!No studio module redefines an engine list."""

   def test_no_copies(self) -> None:
      """!Every module of the package: none assigns an engine name.
      @return None
      """
      found = []
      for path in sorted(PACKAGE.rglob("*.py")):
         rel = path.relative_to(PACKAGE).as_posix()
         for n, name in assignments(path):
            if name in ENGINE_NAMES or rel in MODULE_NAMES.get(name, ()):
               found.append(f"{rel}:{n}: {name}")
      self.assertEqual(found, [], "engine lists copied into the studio (read them from the engine)")

   def test_content_builds_from_the_structure(self) -> None:
      """!The Content pages define presentation constants only (CONTENT_CONSTANTS), none of the former closed lists,
      and no literal list of names beyond CONTENT_LITERALS (A15).
      @return None
      """
      constants, literals = [], []
      for path in sorted(CONTENT.rglob("*.py")):
         rel = path.relative_to(CONTENT).as_posix()
         for n, name in content_constants(path):
            if name in RETIRED_CONTENT_NAMES or name not in CONTENT_CONSTANTS.get(rel, set()):
               constants.append(f"{rel}:{n}: {name}")
         for n, text in name_literals(path):
            if text not in CONTENT_LITERALS.get(rel, set()):
               literals.append(f"{rel}:{n}: {text}")
      self.assertEqual(constants, [], "a Content page constant that is not presentation: read the engine's export or "
                                      "the compiled data (or add a presentation constant to CONTENT_CONSTANTS)")
      self.assertEqual(literals, [], "a closed list in a Content page: build it from the compiled structure (or add a "
                                     "heading / widget key to CONTENT_LITERALS)")
      for rel, names in CONTENT_CONSTANTS.items():
         self.assertTrue((CONTENT / rel).is_file(), rel)
         self.assertFalse(names & set(RETIRED_CONTENT_NAMES), rel)

   def test_content_guard_sees_a_closed_list(self) -> None:
      """!The Content guard finds a new constant (module or class level, annotated or not) and a literal list of
      names, and not a list of one name or of values computed from the data.
      @return None
      """
      import tempfile
      with tempfile.TemporaryDirectory() as tmp:
         path = Path(tmp) / "page.py"
         path.write_text('CATEGORIES = ["physical", "special"]\n'
                         'class Page:\n'
                         '   TYPE_SLOTS: int = 3\n'
                         '   def fill(self, bc):\n'
                         '      flags = ("contact", "sound")\n'
                         '      one = ["selected"]\n'
                         '      names = [bc.TARGETS[0], bc.TARGETS[1]]\n', encoding="utf-8")
         self.assertEqual(content_constants(path), [(1, "CATEGORIES"), (3, "TYPE_SLOTS")])
         self.assertEqual(name_literals(path), [(1, "['physical', 'special']"), (5, "('contact', 'sound')")])

   def test_guard_sees_a_copy(self) -> None:
      """!The pattern finds the assignments it guards against (plain and annotated) and not comparisons.
      @return None
      """
      self.assertIsNotNone(ASSIGNMENT.match('TARGETS = ["selected"]'))
      self.assertIsNotNone(ASSIGNMENT.match("   AI_FLAGS: list[str] = []"))
      self.assertIsNone(ASSIGNMENT.match("TARGETS == other"))
      self.assertIsNone(ASSIGNMENT.match("x = TARGETS"))

   def test_reexports_read(self) -> None:
      """!The modules that read the effect handlers' re-exports take them from battle_compiler, and what they give is
      the engine's.
      @return None
      """
      for rel, parts in REEXPORTED.items():
         text = (PACKAGE / rel).read_text(encoding="utf-8")
         for part in parts:
            self.assertNotIn(f'tool("{part}")', text, rel)
      from capsule_studio.core import battle, codepage, holders, logic, maps, messages, pipelines
      from capsule_studio.core.structure import conditions, record
      bc = engine.tool("battle_compiler")
      self.assertEqual(pipelines.handler_owners(), bc.OWNER_SOURCES)
      self.assertEqual(logic.point_owner_lists(), bc.OWNER_KINDS)
      self.assertEqual(holders.handler_lists(), bc.OWNER_KINDS)
      self.assertEqual(battle.still_motions(), tuple(bc.STILL_MOTIONS))
      self.assertEqual(record.stat_input_roles(), dict(bc.STAT_INPUT_ROLES))
      self.assertEqual(codepage.battle_entry_texts()["presenters"], tuple(bc.PRESENTER_TEXTS))
      self.assertIs(messages._texts(), bc)
      self.assertEqual(maps.max_priority(), engine.tool("map_compiler").MAX_PRIORITY)
      self.assertEqual([conditions.list_key(k) for k in conditions.handler_kinds()],
                       [key for key in bc.OWNER_KINDS if key in [conditions.list_key(k) for k in conditions.kinds()]])

   def test_after_battle_exports_read(self) -> None:
      """!What the studio gives for the after-battle screens' exports is the engine's (the manifest handler lists, the
      phases' notes, the logic kinds, the unary operators, the owner texts key, the map limits and cell fields), and the
      damage trace takes the hit's type from move_type_of() without copying the compiled data.
      @return None
      """
      from capsule_studio.core import bench, expressions, holders, logic, maps
      from capsule_studio.core.structure import turn
      bc = engine.tool("battle_compiler")
      rc = engine.tool("ruleset_compiler")
      mc = engine.tool("map_compiler")
      self.assertEqual(holders.manifest_lists(), [k for k in bc.OWNER_KINDS if k in bc.MANIFEST_HANDLER_LISTS])
      self.assertIn("exactly once", turn.phase_note(bc.ONCE_PHASES[0]))
      self.assertIn("at most once", turn.phase_note(bc.AT_MOST_ONCE_PHASES[0]))
      self.assertEqual(logic.kind_lists(), bc.LOGIC_KINDS)
      self.assertEqual(expressions.unary_operators(), list(rc.UNARY_OPERATORS))
      # the one unary bit operator follows the binary bit operators and shifts
      unary_bits = expressions.bit_operators()[len(rc.BIT_OPS) + len(rc.SHIFT_OPS):]
      self.assertEqual(len(unary_bits), 1)
      self.assertIn(unary_bits[0], rc.UNARY_OPERATORS)
      self.assertEqual(bench.owner_texts_key(), engine.tool("bench_scenario").OWNER_TEXTS_KEY)
      self.assertEqual((maps.max_layers(), maps.max_metatiles(), maps.max_behaviors(), maps.max_border()),
                       (mc.MAX_LAYERS, mc.MAX_METATILES, mc.MAX_BEHAVIORS, mc.MAX_BORDER_SIZE))
      self.assertEqual(maps.cell_fields(), dict(mc.CELL_FIELDS))
      self.assertEqual(maps.behavior_mask(), mc.BEHAVIOR_MASK)
      text = (PACKAGE / "core/pipelines.py").read_text(encoding="utf-8")
      self.assertIn("move_type_of(", text)
      self.assertIn("move_type=typed", text)
      self.assertNotIn('"moves": moves', text)

   def test_internal_reads(self) -> None:
      """!A module reads a battlec part only as INTERNAL_READS lists, and only for names battle_compiler does not
      re-export (a new export fails here until the module switches to battle_compiler).
      @return None
      """
      found = {}
      for path in sorted(PACKAGE.rglob("*.py")):
         rel = path.relative_to(PACKAGE).as_posix()
         for m in BATTLEC_READ.finditer(path.read_text(encoding="utf-8")):
            found.setdefault(rel, set()).add(m.group("part"))
      self.assertEqual(found, {rel: {part} for rel, (part, _names) in INTERNAL_READS.items()})
      bc = engine.tool("battle_compiler")
      for rel, (part, names) in INTERNAL_READS.items():
         module = engine.tool(part)
         for name in names:
            self.assertTrue(hasattr(module, name), f"{rel}: {part}.{name}")
            self.assertFalse(hasattr(bc, name), f"{rel}: battle_compiler re-exports {name}: read it there")
         self.assertIn(names[0], (PACKAGE / rel).read_text(encoding="utf-8"), rel)

   def test_engine_has_them(self) -> None:
      """!The engine exports what the studio reads instead.
      @return None
      """
      bc = engine.tool("battle_compiler")
      for name in ("TARGETS", "AI_FLAGS", "BATTLER_SUBJECTS", "DECISIVE", "DRAWS_PER_KIND", "EACH_PHASES",
                   "LOGIC_KINDS", "DEFAULT_PASSIVE_SLOTS", "OPTIONAL_MESSAGES", "REGEN_RANGE", "MAX_FORMULAS",
                   "PRESENTER_TEXTS", "STILL_MOTIONS", "STAT_INPUT_ROLES", "MESSAGE_KEY", "RETIRED_MESSAGES",
                   # The after-battle screens
                   "OWNER_SOURCES", "OWNER_KINDS", "MANIFEST_HANDLER_LISTS", "ONCE_PHASES", "AT_MOST_ONCE_PHASES",
                   "record_inputs", "species_inputs", "SPECIES_FIELD_NAME", "move_type_of",
                   # The AI profiles
                   "AI_RULES", "AI_SWITCH_RULES", "AI_RULE_ARGS", "AI_SWITCH_ARGS", "MAX_AI_PROFILES", "MAX_AI_RULES",
                   "AI_DEFAULT_PROFILE", "compile_ai_profiles", "party_profile", "BOUND_TO", "MAX_BOUND",
                   "DELAYED_AT_USE", "DELAYED_HIT_FLAGS", "DELAYED_DEFAULT_FLAGS", "DEFAULT_MISS_MESSAGE",
                   "DELAYED_MAX_ACCURACY", "compile_delayed_hits"):
         self.assertTrue(hasattr(bc, name), name)
      self.assertIn("save_resources", bc.AI_FLAGS)
      bs = engine.tool("bench_scenario")
      for name in ("TRACES", "CONTROLLERS", "PARTY_FLAGS", "ANSWER_KINDS", "STOP_KINDS", "RNG_NAME",
                   "RETIRED_POKE_KEYS", "OWNER_TEXTS_KEY"):
         self.assertTrue(hasattr(bs, name), name)
      self.assertTrue(hasattr(engine.tool("ruleset_compiler"), "UNARY_OPERATORS"))
      mc = engine.tool("map_compiler")
      for name in ("MAX_LAYERS", "MAX_METATILES", "MAX_BEHAVIORS", "MAX_BORDER_SIZE", "CELL_FIELDS", "BEHAVIOR_MASK",
                   "MAX_PRIORITY"):
         self.assertTrue(hasattr(mc, name), name)



class HeaderConstantTest(unittest.TestCase):
   """!header_constant() reads any C++ integer literal (a hex one used to read as 0)."""

   def test_literals(self) -> None:
      """!Hex, binary, octal, separated and suffixed literals give their values."""
      cases = {"0x10u": 16, "0X1F": 31, "0b101": 5, "010": 8, "1'000": 1000, "64": 64, "0": 0}
      for text, value in cases.items():
         m = re.match(engine._INT_LITERAL, text)
         self.assertIsNotNone(m, text)
         self.assertEqual(engine.cpp_int(m.group(1)), value, text)

   def test_engine_header(self) -> None:
      """!A constant of the engine's own headers (kBlendMax in video.h) reads as its value."""
      try:
         text = (engine.root() / "include" / "capsule" / "hal" / "video.h").read_text(encoding="utf-8")
      except (OSError, engine.EngineNotFound):
         self.skipTest("no engine checkout")
      m = re.search(r"\bkBlendMax\s*=\s*" + engine._INT_LITERAL, text)
      if m is None:
         self.skipTest("kBlendMax not in video.h")
      self.assertGreater(engine.header_constant("capsule/hal/video.h", "kBlendMax", 0), 0)


if __name__ == "__main__":
   unittest.main()
