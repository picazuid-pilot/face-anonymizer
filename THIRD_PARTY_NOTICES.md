# Onderdelen van derden

Face Anonymizer zelf valt onder de [GPL-3.0-or-later](LICENSE). Deze onderdelen van anderen worden meegeleverd of gebruikt; hun licenties zijn verenigbaar met de GPL-3.0.

| Onderdeel | Waar | Licentie | Bron |
|---|---|---|---|
| YuNet-gezichtsmodel (`face_detection_yunet_2023mar`) | `browser-extension/models/yunet.onnx` (omgezet met [`tools/make_dynamic_yunet.py`](tools/make_dynamic_yunet.py)), desktop-apps downloaden het origineel | MIT | [opencv/opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| ONNX Runtime Web 1.30.0 | `browser-extension/lib/` (webtool en extensie); de Android-app haalt hetzelfde pakket van npm | MIT | [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime) |
| Capacitor 7 | Android-app | MIT | [ionic-team/capacitor](https://github.com/ionic-team/capacitor) |
| AndroidX-bibliotheken | Android-app | Apache-2.0 | [developer.android.com/jetpack/androidx](https://developer.android.com/jetpack/androidx) |
| OpenCV (`opencv-python`) | desktop-apps | Apache-2.0 | [opencv/opencv-python](https://github.com/opencv/opencv-python) |
| NumPy, SciPy, Pillow, PyAV, pyvirtualcam | desktop-apps | BSD / HPND / BSD / GPL-2.0 | PyPI |
| Inter (lettertype in `assets/overlay.png`) | standaard-overlay | OFL-1.1 | [rsms/inter](https://github.com/rsms/inter) |

## Controlesommen

| Bestand | SHA-256 |
|---|---|
| origineel `face_detection_yunet_2023mar.onnx` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `browser-extension/models/yunet.onnx` | `57acd73224bfbe2a2d6d28431da2e7c5b1d643717407e7cf2cae3d4a07ce2c14` |
| `ort-wasm-simd-threaded.wasm` (gelijk aan npm `onnxruntime-web@1.30.0`) | `3398c10d07d229bd91b364548e130e0e51a8e5704b88c7c083ebbeb78842dee2` |
| `ort-wasm-simd-threaded.mjs` | `e13f7f94fc51b4ca72b12faeb1ee95f4ace6dfbc8939bc718aabdc0a27c4299b` |
| `ort.wasm.min.js` | `faece07e84faa9001f5104bbe4e5c70861d06cb2376a0dea1fa0ad33a67adc81` |
