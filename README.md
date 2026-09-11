# gcal-todo-sync

Zwei-Wege-Sync zwischen Microsoft To Do (alle Listen) und einem Google
Kalender. Läuft stündlich als Claude-Cloud-Routine.

## Architektur

- **Microsoft To Do**: Es gibt keinen fertigen Schreib-Connector, daher
  spricht `scripts/ms_graph.py` direkt mit der Microsoft Graph REST API.
  Anmeldung per Device-Code-Flow über Microsofts eigene öffentliche App
  "Microsoft Graph Command Line Tools" — keine eigene Azure-App-Registrierung
  nötig.
- **Google Calendar**: Läuft über den bereits verbundenen Google-Calendar-
  Connector. Die Cloud-Routine (ein Claude-Agent) ruft dessen Tools
  (`list_events`, `create_event`, `update_event`, `delete_event`) direkt auf.
- **Verknüpfung**: Jeder synchronisierte Google-Termin bekommt einen
  unsichtbaren HTML-Kommentar am Ende der Beschreibung
  (`<!--gcalsync:list=...;task=...-->`), jede Microsoft-Aufgabe bekommt eine
  `linkedResources`-Eintrag mit der Google-Event-ID. So werden Duplikate und
  Echo-Schleifen vermieden.
- **Zustand**: `state.json` (Zuordnungspaare + Hashes zur Änderungserkennung)
  und `secrets/ms_token.enc` (verschlüsselter Microsoft-Refresh-Token) werden
  nach jedem Lauf von der Routine committet und gepusht — das ist das
  "Gedächtnis" zwischen den stündlichen Läufen.

## Ablauf pro Lauf

1. `python scripts/sync.py window` — liefert den Zeitfenster (heute -3 bis
   +60 Tage), ohne Anmeldung.
2. Agent ruft `list_events` (Google Calendar) für dieses Fenster ab, schreibt
   eine vereinfachte JSON-Liste (`id`, `summary`, `description`, `startDate`,
   `allDay`) in eine temporäre Datei.
3. `python scripts/sync.py sync --events-file <datei>` — holt alle
   Microsoft-To-Do-Aufgaben (alle Listen, alle Status), vergleicht mit dem
   vorherigen Zustand, wendet alle Microsoft-seitigen Änderungen sofort an
   und gibt eine Liste offener Google-Aktionen zurück
   (`create_event` / `update_event` / `delete_event`).
4. Agent führt jede dieser Aktionen über die Google-Calendar-Connector-Tools
   aus und merkt sich pro Aktion das Ergebnis (bei `create_event`: die neue
   Event-ID).
5. `python scripts/sync.py finalize --results-file <datei>` — verknüpft neu
   erstellte Google-Termine mit der passenden Microsoft-Aufgabe und
   aktualisiert `state.json`.
6. Agent committet und pusht `state.json` und ggf. `secrets/ms_token.enc`.

## Einmaliges Setup

1. Python + `pip install -r requirements.txt` lokal.
2. `python scripts/get_ms_token.py` ausführen, mit dem privaten
   Microsoft-Konto anmelden (Browser-Code-Login, kein Azure-Portal nötig).
3. Den ausgegebenen Passphrase-Wert als Secret `SYNC_SECRET_KEY` in der
   Claude-Cloud-Umgebung hinterlegen.
4. `secrets/ms_token.enc` committen und pushen.

## Bekannte Einschränkungen (v1)

- Minimales Sync-Intervall: 1 Stunde (Vorgabe der Claude-Routinen), kein
  Echtzeit-Sync.
- Aufgaben ohne Fälligkeitsdatum werden nicht synchronisiert (kein
  sinnvolles Kalender-Äquivalent).
- Wiederkehrende Google-Termine/Aufgaben werden als einzelnes Element
  behandelt, nicht pro Vorkommnis.
- Neue Aufgaben aus Google-Terminen landen alle in derselben (ersten)
  To-Do-Liste.
- Termine/Aufgaben, deren Gegenstück außerhalb des aktuellen Zeitfensters
  liegt, werden in diesem Lauf nicht auf Löschung geprüft (verhindert
  Fehlalarme bei alten Einträgen).
