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
cp "$ROOT"/browser-extension/lib/{ort.wasm.min.js,ort-wasm-simd-threaded.mjs,ort-wasm-simd-threaded.wasm} "$OUT/lib/"
cp "$ROOT/browser-extension/src/yunet.js" "$OUT/lib/"
cp "$ROOT/browser-extension/models/yunet.onnx" "$OUT/models/"
cp "$ROOT/assets/overlay.png" "$OUT/assets/"
# Manifest-link weghalen (geen PWA binnen de app)
sed -i '/rel="manifest"/d' "$OUT/index.html"
# Controle: geen verwijzingen meer naar de bovenliggende map
if grep -n '\.\./' "$OUT"/*.html "$OUT"/*.js; then echo "Fout: nog ../-paden in www" >&2; exit 1; fi
echo "www klaar in $OUT"
