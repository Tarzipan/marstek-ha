# Marstek Battery Storage - Home Assistant Integration

Eine Home Assistant Custom Integration für das Marstek VenusE 3.0 Batterie-Speichersystem.

## 📋 Beschreibung

Diese Integration ermöglicht die Überwachung und Steuerung des Marstek VenusE 3.0 Batterie-Speichersystems direkt in Home Assistant. Sie bietet Echtzeit-Daten zu Batterie-Status, Netzleistung und ermöglicht die Steuerung des Energiespeicher-Modus.

### ✨ Features

- **Echtzeit-Überwachung** von Batterie-Status, Temperatur und Kapazität
- **Netzleistung-Tracking** mit separaten Sensoren für Einspeisung und Bezug
- **Batterie-Lade-/Entlade-Tracking** mit separaten Sensoren für aktives Laden/Entladen
- **Energiespeicher-Modus-Steuerung** (Auto, AI, Manual, Passive)
- **Automatische Datenaktualisierung** alle 30 Sekunden
- **UDP-basierte Kommunikation** mit lokalem Port-Binding
- **20 Entitäten** (17 Sensoren + 2 Binary Sensoren + 1 Select)

## 📋 Anforderungen

- Home Assistant 2024.1 oder neuer
- Marstek VenusE 3.0 Gerät im lokalen Netzwerk
- Netzwerk-Zugriff auf Port 30000 (UDP)

## 🚀 Installation

### Schritt 1: Integration kopieren

Kopieren Sie den Ordner `custom_components/marstek-ha` in Ihr Home Assistant `custom_components` Verzeichnis:

```
~/.homeassistant/custom_components/marstek-ha/
```

### Schritt 2: Home Assistant neu starten

Starten Sie Home Assistant neu, damit die Integration erkannt wird.

### Schritt 3: Integration hinzufügen

1. Gehen Sie zu **Einstellungen → Geräte & Dienste**
2. Klicken Sie auf **+ Integration hinzufügen**
3. Suchen Sie nach **Marstek**
4. Geben Sie ein:
   - **IP-Adresse:** Die IP-Adresse Ihres Marstek-Geräts
   - **Port:** 30000 (Standard)
5. Klicken Sie auf **Speichern**

### Schritt 4: Entitäten überprüfen

Nach erfolgreicher Konfiguration sollten 20 Entitäten in Home Assistant verfügbar sein:

- **17 Sensoren** (Batterie, Netzwerk, Energie)
- **2 Binary Sensoren** (Laden/Entladen erlaubt)
- **1 Select-Entität** (Energiespeicher-Modus)

## 📊 Verfügbare Entitäten

### Batterie-Sensoren

- Battery State of Charge (%)
- Battery Voltage (V)
- Battery Current (A)
- Battery Power (W)
- Battery Temperature (°C)
- Battery Capacity (Wh)

### Netzwerk-Sensoren

- Grid Power (W)
- Grid Feed-in Power (W)
- Grid Consumption Power (W)

### Batterie-Lade-/Entlade-Sensoren

- Battery Charging Power (W)
- Battery Discharging Power (W)

### Energiespeicher-Sensoren

- Energy Storage Mode
- Energy Storage Power (W)
- Energy Today (kWh)
- Energy Total (kWh)

### Binary Sensoren

- Battery Charging Allowed
- Battery Discharging Allowed

### Select-Entität

- Energy Storage Mode (Auto, AI, Manual, Passive)

## 🔧 Konfiguration

Die Integration wird vollständig über die Home Assistant UI konfiguriert. Es ist keine manuelle Konfiguration erforderlich.

## 📝 Changelog

### Version 0.2.0 (Initial Release)

**Features:**

- ✅ Vollständige UDP-basierte Kommunikation mit Marstek VenusE 3.0
- ✅ 20 Entitäten (Sensoren, Binary Sensoren, Select)
- ✅ Automatische Datenaktualisierung alle 30 Sekunden
- ✅ Energiespeicher-Modus-Steuerung

**Bekannte Limitierungen:**

- Nur UDP-Protokoll auf Port 30000 unterstützt
- Manuelle IP-Eingabe erforderlich (keine automatische Geräteerkennung)
- Nur Marstek VenusE 3.0 getestet

## 🐛 Fehlerbehebung

### Verbindung fehlgeschlagen

Überprüfen Sie:

- IP-Adresse ist korrekt
- Gerät ist eingeschaltet
- Gerät ist im gleichen Netzwerk
- Port 30000 (UDP) wird nicht von Firewall blockiert
- Gerät verwendet UDP-Protokoll auf Port 30000

### Keine Entitäten sichtbar

1. Überprüfen Sie die Home Assistant Logs
2. Starten Sie Home Assistant neu
3. Entfernen Sie die Integration und fügen Sie sie erneut hinzu

## 🔗 Links

- **Repository:** https://github.com/Tarzipan/marstek-ha
- **Issues:** https://github.com/Tarzipan/marstek-ha/issues
- **Marstek OpenAPI:** https://eu.hamedata.com/ems/resource/agreement/MarstekDeviceOpenApi.pdf

---

**Entwickelt für die Home Assistant Community**
