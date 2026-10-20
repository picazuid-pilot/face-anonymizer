# FA Camera in F-Droid

Wat er al klaarstaat, en wat er nog moet gebeuren om FA Camera in [F-Droid](https://f-droid.org) te krijgen.

## Klaar

- **Licentie:** GPL-3.0-or-later ([LICENSE](../LICENSE)); onderdelen van derden en hun licenties in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
- **Geen trackers, advertenties of Google-diensten**; de app maakt geen verbinding met internet.
- **Alles uit broncode te bouwen:**
  - ONNX Runtime komt van npm (`onnxruntime-web@1.30.0`, vastgelegd in `package-lock.json`), niet uit de repo.
  - Het gezichtsmodel `browser-extension/models/yunet.onnx` is byte-voor-byte na te maken uit het officiële OpenCV-model met [`tools/make_dynamic_yunet.py`](../tools/make_dynamic_yunet.py). Controlesommen staan in THIRD_PARTY_NOTICES.md.
  - Zonder test-sleutel bouwt Gradle een niet-ondertekende APK, die F-Droid zelf ondertekent.
- **Catalogusgegevens:** beschrijvingen, icoon en schermafbeeldingen (Nederlands en Engels) in [`fastlane/metadata/android/`](../fastlane/metadata/android/).
- **Versie:** `versionCode 100`, `versionName "1.0.0"` in `android/app/build.gradle`. Testbuilds van GitHub Actions krijgen een hoger nummer met `-ci.N` erachter.
- **Concept-bouwrecept:** [`fdroid/io.github.picazuidpilot.facecamera.yml`](fdroid/io.github.picazuidpilot.facecamera.yml).

## Nog te doen

1. **Versie 1.0.0 vastleggen op GitHub:** *Releases → Draft a new release → Choose a tag:* `v1.0.0` (nieuw, op `main`) → *Publish release*. F-Droid bouwt vanaf zo'n label.
2. **Aanvragen bij F-Droid**, op één van deze manieren:
   - **Eenvoudig:** maak een *Request For Packaging* (RFP) op <https://gitlab.com/fdroid/rfp/-/issues> met de link naar deze repo en vermeld dat het bouwrecept in `android-app/fdroid/` staat. Een vrijwilliger pakt het op (kan even duren).
   - **Sneller:** fork <https://gitlab.com/fdroid/fdroiddata>, zet het recept in `metadata/` en open een *merge request*. De CI van F-Droid controleert dan direct of de build lukt.
3. **Vragen van de reviewer beantwoorden.** Te verwachten punten:
   - *Node.js-versie:* Capacitor 7 vraagt Node 20 of nieuwer. De bouwserver van F-Droid heeft misschien een oudere versie; de reviewer weet hoe dat in het recept op te lossen is.
   - *ONNX Runtime als WebAssembly-binary van npm:* volgens het [inclusiebeleid](https://f-droid.org/docs/Inclusion_Policy/) kan een vrij, kant-en-klaar pakket van npm acceptabel zijn als zelf bouwen niet haalbaar is. Vraagt de reviewer toch om het uit broncode te bouwen, dan moet ONNX Runtime met Emscripten gebouwd worden in het recept.
   - *INTERNET-toestemming:* nodig voor de interne webserver van Capacitor; de pagina zelf mag nergens verbinding mee maken (Content Security Policy).

## Volgende versies

Verhoog in `android/app/build.gradle` `versionCode` (bijv. 101) en `versionName` (bijv. `"1.0.1"`), zet een changelog in `fastlane/metadata/android/*/changelogs/101.txt` en maak een release `v1.0.1`. F-Droid ziet het nieuwe label en bouwt de update zelf.
