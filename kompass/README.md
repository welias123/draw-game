# Kompass Tagesplaner

Ein Tagesplaner für den Browser und als App. Er läuft komplett offline und ohne Konto. Alle Daten bleiben in deinem Browser.

- **Heute**: Überblick über fällige Aufgaben, deine Fokuszeit der letzten 7 Tage, die heutigen Gewohnheiten und ein Notizzettel.
- **Aufgaben**: mit Fälligkeitsdatum und Wichtigkeit, gruppiert nach „Überfällig“, „Heute“, „Morgen“, „Demnächst“ und „Ohne Datum“. Doppelklick benennt eine Aufgabe um.
- **Fokus**: Pomodoro-Timer (25 min Fokus, 5 min Pause, nach 4 Runden 15 min lange Pause). Ton und Benachrichtigung am Ende, Zeiten einstellbar.
- **Gewohnheiten**: jeden Tag abhaken, mit Serie (Tage am Stück).
- **Notizen**: mit Suche, speichern beim Tippen.
- **Einstellungen**: Hell/Dunkel, Sicherung herunterladen und wieder laden, Beispieldaten entfernen.

Beim ersten Start sind Beispieldaten drin. „Beispiele entfernen“ (auf der Startseite oder in den Einstellungen) löscht sie.

## Starten: Website + App + Desktop-Verknüpfung

Einmal doppelklicken, dann passiert alles auf einmal:

| System  | Datei                          |
|---------|--------------------------------|
| Windows | `Kompass-starten-Windows.bat`  |
| macOS   | `Kompass-starten-Mac.command`  |
| Linux   | `Kompass-starten-Linux.sh`     |

Das Skript

1. legt eine Verknüpfung **„Kompass“** auf dem Desktop an (unter Windows zusätzlich im Startmenü),
2. öffnet Kompass als **Website in Brave**,
3. startet Kompass als **App** in einem eigenen Fenster ohne Browserleiste.

Danach reicht ein Doppelklick auf „Kompass“ auf dem Desktop.

Hinweise:

- **Windows** zeigt beim ersten Start evtl. „Der Computer wurde durch Windows geschützt“. Dann auf „Weitere Informationen“ und „Trotzdem ausführen“ klicken.
- **macOS** blockiert Skripte aus dem Internet beim ersten Mal. Dann mit Rechtsklick auf die Datei und „Öffnen“ starten.
- Ist Brave nicht installiert, öffnet sich Kompass im Standardbrowser.

## Andere Wege

- **Ohne Skript:** `index.html` doppelklicken. Kompass öffnet sich im Browser.
- **Als echte App (PWA) installieren:** `node kompass/serve.js` starten, `http://localhost:4173` in Brave öffnen und im Menü „Kompass installieren“ wählen. Danach läuft die App auch ohne den Server, weil sie sich offline zwischenspeichert.

## Dateien

```
kompass/
├── index.html              Seite
├── style.css               Aussehen (Karopapier, Königsblau, heller und dunkler Modus)
├── app.js                  Logik, Speicherung in localStorage
├── manifest.webmanifest    App-Beschreibung für die Installation
├── sw.js                   Service Worker für den Offline-Betrieb
├── serve.js                Mini-Webserver ohne Abhängigkeiten
├── icons/                  App-Symbole (SVG, PNG, ICO)
├── launcher/windows.ps1    Einrichtung unter Windows (von der .bat aufgerufen)
└── Kompass-starten-*       Start-Skripte für Windows, macOS und Linux
```
