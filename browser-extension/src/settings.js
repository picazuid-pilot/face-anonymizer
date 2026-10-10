/* Standaardinstellingen, gedeeld door bridge.js en popup.js. */
// eslint-disable-next-line no-unused-vars
const FA_DEFAULTS = {
  enabled: true,
  mode: 'overlay',          // overlay | pixelate | blur | black
  scale: 1.8,               // maskergrootte t.o.v. het gezicht
  confidence: 0.6,          // minimale detectiezekerheid
  minSize: 20,              // kleinste gezicht in pixels (in het camerabeeld)
  persistence: 20,          // detecties dat een masker blijft staan na verlies
  smartPersistence: true,   // onbevestigde detecties verdwijnen snel
  failSafeBlur: true,       // heel beeld vervagen zolang de detector niet klaar is
  detectSize: 480,          // lange zijde van het detectiebeeld: 320 snel, 480 normaal, 640 nauwkeurig
  mirrorOverlay: false,     // overlay spiegelen (alleen nuttig voor je eigen gespiegelde voorbeeld)
};
