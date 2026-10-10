# 🎭 Face Anonymizer

Anonimiseert gezichten live in je webcambeeld en stuurt het resultaat naar een **virtuele camera**. Bedoeld voor podcasts, interviews en livestream-events waarbij het publiek of gasten anoniem in beeld moeten blijven.

Kies daarna gewoon de virtuele camera als bron in OBS, Zoom, Teams, Google Meet, YouTube Studio enz.

- Gezichtsdetectie met [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (OpenCV), snel genoeg voor 1080p op een gewone laptop
- Tracking met de Hongaarse methode, zodat een gezicht een vast ID houdt en een korte detectie-misser het gezicht niet blootgeeft
- Vier anonimiseringsmodi: **Overlay** (eigen PNG, bijv. een logo), **Pixelate**, **Blur**, **Black**
- Twee vensters: bediening en een schaalbare preview
- Debug-kaders zie je alleen in de preview, **nooit** in de stream

## Installatie

Python 3.10 of nieuwer.

```bash
git clone <deze-repo>
cd face-anonymizer
pip install -r requirements.txt
python face_anonymizer.py
```

Het YuNet-model (±230 KB) wordt bij de eerste start automatisch gedownload naar `~/.cache/yunet/`.

### Virtuele camera per besturingssysteem

| Systeem | Wat je nodig hebt |
|---|---|
| Windows | [OBS Studio](https://obsproject.com/) geïnstalleerd (levert de driver “OBS Virtual Camera”). Zet de virtuele camera in OBS zelf **niet** aan, deze tool gebruikt hem. |
| macOS | OBS Studio geïnstalleerd en de virtuele camera één keer in OBS gestart (registreert het systeemprogramma). |
| Linux | `sudo apt install v4l2loopback-dkms` en daarna `sudo modprobe v4l2loopback devices=1 exclusive_caps=1 card_label="Face Anonymizer"` |

Op Linux heb je voor de GUI ook `python3-tk` nodig.

## Gebruik

1. Kies het cameranummer (meestal `0`) en druk op **▶ Start**.
2. Vink **Enable Virtual Camera** aan. Je kunt dit ook tijdens het streamen aan- en uitzetten.
3. Kies in je stream- of vergaderapp de virtuele camera als webcam.
4. Zet **Show debug boxes** gerust aan om te tunen: de kaders komen niet in de stream terecht.
5. Sluit je het previewvenster, dan loopt de stream gewoon door en bespaar je rekenkracht.

Standaard wordt `assets/overlay.png` als overlay geladen. Met **📁 Select PNG** kies je een andere. Transparante PNG’s werken het best; zorg dat het deel dat over het gezicht valt volledig dekkend is.

### Instellingen

| Instelling | Wat het doet | Tip |
|---|---|---|
| Scale | Grootte van het masker t.o.v. het gezicht | 1.6–2.0 dekt ook haar en oren |
| Confidence | Minimale zekerheid van een detectie | Hoog (0.6–0.8) = minder valse vlekken op de achtergrond |
| Min Size | Kleinste gezicht in pixels | Verhoog bij een vol publiek op afstand als er ruis ontstaat |
| Persistence | Hoe lang (frames) een masker blijft staan als het gezicht even niet gedetecteerd wordt | Zie hieronder |
| Smart persistence | Gezichten die nog geen 5 keer gezien zijn, verdwijnen al na 5 frames | Laat aan |
| Detect at | Detecteren op lagere resolutie | `960` of `1280` geeft veel meer FPS bij 1080p; `Full` vindt kleine gezichten verder weg beter |
| Mode | Overlay / Pixelate / Blur / Black | Zonder geladen overlay wordt automatisch gepixeld |

**Waarom hoge confidence + lage persistence zo goed werkt:** bij lage confidence ontstaan af en toe valse detecties (een lamp, een poster), en met hoge persistence blijven die maskers lang hangen. *Smart persistence* lost precies dat op: losse valse detecties verdwijnen snel, terwijl echte gezichten die al een tijd gevolgd worden wél lang afgedekt blijven. Je kunt de persistence daardoor weer wat hoger zetten (bijv. 20–30) zonder rommel, wat veiliger is als iemand even wegdraait. Een kwijtgeraakt gezicht krijgt bovendien een masker dat langzaam groeit, zodat het nog bedekt is als de persoon beweegt.

## Privacy en betrouwbaarheid

Geen enkele gezichtsdetector is 100% betrouwbaar. Profielen, handen voor het gezicht, sterk tegenlicht en hele kleine gezichten kunnen gemist worden. Test daarom vooraf in de echte ruimte met het echte licht, en overweeg bij gevoelige events extra maatregelen: camerastandpunt achter het publiek, een iets grotere *Scale*, of in OBS een vaste vertraging zodat je kunt ingrijpen.

Alle verwerking gebeurt lokaal; er worden geen beelden verstuurd.

## Tests

```bash
pip install pytest
python -m pytest tests/
```

De tests draaien zonder camera of scherm.

## Roadmap: webversie

Onderzocht, nog niet gebouwd:

- **Webpagina** die de webcam in de browser anonimiseert (detectie in de browser, niets naar een server). Bruikbaar als *Venster-opname* of *Browserbron* in OBS.
- **Browserextensie** die in webapps (Google Meet, Zoom in de browser, Teams web, StreamYard, YouTube Studio) de webcam vervangt door het geanonimiseerde beeld. Werkt niet in de desktop-apps van Zoom/Teams; daarvoor blijft deze Python-tool met virtuele camera nodig.

## Overlay-logo

`assets/overlay.png` is het CA-logo (handelsmerk). Vervang het door je eigen afbeelding als je de tool buiten CA-verband gebruikt.

## Licentie

Nog te bepalen.
