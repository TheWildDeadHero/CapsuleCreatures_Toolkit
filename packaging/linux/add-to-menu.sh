#!/bin/sh
# Adds CapsuleCreatures Studio to your desktop's application menu (for you only, no administrator rights): writes
# a desktop entry that starts the `studio` program in this folder, with this folder's icon. Run it again after
# moving the folder. To remove the entry, delete the file it names.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
entry="$apps/capsule-studio.desktop"

mkdir -p "$apps"
cat > "$entry" <<EOF
[Desktop Entry]
Type=Application
Name=CapsuleCreatures Studio
Comment=Editors for CapsuleCreatures games
Exec="$here/studio" %f
Icon=$here/capsule-studio.png
Terminal=false
Categories=Development;Game;
EOF

# Menus pick the entry up by themselves; this only speeds it up where the tool exists.
if command -v update-desktop-database > /dev/null 2>&1; then
   update-desktop-database "$apps" > /dev/null 2>&1 || true
fi
echo "Added: $entry"
