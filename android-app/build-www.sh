#!/usr/bin/env bash
# Zet de camera-app (camera/) klaar als www/ voor de Android-app.
# In de app staat alles in één map, dus ../lib, ../models en ../assets worden lib, models en assets.
# De service worker en het webmanifest zijn in de app niet nodig.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
OUT="$HERE/www"
rm -rf "$OUT"
mkdir -p "$OUT/lib" "$OUT/models" "$OUT/assets" "$OUT/icons"
for f in index.html camera.css camera.js tracker.js detector-worker.js; do
  sed -e 's#\.\./lib/#lib/#g' -e 's#\.\./models/#models/#g' -e 's#\.\./assets/#assets/#g' \
    "$ROOT/camera/$f" > "$OUT/$f"
done
cp "$ROOT"/camera/icons/*.png "$OUT/icons/"
# ONNX Runtime komt van npm (versie vast in package-lock.json), niet uit de repo:
# zo is de herkomst controleerbaar (F-Droid). Eerst `npm ci` draaien.
ORT="$HERE/node_modules/onnxruntime-web/dist"
if [ ! -f "$ORT/ort-wasm-simd-threaded.wasm" ]; then
  echo "Fout: onnxruntime-web ontbreekt. Voer eerst 'npm ci' uit in android-app/." >&2
  exit 1
fi
cp "$ORT"/{ort.wasm.min.js,ort-wasm-simd-threaded.mjs,ort-wasm-simd-threaded.wasm} "$OUT/lib/"
cp "$ROOT/browser-extension/src/yunet.js" "$OUT/lib/"
cp "$ROOT/browser-extension/models/yunet.onnx" "$OUT/models/"
cp "$ROOT/assets/overlay.png" "$OUT/assets/"
# Manifest-link weghalen (geen PWA binnen de app)
sed -i '/rel="manifest"/d' "$OUT/index.html"
# Controle: geen verwijzingen meer naar de bovenliggende map
if grep -n '\.\./' "$OUT"/*.html "$OUT"/*.js; then echo "Fout: nog ../-paden in www" >&2; exit 1; fi
echo "www klaar in $OUT"
