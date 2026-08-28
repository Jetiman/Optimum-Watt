# Einspeise-Manager

Eine kaskadierende Überschusssteuerung für Home Assistant, für den eigenen
Warmwasserspeicher mit mehreren Heizstäben, z. B. gesteuert über einen
**Shelly 4PM**.

## Wie es funktioniert

Du hinterlegst einen Sensor, der die aktuelle **Netz-Einspeiseleistung**
liefert, sowie 1–6 Heizstufen (Schalter-Entitäten, z. B. die vier Relais
deines Shelly 4PM). Die Integration beobachtet die Einspeisung fortlaufend:

- Wird für **X Minuten** (Standard: 5) durchgehend mindestens die
  eingestellte Schwelle (Standard: 1000 W) eingespeist, schaltet **Stufe 1**
  ein.
- Bleibt die Einspeisung weiterhin hoch genug (abzüglich der bereits
  zugeschalteten Heizstäbe), schaltet nach den gleichen Regeln **Stufe 2**,
  danach **Stufe 3** usw. zu.
- Sinkt die Einspeisung für X Minuten unter die Schwelle (mit Hysterese, um
  Flattern zu vermeiden), wird die **zuletzt zugeschaltete** Stufe zuerst
  wieder abgeschaltet (LIFO – wie ein Wasserstand, der auf- und abfüllt).
- Jede Stufe lässt sich jederzeit manuell auf **An** oder **Aus** erzwingen,
  unabhängig von der Automatik.

Alle Schwellenwerte, die Ein-/Ausschaltverzögerung und die Hysterese sind
live über Zahlenfelder im Dashboard einstellbar – kein Neustart, keine
YAML-Bearbeitung nötig.

## Installation über HACS

1. HACS → Integrationen → Menü (⋮) → *Benutzerdefinierte Repositories*.
2. Repository-URL hinzufügen, Kategorie **Integration**.
3. „Einspeise-Manager" installieren und Home Assistant neu starten.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Einspeise-Manager".

## Einrichtung

Im Config-Flow wählst du:

1. **Sensor Einspeiseleistung** – ein `sensor`-Entity mit der aktuellen
   Netzleistung in Watt (positiv = Einspeisung). Zeigt dein Sensor
   Einspeisung als negativen Wert an, aktiviere die Option „Sensor zeigt
   Einspeisung als negativen Wert an".
2. **Anzahl Heizstufen** (Standard 3).
3. Für jede Stufe: Name, zu schaltende `switch`-Entität (z. B.
   `switch.shelly4pm_relais_1` deines Shelly 4PM) und Nennleistung in Watt.

Die Konfiguration kann später jederzeit über *Konfigurieren* am Integrationseintrag
angepasst werden.

## Erzeugte Entitäten

Pro Instanz wird ein Gerät „Einspeise-Manager" mit folgenden Entitäten angelegt:

| Entität | Domain | Beschreibung |
|---|---|---|
| Automatik | `switch` | Schaltet die gesamte Kaskadensteuerung ein/aus |
| Überschuss | `sensor` | Aktuelle Einspeiseleistung (normalisiert, W) |
| Aktive Stufen | `sensor` | Anzahl aktuell eingeschalteter Heizstufen |
| Heizung *n* Status | `sensor` | Text-Status + Attribute (aktiv, verbleibende Sekunden, Schwellen …) |
| Heizung *n* Modus | `select` | `auto` / `on` / `off` – erzwingt Ein/Aus oder gibt Automatik frei |
| Heizung *n* Einschaltschwelle | `number` | Einspeiseleistung (W), ab der diese Stufe zuschaltet |
| Hysterese | `number` | Abstand zwischen Ein- und Ausschaltschwelle (W) |
| Einschaltverzögerung | `number` | Minuten, die der Überschuss anstehen muss (Standard 5) |
| Ausschaltverzögerung | `number` | Minuten, die der Unterschuss anstehen muss (Standard 5) |

## Dashboard-Karte

Die Integration liefert eine eigene Lovelace-Karte mit, die automatisch als
Frontend-Ressource registriert wird (kein manuelles Hinzufügen nötig).
Beispiel-Konfiguration im Dashboard (YAML-Modus einer Karte):

```yaml
type: custom:einspeise-manager-card
title: Warmwasser Einspeise-Manager
surplus_entity: sensor.einspeise_manager_ueberschuss
auto_entity: switch.einspeise_manager_automatik
stages:
  - name: Heizung 1
    status_entity: sensor.einspeise_manager_heizung_1_status
    mode_entity: select.einspeise_manager_heizung_1_modus
    threshold_entity: number.einspeise_manager_heizung_1_einschaltschwelle
  - name: Heizung 2
    status_entity: sensor.einspeise_manager_heizung_2_status
    mode_entity: select.einspeise_manager_heizung_2_modus
    threshold_entity: number.einspeise_manager_heizung_2_einschaltschwelle
  - name: Heizung 3
    status_entity: sensor.einspeise_manager_heizung_3_status
    mode_entity: select.einspeise_manager_heizung_3_modus
    threshold_entity: number.einspeise_manager_heizung_3_einschaltschwelle
```

Die tatsächlichen Entity-IDs hängen vom Titel deiner Integrationsinstanz ab –
im UI unter *Einstellungen → Geräte & Dienste → Einspeise-Manager* nachsehen.

Die Karte zeigt den aktuellen Überschuss, einen Automatik-Umschalter sowie je
eine Kachel pro Heizstufe mit Status, Restzeit bis zur nächsten Schaltung,
Auto/An/Aus-Buttons und einem Eingabefeld für die Einschaltschwelle.

## Beispiel: Shelly 4PM

Ein Shelly 4PM stellt vier Relais als eigene `switch`-Entitäten bereit
(`switch.<gerät>_kanal_1` … `_4`). Drei davon können direkt als Stufe 1–3 in
den Config-Flow eingetragen werden; der vierte Kanal bleibt frei für andere
Zwecke. Die vom Shelly gemessene Gesamtleistung eignet sich – falls kein
separater Netzzähler vorhanden ist – ebenfalls als „Sensor Einspeiseleistung",
sofern er die Netzeinspeisung (nicht nur den Heizstab-Verbrauch) abbildet.
