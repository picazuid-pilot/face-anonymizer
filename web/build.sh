#!/usr/bin/env bash
# Bouwt de webtool tot één map die je op elke statische hosting kunt zetten
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
# Juiste MIME-type voor .wasm/.mjs op Apache-hosting (zoals InfinityFree)
cat > "$OUT/.htaccess" <<'HT'
AddType application/wasm .wasm
AddType text/javascript .mjs
<IfModule mod_headers.c>
  Header set Referrer-Policy "no-referrer"
  Header set X-Content-Type-Options "nosniff"
</IfModule>
HT
echo "Webtool gebouwd in $OUT"
