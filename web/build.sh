#!/usr/bin/env bash
# Bouwt de webtool en de camera-app tot één map die je op elke statische hosting kunt zetten
# (GitHub Pages, InfinityFree, een USB-stick…). Gebruik: web/build.sh [doelmap]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist/web}"
rm -rf "$OUT"
mkdir -p "$OUT/lib" "$OUT/models" "$OUT/assets"
cp "$ROOT"/web/{index.html,app.css,app.js,worker.js,zip.js} "$OUT/"
# ONNX Runtime, model en decodering delen we met de browserextensie (één bron)
cp "$ROOT"/browser-extension/lib/{ort.wasm.min.js,ort-wasm-simd-threaded.mjs,ort-wasm-simd-threaded.wasm} "$OUT/lib/"
cp "$ROOT/browser-extension/src/yunet.js" "$OUT/lib/"
cp "$ROOT/browser-extension/models/yunet.onnx" "$OUT/models/"
cp "$ROOT/assets/overlay.png" "$OUT/assets/overlay.png"
cp "$ROOT/assets/photo_icon.png" "$OUT/assets/icon.png"
# Camera-app voor telefoons (PWA) in camera/, deelt lib/, models/ en assets/
mkdir -p "$OUT/camera/icons"
cp "$ROOT"/camera/{index.html,camera.css,camera.js,tracker.js,detector-worker.js,manifest.webmanifest} "$OUT/camera/"
cp "$ROOT"/camera/icons/*.png "$OUT/camera/icons/"
# Cacheversie = inhoud van alle bestanden: telefoons halen alleen bij een echte wijziging opnieuw op
VERSION="$(cd "$OUT" && find camera lib models assets -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12)"
sed "s/const VERSION = 'dev';/const VERSION = '$VERSION';/" "$ROOT/camera/sw.js" > "$OUT/camera/sw.js"
# Juiste MIME-type voor .wasm/.mjs op Apache-hosting (zoals InfinityFree)
cat > "$OUT/.htaccess" <<'HT'
AddType application/wasm .wasm
AddType text/javascript .mjs
AddType application/manifest+json .webmanifest
<IfModule mod_headers.c>
  Header set Referrer-Policy "no-referrer"
  Header set X-Content-Type-Options "nosniff"
</IfModule>
HT
echo "Webtool gebouwd in $OUT"
