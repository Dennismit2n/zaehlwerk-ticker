# Zählwerk Ticker 📊

**Der Verbrauch im Blick, während du arbeitest.** Eine kleine schwebende Anzeige für Windows: laufender Fünf-Stunden-Block, Tagessumme, Aufteilung nach Modell. Liest ausschließlich die Protokolldateien, die Claude Code auf deiner eigenen Festplatte anlegt.

![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-a3e635) ![Kein Netz](https://img.shields.io/badge/Netzzugriff-keiner-4d7c0f) ![Sprachen](https://img.shields.io/badge/Sprachen-DE%20%7C%20EN-65a30d) ![Lizenz](https://img.shields.io/badge/Lizenz-MIT-6ee7b7)

**Ausführliche Auswertung im Browser: [Zählwerk](https://dennismit2n.github.io/zaehlwerk/)** · [English version](README.md)

---

## Wofür

Die Browser-Fassung ist zum Hinsetzen und Anschauen. Diese hier ist zum Nebenherlaufen: Sie steht in einer Bildschirmecke und beantwortet eine einzige Frage — *wie viel ist im laufenden Fenster schon weg, und wann kippt es?*

## Was angezeigt wird

| | |
|---|---|
| **Block** | Verbrauch im laufenden Fünf-Stunden-Fenster, mit Balken und Restzeit |
| **Heute** | Tagessumme und Zahl der Antworten |
| **Modelle** | die drei stärksten im laufenden Block |

## Was NICHT angezeigt wird

- **Kein Prozentsatz eines Kontingents.** Wie viel dir noch zusteht, steht in diesen Dateien nicht. Der Ticker kann nur zählen, was verbraucht wurde — ein Balken gegen ein Limit wäre erfunden.
- **Keine Kosten.** In den Protokollen stehen keine Preise, und im Abonnement kostet Claude Code nichts zusätzlich.
- **Nur Claude Code.** Was du auf claude.ai im Browser tust, hinterlässt keine Protokolle auf der Platte.

## Zum Fünf-Stunden-Block

Wann genau ein neues Fenster beginnt, ist von Anthropic **nicht dokumentiert**. Der Ticker rekonstruiert es aus den Zeitstempeln: Das erste Fenster beginnt mit der ersten Antwort und läuft fünf Stunden; die erste Antwort danach beginnt das nächste — unabhängig davon, ob dazwischen eine Pause lag. So kettet es sich bis zum aktuellen Fenster durch.

Das ist eine begründete Annahme, keine bestätigte Tatsache. Deshalb steht in der Anzeige **„geschätzt"**, und deshalb steht es auch hier.

## Loslegen

**Mit der fertigen Exe** — aus den [Releases](../../releases/latest) herunterladen, irgendwo hinlegen, doppelklicken. Beim ersten Start meldet Windows „Unbekannter Herausgeber": Die Datei ist nicht signiert, das kostet Geld. Über **Weitere Informationen → Trotzdem ausführen**.

**Aus dem Quellcode:**

```
pip install pystray pillow
pythonw zaehlwerk_ticker.py
```

## Bedienung

| | |
|---|---|
| Ziehen | Overlay verschieben — Position wird beim Loslassen gemerkt |
| Doppelklick | zwischen klein und groß umschalten |
| Rechtsklick aufs Taskleisten-Symbol | Overlay an/aus, zur Mitte holen, jetzt aktualisieren, Sprache, Beenden |

Verschwunden? **Zur Mitte holen** im Menü. Das passiert, wenn ein zweiter Bildschirm abgezogen wurde — das Overlay ist randlos und hat keine Titelleiste zum Zurückholen.

## Datenschutz

**Es gibt keinen Netzzugriff.** Nicht „wir senden nichts", sondern: Die Fähigkeit ist gar nicht erst eingebaut. Nachprüfbar über die Importliste des Programms — `requests`, `urllib`, `socket`, `http`, `webbrowser` kommen darin nicht vor. Es gibt keinen Update-Check, keine Telemetrie, keine Kennung.

Gelesen werden ausschließlich die `.jsonl`-Dateien unter `%USERPROFILE%\.claude\projects`, und davon nur die Abrechnungszeilen: Zeitstempel, Modellname und die vier Token-Zahlen. Gesprächsinhalte werden weder ausgewertet noch angezeigt.

Geschrieben wird genau eine Datei: `einstellungen.json` neben dem Programm, mit Position, Deckkraft, Sprache und dem Klein/Groß-Zustand. Kein Protokoll, keine Zwischenspeicher.

## Unter der Haube

Eine Datei, rund 810 Zeilen, zwei Fremdpakete (`pystray`, `pillow`) — alles andere ist Python-Standardbibliothek.

**Zwei Dinge entscheiden über die Richtigkeit der Zahlen:**

1. **Entdopplung über `message.id`.** Eine Antwort steht mehrfach in der Protokolldatei — einmal je Block, aus dem sie besteht (Nachdenken, Text, Werkzeugaufruf) — und *jede* dieser Zeilen trägt die vollständige Abrechnung. An echten Daten ergibt naives Zusammenzählen mehr als das Doppelte.
2. **Inkrementelles Lesen.** Beim Start wird alles gelesen (rund 0,6 Sekunden für 16.000 Zeilen), danach je Datei nur der neu hinzugekommene Teil — das dauert typischerweise unter 10 Millisekunden. Eine angefangene letzte Zeile wird bewusst liegengelassen und erst gelesen, wenn sie vollständig ist.

**Das Protokollformat ist nicht dokumentiert.** Ändert Anthropic es, zeigt der Ticker zu wenig oder nichts mehr.

## Lizenz

MIT — siehe [LICENSE](LICENSE).

---

Zählwerk Ticker ist ein privates Werkzeug und steht **in keiner Verbindung zu Anthropic**. „Claude" ist eine Marke von Anthropic PBC.

Teil der [Werkstatt](https://dennismit2n.github.io/) von Dennis_mit_2n.
