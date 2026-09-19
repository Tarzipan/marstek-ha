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
| Modbus TCP für Leistungsgrenzen | aus | Schaltet die Entitäten für die Lade- und Entladeleistungsgrenze frei – siehe [Leistungsgrenzen](#leistungsgrenzen-max-lade--und-entladeleistung). |
| Modbus-Port / Unit-ID | 502 / 1 | Nur relevant, wenn der Modbus-Kanal aktiv ist. |

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

### Temperatur-Skalierung

`Bat.GetStatus.bat_temp` kommt je nach Gerät in ganzen Grad oder in Zehntelgrad
– und zwar zwischen Einheiten, die denselben Code fahren. Die Integration
entscheidet das anhand der **Größenordnung**: Rohwerte unter 100 sind ganze
Grad, ab 100 Zehntelgrad. Die beiden Bereiche können sich praktisch nicht
überschneiden, weil ein Hausspeicher etwa zwischen −20 °C und 60 °C arbeitet.

Die Firmware-Version taugt dafür **nicht**, auch wenn es naheliegt: Gemessen
liefern eine Venus E 3.0 mit Build 144 und eine mit Build 150 beide ganze Grad,
es gibt also keine Schwelle, die die Fälle trennt.

Das ist keine Kosmetik. Ein echter Wert von 27 °C, fälschlich als 2,7 °C
angezeigt, sieht exakt nach einer zu kalten Batterie aus – also nach genau dem
Zustand, in dem das Gerät die Ladefreigabe entzieht. Der falsche Messwert
bestätigt dann die falsche Diagnose.

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

### Leistungsgrenzen (Max. Lade- und Entladeleistung)

> Standardmäßig **deaktiviert**. Vor dem Einschalten den Abschnitt bis zum Ende
> lesen – der Modbus-Server der Venus ist empfindlich.

Die Open API (Rev 3.1) kennt **keinen** Befehl für eine Lade- oder
Entladeleistungs*grenze*. Das nächstgelegene, `passive_cfg.power`, ist ein
Arbeitspunkt und keine Obergrenze: Es zu setzen nimmt das Gerät aus dem
Auto-Modus und damit aus seiner eigenen, sekündlichen Regelung gegen den
Stromwandler. Genau die will man aber behalten.

Dieselben Geräte stellen beide Grenzen über **Modbus TCP** als Holding-Register
bereit (44002 und 44003, `uint16`, Watt, 0–2500). Die Integration schreibt sie
dort; alles andere bleibt bei UDP.

**Anwendungsfall.** Steht die Ladegrenze nachts auf 0 W, kann ein Gerät im
Auto-Modus nicht mehr laden, regelt seine Entladung aber unverändert weiter.
Das unterbindet das Muster, bei dem eine wegfallende Last das Gerät kurz ins
Netz drücken lässt und es diese Energie eine Sekunde später selbst wieder
einlädt – zweimal gewandelt, ohne Gegenwert. Sobald PV-Leistung anliegt, setzt
eine Automatisierung die Grenze zurück auf 2500 W.

```yaml
action: number.set_value
target:
  entity_id: number.marstek_1_max_ladeleistung
data:
  value: 0
```

**Warum der Kanal so zurückhaltend gebaut ist.** Der Modbus-Server der Venus
bedient nur **eine** Sitzung und hängt sich bei häufigen Zugriffen auf –
beobachtet bis zum Punkt, an dem nur ein Neustart des Geräts hilft. Daraus
folgt alles Weitere:

- Verbinden, schreiben, trennen – bei jedem Schreibvorgang. Die Sitzung wird nie
  offen gehalten.
- **Kein Polling.** Die Register werden genau einmal gelesen, beim Laden des
  Eintrags, damit die Entitäten den tatsächlichen Gerätezustand zeigen.
- Ein unveränderter Wert öffnet gar keine Verbindung.
- Mindestabstand von 60 s zwischen zwei Zugriffen, der **abweist statt
  einzureihen**: Eine fehlerhafte Automatisierung soll im Trace scheitern und
  keinen Rückstau aufbauen.
- Kein Retry bei Timeout. Ein Server, der nicht mehr antwortet, wird durch
  Nachsetzen nicht besser.

Der Mindestabstand gilt auch gegenüber dem Lesezugriff beim Start: Direkt nach
einem Neustart von Home Assistant wird ein Schreibversuch in der ersten Minute
abgewiesen. Das ist Absicht – es ist derselbe Zugriff auf dieselbe eine Sitzung.

**Es darf kein zweiter Modbus-Client auf dasselbe Gerät zugreifen.** Wer parallel
eine andere Marstek-Modbus-Integration betreibt, legt beide lahm. Diese vor dem
Einschalten entfernen.

Die Register leben im Gerät und überstehen einen Neustart von Home Assistant von
selbst, deshalb stellen diese beiden Entitäten – anders als die übrigen
Schreib-Entitäten – ihren Wert nicht aus dem Recorder wieder her, sondern lesen
ihn beim Start vom Gerät.

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

### Entprellung der Binary Sensoren

Die Binary Sensoren melden verrastete Hardware-Zustände: Ein Stromwandler ist
angeschlossen oder nicht, Laden ist freigegeben oder nicht. Keiner davon kippt
im Sekundenbereich hin und her. Trotzdem liefert das Gerät gelegentlich einen
einzelnen abweichenden Messwert – auf einer Venus E 3.0 mit Stromwandler 135
solcher Ausreißer bei `ct_state` in zwölf Stunden, fast alle genau einen
Poll-Zyklus lang, bei durchgehend angeschlossenem Wandler.

Ein Wechsel wird deshalb erst gemeldet, wenn das Gerät den neuen Wert in **drei
aufeinanderfolgenden Abfragen** liefert (rund 30 s). Bleibt eine Antwort ganz
aus, hält der Sensor seinen letzten Wert, und die Lücke zählt nicht auf einen
laufenden Wechsel an. `unavailable` kommt weiterhin ausschließlich vom
Coordinator, also nach drei komplett unbeantworteten Abfragen.

Das entprellt bewusst den **Wert**, nicht nur die ausbleibende Antwort: Ein
fehlender Endpunkt wird ohnehin schon weitergetragen, die Ausreißer kommen in
ansonsten gültigen Antworten an.

## Diagnose

Über **Gerät → Diagnose herunterladen** gibt die Integration die letzte
Rohantwort jedes Endpunkts aus, unskaliert. Damit lässt sich die häufigste
offene Frage beantworten, ohne zu raten: ob ein Zähler auf 0 steht, weil das
Gerät 0 liefert, oder weil die Auswertung danebenliegt. Gerätekennungen
(BLE-MAC, IP, SSID) werden geschwärzt.

Ein Speicher **ohne eigenen Stromwandler** liefert für `EM.GetStatus`
erwartungsgemäß durchgehend Nullen – `ct_state: 0`, alle Phasenleistungen und
beide Zählerstände auf 0. Das ist kein Auswertungsfehler; die Skalierung von
`input_energy`/`output_energy` (0,1 Wh → kWh) stimmt. Bei einem Gerät *mit*
Stromwandler zeigt der Diagnose-Dump, was tatsächlich ankommt.

## Entwicklung

```bash
uv venv --python 3.13 .venv-ha
uv pip install -p .venv-ha --prerelease=allow \
    pytest-homeassistant-custom-component==0.13.240
.venv-ha/bin/python -m pytest
```

Die Tests decken den UDP-Transport gegen ein simuliertes Gerät (ID-Zuordnung,
Fremdgeräte-Abwehr, Timeout und Retry), den Coordinator gegen eine echte
Home-Assistant-Instanz (Ausfalltoleranz, Ratenbegrenzung, Sollwert-Dedup), die
Entprellung der Binary Sensoren, die Temperatur-Skalierung sowie den
Modbus-Kanal ab. Letzterer wird gegen einen Stub geprüft, und zwar auf die
Eigenschaften, auf die es ankommt: Die Verbindung wird auch im Fehlerfall
geschlossen, ein unveränderter Wert öffnet keine, und die Ratenbegrenzung weist
ab statt einzureihen.

## Links

- [Repository](https://github.com/Tarzipan/marstek-ha)
- [Issues](https://github.com/Tarzipan/marstek-ha/issues)
- [Marstek Device Open API Rev 3.1](https://static-eu.marstekenergy.com/ems/resource/agreement/MarstekDeviceOpenApi.pdf)
