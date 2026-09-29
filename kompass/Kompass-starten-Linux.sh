#!/usr/bin/env bash
# Kompass fuer Linux einrichten:
#  1. Starter "Kompass" auf dem Desktop und im Anwendungsmenue anlegen
#  2. Kompass als Website in Brave oeffnen
#  3. Kompass als App-Fenster starten

DIR="$(cd "$(dirname "$0")" && pwd)"
INDEX="$DIR/index.html"
URL="file://${INDEX// /%20}"

BRAVE=""
for c in brave-browser brave brave-browser-stable; do
  if command -v "$c" >/dev/null 2>&1; then BRAVE="$c"; break; fi
done
if [ -z "$BRAVE" ] && command -v flatpak >/dev/null 2>&1 && flatpak info com.brave.Browser >/dev/null 2>&1; then
  BRAVE="flatpak run com.brave.Browser"
fi

echo ""
echo "  Kompass wird eingerichtet ..."

if [ -z "$BRAVE" ]; then
  echo "  Brave wurde nicht gefunden. Kompass oeffnet sich im Standardbrowser."
  xdg-open "$INDEX" >/dev/null 2>&1 &
  exit 0
fi

DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR" "$APPS_DIR"

ENTRY="[Desktop Entry]
Type=Application
Name=Kompass
Comment=Tagesplaner: Aufgaben, Fokus-Timer, Gewohnheiten, Notizen
Exec=$BRAVE --app=\"${URL//\%/%%}\"
Icon=$DIR/icons/icon-512.png
Terminal=false
Categories=Office;Utility;"

for f in "$DESKTOP_DIR/kompass.desktop" "$APPS_DIR/kompass.desktop"; do
  printf '%s\n' "$ENTRY" > "$f"
  chmod +x "$f"
  gio set "$f" metadata::trusted true >/dev/null 2>&1 || true
done
echo "  [ok] Starter \"Kompass\" auf dem Desktop angelegt"

$BRAVE "$URL" >/dev/null 2>&1 &
echo "  [ok] Website in Brave geoeffnet"
sleep 1
$BRAVE --app="$URL" >/dev/null 2>&1 &
echo "  [ok] Kompass-App gestartet"
echo ""
echo "  Fertig. Ab jetzt reicht ein Doppelklick auf \"Kompass\" auf dem Desktop."
