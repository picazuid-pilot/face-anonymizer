# FA Camera voor Android (APK)

Dit is de [camera-app](../camera/) als echte Android-app. Hij doet hetzelfde als de web-app (filmen en fotograferen met gezichten al afgedekt), maar:

- foto's en video's komen **direct in je galerij**, in de map **FA Camera**;
- *Delen…* opent het gewone Android-deelmenu (WhatsApp, Signal, mail…);
- het scherm blijft aan tijdens het filmen;
- de terugknop sluit eerst een geopend paneel of stopt de opname.

Er zit geen internet in de app: het gezichtsmodel staat in de app zelf, en de pagina mag nergens verbinding mee maken.

## Installeren

1. Open op je telefoon: **https://github.com/picazuid-pilot/face-anonymizer/releases/download/android/fa-camera.apk**
2. Tik op het gedownloade bestand. Android vraagt of je browser apps mag installeren: sta dat toe (*Instellingen → Onbekende apps installeren*).
3. Open **FA Camera**, tik op *Camera starten* en sta camera en microfoon toe.

Nodig: Android 10 of nieuwer.

**Bijwerken:** download de APK opnieuw en installeer hem over de oude heen. Je instellingen blijven bewaard.

## Hoe de APK gemaakt wordt

GitHub bouwt de app zelf, met **GitHub Actions** ([.github/workflows/android.yml](../.github/workflows/android.yml)). Bij elke wijziging aan `camera/` of `android-app/` start GitHub een tijdelijke computer met de Android-bouwtools, die:

1. de camera-app klaarzet (`build-www.sh`: zelfde bestanden als de web-app);
2. die met [Capacitor](https://capacitorjs.com) in een Android-app verpakt;
3. de APK bouwt en ondertekent;
4. hem op de [Releases-pagina](https://github.com/picazuid-pilot/face-anonymizer/releases/tag/android) zet, altijd onder dezelfde link.

Je kunt een build ook met de hand starten: tabblad **Actions → Android-app bouwen → Run workflow**.

Zelf bouwen (Android Studio of de Android SDK nodig):

```bash
cd android-app
npm ci
npm run sync
cd android && ./gradlew assembleRelease
```

## Ondertekening

Elke Android-app moet ondertekend zijn, en een update moet met **dezelfde sleutel** ondertekend zijn als de geïnstalleerde versie.

- Standaard gebruikt de build `sideload.keystore` uit deze map. Die sleutel is **openbaar** (wachtwoord `facamera`) en alleen bedoeld om de app zelf te installeren en te testen.
- Ga je de app breder verspreiden of in de **Play Store** zetten, maak dan een eigen geheime sleutel en zet die in GitHub (*Settings → Secrets and variables → Actions*):

  ```bash
  keytool -genkeypair -keystore fa-camera.keystore -alias facamera -keyalg RSA -keysize 2048 -validity 10000
  base64 -w0 fa-camera.keystore   # deze uitvoer is ANDROID_KEYSTORE_BASE64
  ```

  | Secret | Waarde |
  |---|---|
  | `ANDROID_KEYSTORE_BASE64` | uitvoer van `base64 -w0` hierboven |
  | `ANDROID_KEYSTORE_PASSWORD` | wachtwoord van de keystore |
  | `ANDROID_KEY_ALIAS` | `facamera` |
  | `ANDROID_KEY_PASSWORD` | wachtwoord van de sleutel (vaak hetzelfde) |

  Bewaar `fa-camera.keystore` veilig en zet hem nooit in de repo. Na het wisselen van sleutel moet de app één keer verwijderd en opnieuw geïnstalleerd worden.

## Play Store

Kan later: een ontwikkelaarsaccount kost eenmalig $25. Google vraagt dan een `.aab`-bestand (`./gradlew bundleRelease`), een eigen sleutel (zie hierboven), een privacyverklaring en schermafbeeldingen.
