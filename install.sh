#!/usr/bin/env bash
# Face Anonymizer – installatie voor Linux (getest op Ubuntu 24.04)
#
# Wat dit script doet:
#   1. Systeempakketten installeren (Python, Tk, virtuele-camera-driver)
#   2. De app kopiëren naar ~/.local/share/face-anonymizer met een eigen Python-omgeving
#   3. Het gezichtsmodel vooraf downloaden
#   4. De virtuele camera instellen zodat hij ook na een herstart beschikbaar is
#   5. Een snelkoppeling maken in het app-menu en op het bureaublad
#
# Installeert drie apps: Face Anonymizer (live webcam), Foto Anonymizer (mappen met foto's)
# en Face Anonymizer for AV (video's, beeldreeksen en foto's).
#
# Gebruik:   ./install.sh            (vraagt om bevestiging waar nodig)
#            ./install.sh --yes      (alles automatisch)
#            ./install.sh --no-virtualcam   (zonder virtuele camera)
# Bijwerken: git pull && ./install.sh
# Verwijderen: ./uninstall.sh

set -euo pipefail

APP_ID="face-anonymizer"
APP_NAME="Face Anonymizer"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
BIN_DIR="$HOME/.local/bin"
CAM_LABEL="Face Anonymizer"
MODPROBE_CONF="/etc/modprobe.d/$APP_ID.conf"
MODULES_CONF="/etc/modules-load.d/$APP_ID.conf"

ASSUME_YES=0
WITH_VCAM=1
ALLOW_ROOT=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --no-virtualcam) WITH_VCAM=0 ;;
    --allow-root) ALLOW_ROOT=1 ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Onbekende optie: $arg (zie --help)"; exit 1 ;;
  esac
done

# ------------------------------------------------------------------ helpers
if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'; else B=; G=; Y=; R=; N=; fi
step() { echo; echo "${B}▶ $*${N}"; }
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
die()  { echo "  ${R}✗ $*${N}" >&2; exit 1; }
ask()  {  # ask "vraag" -> 0 bij ja (standaard ja)
  [ "$ASSUME_YES" = 1 ] && return 0
  local reply; read -r -p "  $1 [J/n] " reply || true
  [[ -z "$reply" || "$reply" =~ ^[JjYy] ]]
}
SUDO=""
need_sudo() {
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; return; fi
  command -v sudo >/dev/null || die "sudo is nodig om systeempakketten te installeren."
  SUDO="sudo"
}

if [ "$(id -u)" -eq 0 ] && [ "$ALLOW_ROOT" = 0 ]; then
  die "Start dit script als je eigen gebruiker, niet met sudo. Het vraagt zelf om je wachtwoord waar nodig."
fi
[ -f "$SRC_DIR/face_anonymizer.py" ] || die "Start install.sh vanuit de map van de repository."

echo "${B}$APP_NAME – installatie${N}"
echo "Bron:        $SRC_DIR"
echo "Installatie: $DATA_DIR"

# ---------------------------------------------------- 1. systeempakketten
step "Systeempakketten"
PKG=""
if command -v apt-get >/dev/null; then PKG=apt
elif command -v dnf >/dev/null; then PKG=dnf
elif command -v pacman >/dev/null; then PKG=pacman
fi

pkgs_base=(); pkgs_vcam=()
case "$PKG" in
  apt)    pkgs_base=(python3 python3-venv python3-tk python3-pip libnotify-bin zenity)
          pkgs_vcam=(v4l2loopback-dkms v4l-utils "linux-headers-$(uname -r)") ;;
  dnf)    pkgs_base=(python3 python3-tkinter python3-pip libnotify zenity)
          pkgs_vcam=(v4l2loopback v4l-utils) ;;  # Fedora: via RPM Fusion
  pacman) pkgs_base=(python tk python-pip libnotify zenity)
          pkgs_vcam=(v4l2loopback-dkms v4l-utils linux-headers) ;;
  *)      warn "Onbekende pakketbeheerder. Zorg zelf voor Python 3, venv en Tk." ;;
esac

install_pkgs() {
  case "$PKG" in
    apt)    $SUDO apt-get update -qq && $SUDO apt-get install -y -qq "$@" ;;
    dnf)    $SUDO dnf install -y -q "$@" ;;
    pacman) $SUDO pacman -S --needed --noconfirm "$@" ;;
  esac
}

if [ -n "$PKG" ]; then
  need_sudo
  echo "  Installeren: ${pkgs_base[*]}"
  install_pkgs "${pkgs_base[@]}" >/dev/null || die "Installeren van systeempakketten mislukt."
  ok "Python en Tk geïnstalleerd"
fi
# Een Python zoeken met Tk (bij meerdere geïnstalleerde versies is 'python3' niet altijd de juiste)
PY=""
for cand in /usr/bin/python3 python3 python3.13 python3.12 python3.11 python3.10 python3.9; do
  if command -v "$cand" >/dev/null &&
     "$cand" -c 'import sys, tkinter, venv; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY="$(command -v "$cand")"; break
  fi
done
[ -n "$PY" ] || die "Geen Python 3.9+ met Tk (tkinter) en venv gevonden."
ok "Python $("$PY" -c 'import platform; print(platform.python_version())') ($PY)"

# ------------------------------------------------- 2. app + Python-omgeving
step "App installeren"
mkdir -p "$DATA_DIR" "$BIN_DIR"
# Alleen wat de app nodig heeft; eigen instellingen in $DATA_DIR blijven staan
# install -m 644: werkt ook als bronbestanden of een eerdere installatie alleen-lezen zijn
install -m 644 "$SRC_DIR/face_anonymizer.py" "$SRC_DIR/photo_anonymizer.py" "$SRC_DIR/face_core.py" \
  "$SRC_DIR/av_anonymizer.py" "$SRC_DIR/av_core.py" "$SRC_DIR/requirements.txt" "$DATA_DIR/"
install -d "$DATA_DIR/assets"
install -m 644 "$SRC_DIR/assets/"*.png "$DATA_DIR/assets/"
if [ -d "$SRC_DIR/browser-extension" ]; then
  rm -rf "$DATA_DIR/browser-extension"
  cp -r "$SRC_DIR/browser-extension" "$DATA_DIR/browser-extension"
  rm -rf "$DATA_DIR/browser-extension/test"
  chmod -R u+rwX,go+rX "$DATA_DIR/browser-extension"
fi
if [ -d "$SRC_DIR/web" ] && [ -d "$SRC_DIR/browser-extension" ]; then
  bash "$SRC_DIR/web/build.sh" "$DATA_DIR/web" >/dev/null && chmod -R u+rwX,go+rX "$DATA_DIR/web"
fi
ok "Bestanden gekopieerd"

if [ -x "$DATA_DIR/venv/bin/python" ] && ! "$DATA_DIR/venv/bin/python" -c 'import tkinter' 2>/dev/null; then
  rm -rf "$DATA_DIR/venv"   # oude omgeving zonder Tk: opnieuw opbouwen
fi
if [ ! -x "$DATA_DIR/venv/bin/python" ]; then
  "$PY" -m venv "$DATA_DIR/venv" || die "Python-omgeving maken mislukt (is python3-venv geïnstalleerd?)."
fi
"$DATA_DIR/venv/bin/python" -m pip install -q --upgrade pip >/dev/null
echo "  Python-pakketten installeren (eerste keer duurt dit even)…"
"$DATA_DIR/venv/bin/python" -m pip install -q -r "$DATA_DIR/requirements.txt" \
  || die "Python-pakketten installeren mislukt. Controleer je internetverbinding."
ok "Python-omgeving klaar"
if "$DATA_DIR/venv/bin/python" -m pip install -q pillow-heif >/dev/null 2>&1; then
  ok "iPhone-foto's (HEIC) ondersteund"
else
  warn "HEIC-ondersteuning niet beschikbaar; iPhone-foto's eerst als JPG exporteren."
fi

# ------------------------------------------------------------- 3. model
step "Gezichtsmodel"
if (cd "$DATA_DIR" && "$DATA_DIR/venv/bin/python" - <<'PY'
import face_core
face_core.create_detector()
PY
) >/dev/null 2>&1; then
  ok "YuNet-model gedownload"
else
  warn "Model kon nu niet gedownload worden; de app probeert het bij de eerste start opnieuw."
fi

# ------------------------------------------------- 4. virtuele camera
step "Virtuele camera (v4l2loopback)"
VCAM_STATUS="niet ingesteld"
if [ "$WITH_VCAM" = 0 ]; then
  warn "Overgeslagen (--no-virtualcam)"
elif [ "$PKG" != apt ] && [ "$PKG" != pacman ] && [ "$PKG" != dnf ]; then
  warn "Installeer v4l2loopback zelf om de virtuele camera te gebruiken."
elif ask "Virtuele camera installeren en bij het opstarten automatisch laden?"; then
  need_sudo
  if ! modinfo v4l2loopback >/dev/null 2>&1; then
    echo "  Driver installeren en bouwen (kan een paar minuten duren)…"
    # Uitvoer zichtbaar laten: bij Secure Boot vraagt Ubuntu hier om een wachtwoord
    install_pkgs "${pkgs_vcam[@]}" || warn "Installeren van de driver gaf een fout."
  fi
  if modinfo v4l2loopback >/dev/null 2>&1; then
    ok "Driver aanwezig"
    # exclusive_caps=1 is nodig zodat Chrome/Meet de camera herkent
    echo "options v4l2loopback devices=1 video_nr=10 exclusive_caps=1 card_label=\"$CAM_LABEL\"" \
      | $SUDO tee "$MODPROBE_CONF" >/dev/null
    echo "v4l2loopback" | $SUDO tee "$MODULES_CONF" >/dev/null
    ok "Wordt automatisch geladen bij het opstarten"
    if lsmod | grep -q '^v4l2loopback'; then
      ok "Driver is al geladen"
      VCAM_STATUS="klaar"
    elif $SUDO modprobe v4l2loopback 2>/dev/null; then
      ok "Virtuele camera nu actief"
      VCAM_STATUS="klaar"
    else
      VCAM_STATUS="na herstart"
      if command -v mokutil >/dev/null && mokutil --sb-state 2>/dev/null | grep -qi enabled; then
        warn "Secure Boot staat aan: de driver moet eenmalig goedgekeurd worden."
        MOK_DER=/var/lib/shim-signed/mok/MOK.der
        if [ -f "$MOK_DER" ] && ! mokutil --test-key "$MOK_DER" 2>/dev/null | grep -qi "already enrolled"; then
          # Een eventueel eerder (onbekend) wachtwoord vervangen door een dat je nu zelf kiest.
          $SUDO mokutil --revoke-import >/dev/null 2>&1 || true
          echo "  Kies nu een eenmalig wachtwoord (bijv. 12345678). Je hebt het zo meteen één keer nodig na de herstart."
          if $SUDO mokutil --import "$MOK_DER"; then
            ok "Goedkeuring klaargezet"
          else
            warn "Klaarzetten mislukt; voer later uit: sudo mokutil --import $MOK_DER"
          fi
        fi
        warn "Herstart nu. Druk in het blauwe scherm 'Perform MOK management' direct op een toets"
        warn "(het verdwijnt na 10 seconden) en kies: Enroll MOK → Continue → Yes → wachtwoord → Reboot."
      else
        warn "Driver kon nu niet geladen worden; probeer het na een herstart."
      fi
    fi
  else
    warn "v4l2loopback is niet beschikbaar voor deze kernel ($(uname -r))."
    warn "De app werkt wel, maar zonder virtuele camera (alleen de preview)."
  fi
else
  warn "Overgeslagen"
fi

# ----------------------------------------------------------- 5. starters
step "Snelkoppelingen"
DESKTOP_DIR="$(command -v xdg-user-dir >/dev/null && xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
WANT_DESKTOP=0
if [ -d "$DESKTOP_DIR" ] && [ "$DESKTOP_DIR" != "$HOME" ] && ask "Ook snelkoppelingen op het bureaublad zetten?"; then
  WANT_DESKTOP=1
fi

# make_app ID "Naam" script.py icoon.png WMClass "Omschrijving" "Categorieën" "Trefwoorden" virtuele-camera(0/1)
make_app() {
  local id="$1" name="$2" script="$3" icon="$4" wmclass="$5" comment="$6" cats="$7" keys="$8" vcam="$9"
  local launcher="$BIN_DIR/$id"
  local desktop="${XDG_DATA_HOME:-$HOME/.local/share}/applications/$id.desktop"
  local vcam_block=""
  if [ "$vcam" = 1 ]; then
    # Virtuele camera laden als die er nog niet is (bijv. vlak na de installatie).
    # pkexec toont een gewoon wachtwoordvenster, net als OBS doet.
    vcam_block="if modinfo v4l2loopback >/dev/null 2>&1 && ! lsmod | grep -q '^v4l2loopback'; then
  command -v pkexec >/dev/null && pkexec modprobe v4l2loopback devices=1 video_nr=10 exclusive_caps=1 card_label=\"$CAM_LABEL\" || true
fi"
  fi
  cat > "$launcher" <<LAUNCH
#!/usr/bin/env bash
# Starter voor $name (gemaakt door install.sh)
APP_DIR="$DATA_DIR"
LOG_DIR="\${XDG_CACHE_HOME:-\$HOME/.cache}/$APP_ID"
LOG="\$LOG_DIR/$id.log"
mkdir -p "\$LOG_DIR"

notify() { command -v notify-send >/dev/null && notify-send -i "\$APP_DIR/assets/$icon" "$name" "\$1"; }

# Maar één keer tegelijk starten
exec 9>"\$LOG_DIR/$id.lock"
if ! flock -n 9; then
  notify "$name draait al."
  exit 0
fi

$vcam_block

cd "\$APP_DIR" || exit 1
{ echo "=== \$(date) ==="; } >> "\$LOG"
"\$APP_DIR/venv/bin/python" "\$APP_DIR/$script" >> "\$LOG" 2>&1
status=\$?
# Stopsignaal (uitloggen, afsluiten) is geen fout; alleen echte fouten melden
if [ \$status -ne 0 ] && [ \$status -lt 128 ]; then
  msg="$name is gestopt met een fout.\n\nLaatste regels uit \$LOG:\n\n\$(tail -n 15 "\$LOG")"
  if command -v zenity >/dev/null; then
    zenity --error --title="$name" --width=560 --text="\$msg" 2>/dev/null
  else
    notify "Gestopt met een fout. Zie \$LOG"
  fi
fi
exit \$status
LAUNCH
  chmod +x "$launcher"

  mkdir -p "$(dirname "$desktop")"
  cat > "$desktop" <<DESK
[Desktop Entry]
Type=Application
Name=$name
GenericName=Gezichten anonimiseren
Comment=$comment
Exec=$launcher
Icon=$DATA_DIR/assets/$icon
Terminal=false
Categories=$cats
Keywords=$keys
StartupNotify=true
StartupWMClass=$wmclass
DESK
  chmod +x "$desktop"
  if [ "$WANT_DESKTOP" = 1 ]; then
    cp "$desktop" "$DESKTOP_DIR/$id.desktop"
    chmod +x "$DESKTOP_DIR/$id.desktop"
    # GNOME: als vertrouwd markeren, anders moet je eerst "Starten toestaan" kiezen
    gio set "$DESKTOP_DIR/$id.desktop" metadata::trusted true 2>/dev/null || true
  fi
  if [ "$WANT_DESKTOP" = 1 ]; then ok "$name: in het app-menu en op het bureaublad"; else ok "$name: in het app-menu"; fi
}

make_app "$APP_ID" "$APP_NAME" face_anonymizer.py icon.png Face-anonymizer \
  "Anonimiseer gezichten live voor OBS, Zoom, Meet en livestreams" \
  "AudioVideo;Video;" "webcam;camera;privacy;anoniem;obs;stream;" 1
make_app "foto-anonymizer" "Foto Anonymizer" photo_anonymizer.py photo_icon.png Foto-anonymizer \
  "Maak gezichten op een map vol foto's onherkenbaar" \
  "Graphics;Photography;" "foto;photo;privacy;anoniem;gezicht;blur;" 0
make_app "face-anonymizer-av" "Face Anonymizer for AV" av_anonymizer.py av_icon.png Face-anonymizer-av \
  "Anonimiseer gezichten in video's, beeldreeksen en foto's (met geluid, zonder metadata)" \
  "AudioVideo;Video;" "video;film;foto;reeks;privacy;anoniem;gezicht;blur;" 0
command -v update-desktop-database >/dev/null && \
  update-desktop-database -q "${XDG_DATA_HOME:-$HOME/.local/share}/applications" 2>/dev/null || true

# ------------------------------------------------------------- klaar
echo
echo "${G}${B}Klaar!${N}"
echo "  • In het app-menu: ${B}$APP_NAME${N} (live), ${B}Foto Anonymizer${N} (mappen met foto's)"
echo "    en ${B}Face Anonymizer for AV${N} (video's, beeldreeksen en foto's)."
case "$VCAM_STATUS" in
  klaar)         echo "  • Virtuele camera: ${G}klaar${N}. Kies \"$CAM_LABEL\" als camera in OBS, Zoom, Meet enz." ;;
  "na herstart") echo "  • Virtuele camera: ${Y}beschikbaar na een herstart${N}." ;;
  *)             echo "  • Virtuele camera: niet ingesteld." ;;
esac
if [ -d "$DATA_DIR/browser-extension" ]; then
  echo "  • Browserextensie: laad in chrome://extensions (Ontwikkelaarsmodus → Uitgepakte extensie laden) de map"
  echo "      $DATA_DIR/browser-extension"
  echo "    Na een update via install.sh hoef je daar alleen op ↻ te klikken."
fi
if [ -f "$DATA_DIR/web/index.html" ]; then
  echo "  • Webtool (zelfde functie als Foto Anonymizer, in de browser): $DATA_DIR/web"
  echo "    Zet die map op een website, of zie de README voor GitHub Pages."
fi
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "  • Tip: na opnieuw inloggen kun je ook '$APP_ID' typen in een terminal." ;; esac
