# 🎭 Face Anonymizer

Anonimiseert gezichten live in je webcambeeld en stuurt het resultaat naar een **virtuele camera**. Bedoeld voor podcasts, interviews en livestream-events waarbij het publiek of gasten anoniem in beeld moeten blijven.

Kies daarna gewoon de virtuele camera als bron in OBS, Zoom, Teams, Google Meet, YouTube Studio enz.

- Gezichtsdetectie met [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (OpenCV), snel genoeg voor 1080p op een gewone laptop
- Tracking met de Hongaarse methode, zodat een gezicht een vast ID houdt en een korte detectie-misser het gezicht niet blootgeeft
- Vier anonimiseringsmodi: **Overlay** (eigen PNG, bijv. een logo), **Pixelate**, **Blur**, **Black**
- Twee vensters: bediening en een schaalbare preview
- Debug-kaders zie je alleen in de preview, **nooit** in de stream

https://github.com/user-attachments/assets/024daca7-4c85-42a7-befd-ff649e81f6b3

## Installatie

### Linux (Ubuntu, Debian, Mint, Fedora, Arch) – automatisch

Eenmalig in een terminal, vanuit de map van deze repository:

```bash
git clone https://github.com/picazuid-pilot/face-anonymizer.git
cd face-anonymizer
./install.sh
```

Het script:

1. installeert Python, Tk en de virtuele-camera-driver (*v4l2loopback*);
2. zet de app met een eigen Python-omgeving in `~/.local/share/face-anonymizer`;
3. downloadt het gezichtsmodel vooraf;
4. stelt de virtuele camera **"Face Anonymizer"** zo in dat hij na elke herstart beschikbaar is;
5. maakt een snelkoppeling in het **app-menu** en op het **bureaublad**.

Daarna start je Face Anonymizer gewoon via het app-menu of het bureaublad; een terminal is niet meer nodig. Gaat er iets mis bij het starten, dan krijg je een venster met de foutmelding (het volledige logboek staat in `~/.cache/face-anonymizer/`).

| | |
|---|---|
| Bijwerken | `git pull && ./install.sh` |
| Verwijderen | `./uninstall.sh` |
| Zonder vragen | `./install.sh --yes` |
| Zonder virtuele camera | `./install.sh --no-virtualcam` |

**Secure Boot:** staat Secure Boot aan, dan vraagt Ubuntu bij het installeren van de driver om een wachtwoord. Na de herstart verschijnt een blauw scherm: kies *Enroll MOK* en voer dat wachtwoord in. Daarna werkt de virtuele camera.

### Windows en macOS – handmatig

Python 3.10 of nieuwer en [OBS Studio](https://obsproject.com/) (alleen voor de driver van de virtuele camera; OBS hoeft niet open te staan).

```bash
pip install -r requirements.txt
python face_anonymizer.py
```

Op macOS moet je de virtuele camera één keer in OBS starten om hem te registreren. Op Windows zet je de virtuele camera in OBS zelf **niet** aan; deze tool gebruikt hem.

### Heb ik OBS nodig?

Nee, niet om naar Zoom, Meet of Teams te gaan. De virtuele camera verschijnt in die apps als een gewone webcam met de naam **"Face Anonymizer"**. Op Linux levert *v4l2loopback* die camera; op Windows en macOS moet OBS geïnstalleerd zijn voor de driver. OBS gebruik je alleen als je zelf een livestream opbouwt; daar kies je de virtuele camera dan als *Video-opnameapparaat*.

## Gebruik

1. Kies het cameranummer (meestal `0`) en druk op **▶ Start**.
2. Vink **Enable Virtual Camera** aan. Je kunt dit ook tijdens het streamen aan- en uitzetten.
3. Kies in Zoom, Meet, Teams of OBS de camera **"Face Anonymizer"**.
   Op Linux toont Chrome/Meet de camera pas als er beeld op staat: start dus eerst deze tool en vink de virtuele camera aan, en open of herlaad daarna Meet.
4. Zet **Show debug boxes** gerust aan om te tunen: de kaders komen niet in de stream terecht.
5. Sluit je het previewvenster, dan loopt de stream gewoon door en bespaar je rekenkracht.

Gebruik je de virtuele camera in de browser, zet dan de browserextensie uit; anders wordt het beeld twee keer bewerkt.

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
| Mirror overlay | Spiegelt het logo | Zoom, Meet en Teams spiegelen alleen je **eigen** voorbeeld; de anderen zien het logo gewoon goed. Zet dit alleen aan als je ook gespiegeld uitzendt |

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

## Browserextensie (Chrome/Edge)

In [`browser-extension/`](browser-extension/) staat een extensie (installatie: zie de [README](browser-extension/README.md); na `install.sh` staat hij ook klaar in `~/.local/share/face-anonymizer/browser-extension`) die in webapps (Google Meet, Zoom in de browser, Teams web, StreamYard, YouTube Studio) je webcambeeld vervangt door een geanonimiseerde versie. Zet hem aan en kies je gewone camera; meer is niet nodig. Hij gebruikt hetzelfde YuNet-model en dezelfde tracking als deze Python-tool.

| | Python-tool | Browserextensie |
|---|---|---|
| OBS, Zoom/Teams desktop-app | ✅ via virtuele camera | ❌ |
| Meet, Zoom/Teams in de browser, YouTube Studio | ✅ via virtuele camera | ✅ direct |
| Installatie | `install.sh` (Linux) of Python + OBS (Windows/macOS) | Extensie laden |
| Kleine gezichten ver weg | Beter (volle resolutie) | Detectie op 320–640 px |

## Roadmap

- **Webpagina** die de webcam in de browser anonimiseert, als *Browserbron* of *Venster-opname* in OBS.

## Overlay-logo

`assets/overlay.png` is het CA-logo (handelsmerk). Vervang het door je eigen afbeelding als je de tool buiten CA-verband gebruikt.

## Licentie

Nog te bepalen.
