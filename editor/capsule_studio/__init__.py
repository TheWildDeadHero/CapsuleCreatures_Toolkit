"""!CapsuleCreatures Studio: editors for CapsuleCreatures projects.

  - capsule_studio.core: editing logic, no user interface (scripts, CI, Docker)
  - capsule_studio.cli:  command line over core (`capsule-studio ...`)
  - capsule_studio.ui:   PySide6 panels and the application shell
  - capsule_studio.plugins: the extension host (D-10): plugin loading and
    the points extensions register at
  - capsule_studio.extensions: extensions shipped with the studio
"""

## Package version.
__version__ = "0.1.0"
## Calendar version of this release (D-10: YYYY.MM.DD.MMMM, UTC, zero-padded; stamped when a
## release is cut). Plugins' "requires" compare against it.
__calver__ = "2026.10.17.1315"
