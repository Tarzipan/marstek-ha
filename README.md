# Marstek Battery Storage – Home Assistant Integration

Home-Assistant-Custom-Integration für Marstek-Batteriespeicher (Venus E / Venus C)
über die **Marstek Device Open API Rev 3.1**, lokal per UDP.

Die Integration ist auf den Betrieb **mehrerer Speicher** ausgelegt: eine
Config-Entry pro Gerät, jede mit eigener IP und eigenem UDP-Port.

## Voraussetzungen

- Home Assistant 2025.5.0 oder neuer
- Marstek-Gerät mit aktivierter Open API im lokalen Netzwerk
- UDP-Zugriff auf den API-Port des Geräts (Standard 30000)

> **Hinweis von Marstek:** Das Aktivieren der Open API kann eingebaute Funktionen
> des Geräts deaktivieren, um Befehlskonflikte zu vermeiden. Ob der Auto-Modus
> (Nulleinspeisungsregelung gegen den Stromwandler) dabei erhalten bleibt, ist
> geräteabhängig. Die Integration unterstützt beide Fälle – siehe
> [Betriebsarten](#betriebsarten).

## Installation

### Über HACS

Repository als Custom Repository der Kategorie *Integration* hinzufügen,
installieren und Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/marstek_ha` nach
`<config>/custom_components/marstek_ha` kopieren und Home Assistant neu starten.

### Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → Marstek.**

Die Integration sucht per UDP-Broadcast nach Geräten. Gefundene Geräte lassen
sich direkt auswählen; alternativ können IP und Port von Hand eingegeben werden.
Jeder Speicher wird als eigene Integration hinzugefügt.

Unter **Konfigurieren** lassen sich je Gerät einstellen:

| Option | Standard | Bedeutung |
| --- | --- | --- |
| Abfrageintervall | 10 s | Wie oft das Gerät gepollt wird. Unter 5 s verwirft das Gerät Anfragen. |
| Mindestabstand zwischen Schreibbefehlen | 5 s | Untergrenze für den Abstand zweier `ES.SetMode`-Befehle. |

## Betriebsarten

### Auto – bevorzugt

Das Gerät regelt selbst gegen den Stromwandler bzw. den emulierten Zähler.
Home Assistant liest nur mit. Das ist der sparsamste Pfad und sekundengenau.

**Wichtig bei mehreren Speichern an einem Zähler:** Es darf immer nur *ein*
Gerät im Auto-Modus laufen, sonst regeln beide gegen dieselbe Messgröße und
schaukeln sich auf. Die übrigen Geräte gehören in den Passiv-Modus.

### Passiv – für Lastverteilung und als Rückfallebene

Im Passiv-Modus gibt Home Assistant die Leistung vor. Der zentrale Schreibpfad
ist der Service `marstek_ha.set_passive_power`, der Modus, Sollwert und
Countdown in *einem* Befehl setzt:

```yaml
action: marstek_ha.set_passive_power
target:
  device_id: <Gerät>
data:
  power: -800   # negativ = laden, positiv = entladen
  cd_time: 30   # Sekunden bis zum selbsttätigen Rückfall
```

`cd_time` ist der **Watchdog des Geräts**: Trifft innerhalb dieser Zeit kein
neuer Befehl ein, verlässt das Gerät den Passiv-Modus von selbst. Bleibt Home
Assistant stehen, fällt der Speicher also eigenständig zurück – deshalb braucht
die Integration keinen eigenen Heartbeat, und es sollte auch keiner gebaut
werden.

Als Faustregel `cd_time` auf das Zwei- bis Dreifache des Nachführintervalls
setzen: Wer alle 10 s einen Sollwert schickt, wählt `cd_time: 30`.

Werden Sollwerte häufig nachgeführt, greifen zwei Schutzmechanismen: Befehle
werden auf den eingestellten Mindestabstand ausgedünnt, und ein unveränderter
Sollwert wird nicht erneut gesendet, solange das Gerät noch Passiv meldet. Nach
Ablauf des Countdowns gilt derselbe Sollwert wieder als echtes Nachsetzen.

> **Vorzeichen noch nicht am Gerät verifiziert.** Die Integration nimmt
> durchgängig an: **positiv = entladen, negativ = laden.** Verhält sich das
> Gerät umgekehrt, genügt es, `PASSIVE_POWER_SIGN` in
> `custom_components/marstek_ha/const.py` auf `-1` zu setzen – die Konvention
> wird an genau dieser einen Stelle angewendet.

## Entitäten

Alle Entitäten tragen stabile Unique-IDs auf Basis der BLE-MAC des Geräts und
sind einem Gerät pro Speicher zugeordnet.

### Sensoren

| Quelle | Werte |
| --- | --- |
| `ES.GetStatus` | Batterieleistung (vorzeichenbehaftet), Lade- und Entladeleistung, Netzleistung, Inselnetz-Leistung, Solarleistung, Ladezustand und Kapazität |
| `ES.GetStatus` (Zähler) | Netzbezug gesamt (Wh), Netzeinspeisung gesamt (Wh), Solarenergie gesamt (kWh), Lastverbrauch gesamt (Wh) |
| `Bat.GetStatus` | Ladezustand, Temperatur, Kapazität, Nennkapazität |
| `EM.GetStatus` | Leistung Phase A/B/C, Zähler-Gesamtleistung, Zähler-Bezug und -Einspeisung (Wh) |
| `ES.GetMode` | aktueller Modus |
| `Wifi.GetStatus` | Signalstärke, IP-Adresse (Diagnose) |

Die Energiezähler der API haben unterschiedliche Skalierungen
(`total_pv_energy` in 0,01 kWh, die Zählerwerte in 0,1 Wh, die Netzzähler in Wh).
Die Integration rechnet alle auf **kWh** um, sodass sie mit passender
`device_class` und `state_class` direkt im **Energie-Dashboard** verwendbar und
untereinander vergleichbar sind.

Einzelne Leistungsfelder liefert das Gerät als vorzeichenlose 16-Bit-Zahl – eine
kleine negative Leistung kommt dann als Wert nahe 65536 an (`-12 W` als `65524`).
Die Integration rechnet das für alle Leistungsfelder zurück.

`ES.GetStatus.bat_power` fehlt auf manchen Firmwares (etwa 150 auf der Venus E
3.0). Fällt es weg, wird die AC-seitige `ongrid_power` als Ersatz verwendet; sie
trägt dasselbe Vorzeichen, unterscheidet sich aber um die Wandlungsverluste.

### Plausibilitätsprüfung

Das Gerät antwortet gelegentlich mit Unsinn – auf einer Venus E 3.0 wurden
einige Male pro Tag eine Batterietemperatur von 5,4·10¹⁰ °C und eine Kapazität
von 5,4·10¹² Wh beobachtet, zwischen ansonsten sauberen Messwerten. Jeder
numerische Sensor hat deshalb einen Plausibilitätsbereich; Werte außerhalb
werden verworfen, der vorherige Wert bleibt stehen und eine Warnung landet im
Log. Besonders wichtig ist das für die `TOTAL_INCREASING`-Zähler: Ein einziger
Ausreißer würde sich dort dauerhaft ins Energie-Dashboard schreiben.

Wenig gebräuchliche und modellabhängige Sensoren (Solar, Inselnetz, doppelte
Ladezustände) sind standardmäßig deaktiviert und lassen sich in der UI
einschalten.

### Binary Sensoren

Laden erlaubt, Entladen erlaubt, Stromwandler verbunden.

### Steuerung

| Entität | Funktion |
| --- | --- |
| Select *Energiespeicher-Modus* | Auto, AI, Manuell, Passiv, USV |
| Number *Passiv-Sollleistung* | Sollwert in W; Setzen schaltet in den Passiv-Modus |
| Number *Passiv-Countdown* | `cd_time` in s; wirkt beim nächsten Sollwert |
| Number *Entladetiefe* | `DOD.SET`, 30–88 % |
| Switch *LED*, *Bluetooth* | Schreibbefehle ohne Rückleseweg |

`DOD.SET`, LED und Bluetooth bieten laut API keinen Leseweg. Der zuletzt
geschriebene Wert wird angezeigt und über Neustarts hinweg wiederhergestellt.

## Verhalten bei Paketverlust

UDP ist verbindungslos: Einzelne verlorene Antworten sind normal. Die
Integration fängt das ab, statt Entitäten flackern zu lassen:

- Es ist immer nur **eine Anfrage gleichzeitig unterwegs**. Das Gerät
  beantwortet jeweils nur eine Anfrage und verwirft stillschweigend alles, was
  währenddessen eintrifft – ein Poll, der seine Kommandos parallel abschickt,
  verliert die meisten Antworten.
- Jede Anfrage bekommt eine eigene ID; Antworten werden darüber zugeordnet.
  Verspätete oder fremde Antworten werden verworfen und können keine Werte in
  die falschen Sensoren schreiben.
- Antworten von einer anderen Absender-IP werden ignoriert – relevant, sobald
  mehrere Speicher im Netz sind.
- Jede Anfrage wird einmal wiederholt.
- Bleibt ein einzelner Endpunkt stumm, behält er seinen letzten Wert.
- Erst nach drei vollständig unbeantworteten Abfragen in Folge werden die
  Entitäten als nicht verfügbar gemeldet.
- Ein Poll ist auf die Dauer eines Abfrageintervalls begrenzt, damit ein
  stummes Gerät keine Abfragen auflaufen lässt.

## Entwicklung

```bash
uv venv --python 3.13 .venv-ha
uv pip install -p .venv-ha --prerelease=allow \
    pytest-homeassistant-custom-component==0.13.240
.venv-ha/bin/python -m pytest
```

Die Tests decken den UDP-Transport gegen ein simuliertes Gerät (ID-Zuordnung,
Fremdgeräte-Abwehr, Timeout und Retry) sowie den Coordinator gegen eine echte
Home-Assistant-Instanz ab (Ausfalltoleranz, Ratenbegrenzung, Sollwert-Dedup).

## Links

- [Repository](https://github.com/Tarzipan/marstek-ha)
- [Issues](https://github.com/Tarzipan/marstek-ha/issues)
- [Marstek Device Open API Rev 3.1](https://static-eu.marstekenergy.com/ems/resource/agreement/MarstekDeviceOpenApi.pdf)
