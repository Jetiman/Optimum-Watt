# Changelog

Die Release-Beschreibung auf GitHub wird automatisch aus dem jeweiligen
Abschnitt hier erzeugt (siehe `.github/workflows/release.yml`).

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
