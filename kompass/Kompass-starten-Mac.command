#!/bin/bash
# Kompass fuer macOS einrichten:
#  1. App "Kompass" auf dem Schreibtisch anlegen (oeffnet Kompass als App-Fenster in Brave)
#  2. Kompass als Website in Brave oeffnen
#  3. Kompass als App-Fenster starten

DIR="$(cd "$(dirname "$0")" && pwd)"
INDEX="$DIR/index.html"
URL="file://${INDEX// /%20}"
BRAVE="Brave Browser"
TARGET="$HOME/Desktop/Kompass.app"

echo ""
echo "  Kompass wird eingerichtet ..."

if ! open -Ra "$BRAVE" 2>/dev/null; then
  echo "  Brave wurde nicht gefunden. Kompass oeffnet sich im Standardbrowser."
  open "$INDEX"
  exit 0
fi

# Schreibtisch-App bauen
rm -rf "$TARGET"
osacompile -o "$TARGET" -e "do shell script \"open -na '$BRAVE' --args --app='$URL'\"" >/dev/null

# Eigenes Symbol setzen
ICONSET="$(mktemp -d)/kompass.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$DIR/icons/icon-512.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1
  d=$((s * 2))
  sips -z $d $d "$DIR/icons/icon-512.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
done
iconutil -c icns "$ICONSET" -o "$TARGET/Contents/Resources/applet.icns" >/dev/null 2>&1 && touch "$TARGET"
echo "  [ok] App \"Kompass\" auf dem Schreibtisch angelegt"

open -a "$BRAVE" "$URL"
echo "  [ok] Website in Brave geoeffnet"
sleep 1
open -na "$BRAVE" --args --app="$URL"
echo "  [ok] Kompass-App gestartet"
echo ""
echo "  Fertig. Ab jetzt reicht ein Doppelklick auf \"Kompass\" auf dem Schreibtisch."
