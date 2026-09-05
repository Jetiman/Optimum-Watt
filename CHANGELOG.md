# Changelog

Die Release-Beschreibung auf GitHub wird automatisch aus dem jeweiligen
Abschnitt hier erzeugt (siehe `.github/workflows/release.yml`).

## v0.4.0 – Schaltzeiten pro Gerät

### Neu
- **Schaltzeiten.** Pro Gerät lassen sich beliebig viele wiederkehrende
  Zeitfenster anlegen (im „Gerät bearbeiten"-Formular → „Schaltzeiten" →
  „+ Schaltzeit"). Ein Fenster hat Von-/Bis-Uhrzeit, aktive Wochentage
  und eine feste Aktion: **Auto**, **An**, **Aus** oder **Regelung aus**.
  Solange ein Fenster aktiv ist, überschreibt seine Aktion den normal
  gewählten Modus des Geräts – z. B. „Mo–Fr 22:00–06:00 → Aus" oder
  „Sa–So ganztags → Auto". Fenster über Mitternacht (22:00–06:00) sind
  erlaubt; überlappen sich zwei, gewinnt das zuletzt angelegte.
- In der Karte steht bei einem Gerät, dessen Modus gerade von einer
  Schaltzeit bestimmt wird, „⏱ Schaltzeit".
- Auch als Feld `schedules` im Service `optimum_watt.add_device` (Liste
  von `{start, end, days, action}`; `days` = 0–6, Montag = 0).

## v0.3.2 – Hängender Schalter-Aufruf blockiert nicht mehr alles

### Behoben
- **Ein zäh antwortendes Gerät konnte die komplette Regelung dauerhaft
  einfrieren.** Reagierte ein Schalter (z. B. ein WLAN-Relais nach einem
  kurzen Netzwerk-Aussetzer) auf `switch.turn_on`/`turn_off` nicht mit
  Erfolg oder Fehler, sondern gar nicht, wartete Optimum Watt endlos
  darauf – ohne Fehlermeldung im Log, denn nichts ist fehlgeschlagen, es
  hing nur fest. Alle Geräte blieben dabei auf ihrem letzten Stand
  eingefroren, z. B. dauerhaft „schaltet in 0 s ein".
  Schaltbefehle haben jetzt ein Zeitlimit (10 s); danach wird das Gerät
  als „Schalter nicht erreichbar" markiert und die Regelung läuft für
  alle anderen Geräte normal weiter.
- Ein bereits hängender Zustand lässt sich auch ohne Update beheben:
  Einstellungen → Geräte & Dienste → Optimum Watt → „Neu laden".

## v0.3.1 – Netz-Ladung des Speichers zählt nicht als Überschuss

### Behoben
- **Basis „Überschuss vor Speicherladung" blieb an, wenn der Speicher aus
  dem Netz lädt.** Lud die Batterie z. B. mit 6 kW, davon 5,9 kW aus dem
  Netz, wurde das als Überschuss gewertet und die Geräte liefen weiter –
  auf bezahltem Netzstrom. Jetzt wird der aus dem Netz stammende Anteil
  der Speicherladung abgezogen.

### Neu
- Einstellung **„Max. Netz-Ladung des Speichers (W)"** (Standard 100).
  Lädt der Speicher mehr als diesen Wert aus dem Netz, schalten Geräte
  mit Basis „Überschuss vor Speicherladung" ab. `0` = aus (altes
  Verhalten: jede Speicherladung zählt als Überschuss).
- In der Karte steht bei den betroffenen Geräten dann „⏸ Speicher lädt
  aus Netz".

## v0.3.0 – Info-Sensoren & Kartenverbesserungen

### Neu
- **Info-Sensoren pro Gerät.** Im „Gerät bearbeiten"-Formular lassen sich
  unter *Zusätzliche Sensoren* beliebig viele Entitäten hinterlegen –
  z. B. eine Temperatur oder die aktuelle Leistung. Sie werden als reiner
  Wert neben dem Gerät in der Karte angezeigt und haben **keinen**
  Einfluss auf die Regelung. Auch als Feld `info_entities` im Service
  `optimum_watt.add_device`.

### Behoben
- **Ein hängender Schalter legte die ganze Regelung lahm.** Ließ sich
  `switch.turn_on`/`turn_off` für ein Gerät nicht ausführen (Entität
  umbenannt, gelöscht oder Relais offline), brach das die komplette
  Auswertung pro Zyklus ab – *alle* Geräte froren auf ihrem letzten
  Status ein und zeigten dauerhaft „schaltet in 0 s ein". Der Fehler wird
  jetzt abgefangen: das betroffene Gerät wird rot mit „⚠ Schalter nicht
  erreichbar" markiert, alle anderen laufen normal weiter.

### Karte
- **Version & Build** unten im aufklappbaren *Einstellungen*-Feld. Der
  Build-Hash ändert sich bei jeder Code-Änderung – so lässt sich prüfen,
  ob der laufende Stand wirklich der aktuelle ist.
- Größere Logo-Marke oben links.
- Mehr Abstand zwischen Home-Assistant-Toolbar und Karte in der
  Seitenleisten-Ansicht.

### Intern
- Beta-Builds erscheinen als hochzählende Pre-Releases
  `vX.Y.Z-beta.N`; die jeweils vorherige Beta wird sofort gelöscht. So
  erkennt HACS ein Update und die Releases-Liste bleibt aufgeräumt.

## v0.2.0 – Umbenennung zu Optimum Watt

Erste Version unter dem neuen Namen (vorher „Wattix").

**Breaking Change:** Die Integrations-Domain wechselt von `wattix` zu
`optimum_watt`. Bestehende Installationen müssen die Integration einmal
entfernen und neu einrichten; Entitäten heißen danach `optimum_watt.*`,
Services `optimum_watt.*`, die Karte ist `custom:optimum-watt-card`.

Enthalten sind außerdem die Arbeiten aus dem bisherigen Test-Zweig:
Schwellenbasis pro Gerät (PV-Produktion bzw. Überschuss vor
Speicherladung), Speicher-SoC-Gate pro Gerät, Sensor-Timeout-
Sicherheitsabschaltung und das neue OW-Logo.
