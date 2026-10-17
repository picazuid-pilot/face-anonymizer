#!/usr/bin/env bash
# Face Anonymizer – verwijderen. Systeempakketten (Python, v4l2loopback) blijven staan.
set -euo pipefail

APP_ID="face-anonymizer"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
DESKTOP_DIR="$(command -v xdg-user-dir >/dev/null && xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

echo "Face Anonymizer, Foto Anonymizer en Face Anonymizer for AV verwijderen…"
for id in "$APP_ID" foto-anonymizer face-anonymizer-av; do
  rm -f "$HOME/.local/bin/$id"
  rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/$id.desktop"
  rm -f "$DESKTOP_DIR/$id.desktop"
done
rm -rf "$DATA_DIR"
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/$APP_ID"
echo "  ✓ App, starter en snelkoppelingen verwijderd"

if [ -f "/etc/modprobe.d/$APP_ID.conf" ] || [ -f "/etc/modules-load.d/$APP_ID.conf" ]; then
  read -r -p "  Ook de automatische virtuele camera bij het opstarten uitzetten? [j/N] " reply || true
  if [[ "$reply" =~ ^[JjYy] ]]; then
    sudo rm -f "/etc/modprobe.d/$APP_ID.conf" "/etc/modules-load.d/$APP_ID.conf"
    echo "  ✓ Uitgezet (na een herstart is de virtuele camera weg)"
  fi
fi
echo "Klaar. Het gezichtsmodel in ~/.cache/yunet kun je met de hand verwijderen."
