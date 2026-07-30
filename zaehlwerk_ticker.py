"""
Zählwerk Ticker — schwebende Anzeige des Claude-Code-Verbrauchs (Windows)
=========================================================================
Zeigt live, wie viel im laufenden Fünf-Stunden-Block und am heutigen Tag
verbraucht wurde. Liest ausschließlich die Protokolldateien, die Claude Code
selbst auf dieser Festplatte anlegt.

    Ordner: %USERPROFILE%\\.claude\\projects   (bzw. ~/.claude/projects)

KEIN NETZZUGRIFF. Es gibt in dieser Datei keinen einzigen Aufruf, der etwas
verschickt oder abruft — kein requests, kein urllib, kein socket. Wer das
prüfen will: eine Suche über den Quelltext genügt.

Installation (einmalig):
    pip install pystray pillow

Start:
    pythonw zaehlwerk_ticker.py

Bedienung:
    - Overlay mit der Maus verschieben (Position wird beim Loslassen gemerkt)
    - Doppelklick: zwischen klein und groß umschalten
    - Rechtsklick aufs Symbol in der Taskleiste: Overlay an/aus, zur Mitte
      holen, jetzt aktualisieren, Sprache, Beenden

WAS DIESE ANZEIGE NICHT KANN:
    Sie zeigt keinen Prozentsatz eines Kontingents. Wie viel einem noch
    zusteht, steht in diesen Dateien nicht — nur, was verbraucht wurde.
    Sie zeigt auch keine Kosten: In den Protokollen stehen keine Preise.

ZUM FÜNF-STUNDEN-BLOCK:
    Wann genau Anthropic ein neues Fenster beginnt, ist nirgends dokumentiert.
    Diese Anzeige rekonstruiert es aus den Zeitstempeln: Ein Block beginnt mit
    der ersten Antwort nach einer Pause von mindestens fünf Stunden und endet
    fünf Stunden später. Das ist eine begründete Annahme, keine bestätigte
    Tatsache — deshalb steht in der Anzeige „geschätzt".

Teil der Werkstatt: https://dennismit2n.github.io/
Browser-Fassung mit ausführlicher Auswertung: .../zaehlwerk/
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import messagebox

try:
    import ctypes
except ImportError:
    ctypes = None

try:
    import msvcrt                      # nur Windows — für die Instanz-Sperre
except ImportError:
    msvcrt = None

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Bitte zuerst installieren:  pip install pystray pillow")
    sys.exit(1)

VERSION = "1.0"

# ------------------------------ Pfade & Konstanten --------------------------

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(_BASE_DIR, "einstellungen.json")
LOCK_PATH = os.path.join(_BASE_DIR, ".ticker.lock")

PROTOKOLL_ORDNER = os.path.join(os.path.expanduser("~"), ".claude", "projects")

BLOCK_STUNDEN = 5                      # Länge des angenommenen Fensters
AKTUALISIERUNG = 60                    # Sekunden zwischen zwei Durchläufen
BAR_W, BAR_H = 190, 7

# Farbwelt: dieselbe Oliv-Limette wie das Browser-Werkzeug
FARBEN = {
    "bg": "#141a0c",
    "titel": "#a3e635",
    "text": "#eaf2dd",
    "leise": "#8b9878",
    "balken_bg": "#2a3520",
    "balken": "#a3e635",
    "warn": "#fbbf24",
}

# ------------------------------ Sprachen ------------------------------------
# Zwei Sprachen, von Hand geschrieben. Die Browser-Fassung führt zwölf;
# für ein Tray-Menü mit einer Handvoll Zeilen wäre das unnötiger Ballast.

TEXTE = {
    "de": {
        "_name": "Deutsch",
        "titel": "Zählwerk",
        "block": "Block",
        "blockGeschaetzt": "geschätzt",
        "heute": "Heute",
        "endetIn": "endet in",
        "abgelaufen": "abgelaufen",
        "antworten_1": "Antwort",
        "antworten_n": "Antworten",
        "lade": "lese Protokolle …",
        "keineDaten": "Noch keine Nutzung heute",
        "keinOrdner": "Ordner nicht gefunden",
        "keinOrdnerLang": ("Der Ordner mit den Protokollen wurde nicht gefunden:\n\n{pfad}\n\n"
                           "Er entsteht, sobald Claude Code das erste Mal gelaufen ist."),
        "aktualisiert": "aktualisiert %H:%M:%S",
        "mOverlay": "Overlay an/aus",
        "mMitte": "Overlay zur Mitte holen",
        "mJetzt": "Jetzt aktualisieren",
        "mSprache": "Sprache",
        "mBrowser": "Ausführliche Auswertung im Browser",
        "mBeenden": "Beenden",
        "laeuftBereits": ("Der Zählwerk Ticker läuft bereits.\n\n"
                          "Das Symbol steckt im Infobereich der Taskleiste — "
                          "Rechtsklick darauf."),
    },
    "en": {
        "_name": "English",
        "titel": "Zählwerk",
        "block": "Block",
        "blockGeschaetzt": "estimated",
        "heute": "Today",
        "endetIn": "ends in",
        "abgelaufen": "expired",
        "antworten_1": "reply",
        "antworten_n": "replies",
        "lade": "reading logs …",
        "keineDaten": "No usage today yet",
        "keinOrdner": "Folder not found",
        "keinOrdnerLang": ("The folder holding the logs was not found:\n\n{pfad}\n\n"
                           "It appears once Claude Code has run for the first time."),
        "aktualisiert": "updated %H:%M:%S",
        "mOverlay": "Show/hide overlay",
        "mMitte": "Bring overlay to centre",
        "mJetzt": "Refresh now",
        "mSprache": "Language",
        "mBrowser": "Full analysis in the browser",
        "mBeenden": "Quit",
        "laeuftBereits": ("Zählwerk Ticker is already running.\n\n"
                          "Its icon sits in the notification area — right-click it."),
    },
}


def systemsprache() -> str:
    """Windows-Anzeigesprache; alles außer Deutsch bekommt Englisch."""
    try:
        if ctypes is not None:
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if (lcid & 0x3FF) == 0x07:          # LANG_GERMAN
                return "de"
    except (AttributeError, OSError):
        pass
    return "en"


# ------------------------------ Einstellungen -------------------------------


def lade_einstellungen() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            werte = json.load(f)
        return werte if isinstance(werte, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def speichere_einstellungen(werte: dict) -> None:
    """Atomar: erst daneben schreiben, dann umbenennen."""
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(werte, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ------------------------------ Instanz-Sperre ------------------------------

_LOCK = None


def sperre_holen() -> bool:
    global _LOCK
    if msvcrt is None:
        return True
    try:
        _LOCK = open(LOCK_PATH, "a+b")
        msvcrt.locking(_LOCK.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        if _LOCK is not None:
            try:
                _LOCK.close()
            except OSError:
                pass
            _LOCK = None
        return False


def sperre_freigeben() -> None:
    global _LOCK
    if _LOCK is None:
        return
    try:
        msvcrt.locking(_LOCK.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    try:
        _LOCK.close()
    except OSError:
        pass
    _LOCK = None


# ------------------------------ Bildschirmgrenzen ---------------------------


def virtueller_bildschirm() -> tuple[int, int, int, int]:
    """(x, y, breite, höhe) über alle Monitore — tkinter kennt nur den ersten."""
    try:
        g = ctypes.windll.user32.GetSystemMetrics
        return g(76), g(77), g(78), g(79)
    except (AttributeError, OSError):
        return 0, 0, 1920, 1080


def auf_bildschirm(x: int, y: int, w: int = 230, h: int = 120) -> tuple[int, int]:
    """Holt eine Position zurück ins Sichtbare. Nötig, weil das Overlay
    randlos ist: liegt es außerhalb, kommt man ohne Neustart nicht mehr dran."""
    vx, vy, vw, vh = virtueller_bildschirm()
    rand = 40
    if (x + w < vx + rand or x > vx + vw - rand
            or y + h < vy + rand or y > vy + vh - rand):
        return vx + 60, vy + 60
    return x, y


# ------------------------------ Protokolle lesen ----------------------------


class Protokolle:
    """Liest die .jsonl-Dateien inkrementell.

    Beim ersten Durchlauf wird alles gelesen, danach je Datei nur der Teil,
    der seither dazugekommen ist. Ohne das würde jeder Durchlauf zig Megabyte
    erneut durchkauen, obwohl sich meist nur ein paar Zeilen ändern.
    """

    def __init__(self, ordner: str):
        self.ordner = ordner
        self._stand: dict[str, int] = {}        # Pfad -> gelesene Bytes
        self._gesehen: set[str] = set()         # message.id
        self.antworten: list[dict] = []         # je Antwort ein Eintrag
        self.zeilen_gelesen = 0
        self.doppelte = 0

    def ordner_da(self) -> bool:
        return os.path.isdir(self.ordner)

    def _dateien(self):
        for wurzel, _, namen in os.walk(self.ordner):
            for name in namen:
                if name.endswith(".jsonl"):
                    yield os.path.join(wurzel, name)

    def einlesen(self) -> int:
        """Liest alles Neue. Rückgabe: Anzahl neu erfaßter Antworten."""
        neu = 0
        for pfad in self._dateien():
            try:
                groesse = os.path.getsize(pfad)
            except OSError:
                continue
            ab = self._stand.get(pfad, 0)
            if groesse == ab:
                continue
            if groesse < ab:            # Datei wurde gekürzt oder ersetzt
                ab = 0
            try:
                with open(pfad, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(ab)
                    rest = f.read()
                    self._stand[pfad] = groesse
            except OSError:
                continue

            # Eine angefangene letzte Zeile beim nächsten Mal erneut lesen
            schnitt = rest.rfind("\n")
            if schnitt == -1:
                self._stand[pfad] = ab
                continue
            if schnitt + 1 < len(rest):
                self._stand[pfad] = ab + len(rest[:schnitt + 1].encode("utf-8"))
                rest = rest[:schnitt + 1]

            for zeile in rest.split("\n"):
                if not zeile.strip():
                    continue
                self.zeilen_gelesen += 1
                if self._zeile(zeile):
                    neu += 1
        return neu

    def _zeile(self, zeile: str) -> bool:
        try:
            o = json.loads(zeile)
        except (ValueError, TypeError):
            return False
        if not isinstance(o, dict):
            return False
        nachricht = o.get("message")
        if not isinstance(nachricht, dict):
            return False
        u = nachricht.get("usage")
        if not isinstance(u, dict):
            return False

        # Entdopplung: Eine Antwort steht einmal je Block in der Datei, und
        # JEDE dieser Zeilen trägt die vollständige Abrechnung. Ohne das hier
        # wären alle Zahlen mehr als doppelt so hoch.
        kennung = nachricht.get("id")
        if not kennung:
            return False
        if kennung in self._gesehen:
            self.doppelte += 1
            return False
        self._gesehen.add(kennung)

        zeit = _zeitstempel(o.get("timestamp"))
        if zeit is None:
            return False

        ein = _zahl(u.get("input_tokens"))
        aus = _zahl(u.get("output_tokens"))
        cache_neu = _zahl(u.get("cache_creation_input_tokens"))
        cache_gelesen = _zahl(u.get("cache_read_input_tokens"))

        self.antworten.append({
            "zeit": zeit,
            "modell": nachricht.get("model") or "?",
            "echt": ein + aus + cache_neu,
            "cache": cache_gelesen,
        })
        return True


def _zahl(v) -> int:
    return v if isinstance(v, int) and v >= 0 else 0


def _zeitstempel(s) -> float | None:
    if not s:
        return None
    try:
        t = str(s).replace("Z", "+00:00")
        return datetime.fromisoformat(t).timestamp()
    except (ValueError, TypeError):
        return None


# ------------------------------ Auswertung ----------------------------------


def block_grenzen(zeiten: list[float], jetzt: float) -> tuple[float, float] | None:
    """Ermittelt den laufenden Fünf-Stunden-Block.

    Angenommen wird: Ein Block beginnt mit der ersten Antwort und läuft fünf
    Stunden. Die erste Antwort NACH diesem Ende beginnt den nächsten Block —
    unabhängig davon, ob dazwischen eine Pause lag. So kettet sich das über
    den ganzen Verlauf, und übrig bleibt der zuletzt begonnene Block.

    Wie Anthropic das tatsächlich handhabt, ist nicht dokumentiert; die
    Anzeige sagt deshalb „geschätzt".

    (Frühere Fassung suchte nur nach Pausen von mindestens fünf Stunden. Das
    war falsch: Wer durcharbeitet, hat trotzdem irgendwann ein neues Fenster —
    an echten Daten zeigte die Anzeige einen längst abgelaufenen Block, obwohl
    Stunden später weitergearbeitet wurde.)
    """
    if not zeiten:
        return None
    fenster = BLOCK_STUNDEN * 3600
    start = None
    ende = None
    for t in sorted(zeiten):
        if ende is None or t > ende:
            start = t
            ende = t + fenster
    return start, ende


def tagesbeginn(jetzt: float) -> float:
    d = datetime.fromtimestamp(jetzt)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def auswerten(antworten: list[dict], jetzt: float | None = None) -> dict:
    jetzt = jetzt if jetzt is not None else time.time()
    tag_ab = tagesbeginn(jetzt)

    heute = [a for a in antworten if a["zeit"] >= tag_ab]
    grenzen = block_grenzen([a["zeit"] for a in antworten], jetzt)

    block_liste: list[dict] = []
    if grenzen:
        von, bis = grenzen
        block_liste = [a for a in antworten if von <= a["zeit"] <= bis]

    def summe(liste):
        return {
            "echt": sum(a["echt"] for a in liste),
            "cache": sum(a["cache"] for a in liste),
            "anzahl": len(liste),
        }

    modelle: dict[str, int] = {}
    for a in block_liste or heute:
        modelle[a["modell"]] = modelle.get(a["modell"], 0) + a["echt"]

    return {
        "block": summe(block_liste),
        "heute": summe(heute),
        "gesamt": summe(antworten),
        "block_von": grenzen[0] if grenzen else None,
        "block_bis": grenzen[1] if grenzen else None,
        "modelle": sorted(modelle.items(), key=lambda x: -x[1]),
    }


def kurz_modell(name: str) -> str:
    """claude-opus-5 -> Opus 5, claude-haiku-4-5-20251001 -> Haiku 4.5"""
    n = str(name)
    if n.startswith("claude-"):
        n = n[len("claude-"):]
    teile = n.split("-")
    if not teile:
        return name
    familie = teile[0].capitalize()
    ziffern = [t for t in teile[1:] if t.isdigit()]
    if not ziffern:
        return familie
    if len(ziffern[0]) >= 8:                      # angehängtes Datum
        return familie
    version = ziffern[0]
    if len(ziffern) > 1 and len(ziffern[1]) == 1:
        version += "." + ziffern[1]
    return f"{familie} {version}"


def zahl(n: int) -> str:
    """Tausendertrennung ohne locale-Abhängigkeit."""
    return f"{int(n):,}".replace(",", ".")


def dauer_kurz(sekunden: float, sprache: str) -> str:
    s = max(0, int(sekunden))
    st, rest = divmod(s, 3600)
    mi = rest // 60
    if st:
        return f"{st}h {mi:02d}m"
    return f"{mi}m"


# ------------------------------ Anwendung -----------------------------------


class TickerApp:

    def __init__(self):
        self.cfg = lade_einstellungen()
        self.sprache = self.cfg.get("sprache") or systemsprache()
        if self.sprache not in TEXTE:
            self.sprache = "en"

        self.protokolle = Protokolle(PROTOKOLL_ORDNER)
        self.ergebnis: dict | None = None
        self.kompakt = bool(self.cfg.get("kompakt", False))
        self.sichtbar = True

        self.ui_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self._lese_sperre = threading.Lock()
        self.icon: pystray.Icon | None = None

        self._baue_fenster()
        self._baue_tray()

        self.worker = threading.Thread(target=self._schleife, daemon=True)
        self.worker.start()
        self.root.after(200, self._queue_abarbeiten)

    def t(self, schluessel: str) -> str:
        return TEXTE[self.sprache].get(schluessel, schluessel)

    # ---------------------------------------------------------------- Fenster

    def _baue_fenster(self):
        self.root = tk.Tk()
        self.root.title("Zaehlwerk Ticker")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", int(self.cfg.get("deckkraft", 88)) / 100.0)
        self.root.configure(bg=FARBEN["bg"])

        x, y = auf_bildschirm(int(self.cfg.get("pos_x", 60)),
                              int(self.cfg.get("pos_y", 60)))
        self.cfg["pos_x"], self.cfg["pos_y"] = x, y
        self.root.geometry(f"+{x}+{y}")

        self.rahmen = tk.Frame(self.root, bg=FARBEN["bg"], padx=11, pady=9)
        self.rahmen.pack()

        self.titel_lbl = tk.Label(self.rahmen, text=self.t("titel"),
                                  fg=FARBEN["titel"], bg=FARBEN["bg"],
                                  font=("Segoe UI", 9, "bold"))
        self.titel_lbl.pack(anchor="w")

        self.koerper = tk.Frame(self.rahmen, bg=FARBEN["bg"])
        self.koerper.pack(fill="x")

        self.status_lbl = tk.Label(self.rahmen, text=self.t("lade"),
                                   fg=FARBEN["leise"], bg=FARBEN["bg"],
                                   font=("Segoe UI", 8))
        self.status_lbl.pack(anchor="w")

        self._binde(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.beenden)

    def _binde(self, widget):
        widget.bind("<Button-1>", self._zieh_start)
        widget.bind("<B1-Motion>", self._zieh)
        widget.bind("<ButtonRelease-1>", self._zieh_ende)
        widget.bind("<Double-Button-1>", self._umschalten)
        for kind in widget.winfo_children():
            self._binde(kind)

    def _zieh_start(self, e):
        self._versatz = (e.x_root - self.root.winfo_x(),
                         e.y_root - self.root.winfo_y())

    def _zieh(self, e):
        ox, oy = getattr(self, "_versatz", (0, 0))
        x, y = e.x_root - ox, e.y_root - oy
        self.root.geometry(f"+{x}+{y}")
        # Nur merken, nicht schreiben: sonst schriebe jede einzelne
        # Mausbewegung die Einstellungsdatei auf die Platte.
        self.cfg["pos_x"], self.cfg["pos_y"] = x, y

    def _zieh_ende(self, _e=None):
        x, y = auf_bildschirm(int(self.cfg.get("pos_x", 60)),
                              int(self.cfg.get("pos_y", 60)))
        if (x, y) != (self.cfg.get("pos_x"), self.cfg.get("pos_y")):
            self.root.geometry(f"+{x}+{y}")
            self.cfg["pos_x"], self.cfg["pos_y"] = x, y
        speichere_einstellungen(self.cfg)

    def _umschalten(self, _e=None):
        self.kompakt = not self.kompakt
        self.cfg["kompakt"] = self.kompakt
        speichere_einstellungen(self.cfg)
        self._zeichnen()

    def _zur_mitte(self):
        vx, vy, vw, vh = virtueller_bildschirm()
        x, y = vx + vw // 2 - 115, vy + vh // 2 - 60
        self.root.geometry(f"+{x}+{y}")
        self.cfg["pos_x"], self.cfg["pos_y"] = x, y
        speichere_einstellungen(self.cfg)
        if not self.sichtbar:
            self._sichtbarkeit()

    # ---------------------------------------------------------------- Zeichnen

    def _zeile(self, eltern, links, rechts, anteil, fett=False, farbe=None):
        zeile = tk.Frame(eltern, bg=FARBEN["bg"])
        zeile.pack(fill="x", pady=(4, 0))
        kopf = tk.Frame(zeile, bg=FARBEN["bg"])
        kopf.pack(fill="x")
        tk.Label(kopf, text=links, fg=FARBEN["text"], bg=FARBEN["bg"],
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Label(kopf, text=rechts, fg=farbe or FARBEN["titel"], bg=FARBEN["bg"],
                 font=("Segoe UI", 9, "bold" if fett else "normal")).pack(side="right")
        if anteil is not None:
            hg = tk.Frame(zeile, bg=FARBEN["balken_bg"], width=BAR_W, height=BAR_H)
            hg.pack(fill="x", pady=(2, 0))
            hg.pack_propagate(False)
            breite = max(1, int(BAR_W * max(0.0, min(1.0, anteil))))
            tk.Frame(hg, bg=FARBEN["balken"], width=breite, height=BAR_H).place(x=0, y=0)

    def _zeichnen(self):
        for w in self.koerper.winfo_children():
            w.destroy()
        r = self.ergebnis
        if not r:
            self._binde(self.root)
            return

        jetzt = time.time()

        if self.kompakt:
            tk.Label(self.koerper,
                     text=self.t("heute") + ": " + zahl(r["heute"]["echt"]),
                     fg=FARBEN["titel"], bg=FARBEN["bg"],
                     font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(2, 0))
            self._binde(self.root)
            return

        # --- laufender Block ---
        if r["block_bis"]:
            rest = r["block_bis"] - jetzt
            if rest > 0:
                zusatz = self.t("endetIn") + " " + dauer_kurz(rest, self.sprache)
                anteil = 1.0 - rest / (BLOCK_STUNDEN * 3600)
                farbe = FARBEN["titel"]
            else:
                zusatz = self.t("abgelaufen")
                anteil = 1.0
                farbe = FARBEN["leise"]
            von = datetime.fromtimestamp(r["block_von"]).strftime("%H:%M")
            self._zeile(self.koerper,
                        self.t("block") + " " + von + " (" + self.t("blockGeschaetzt") + ")",
                        zahl(r["block"]["echt"]), anteil, fett=True, farbe=farbe)
            tk.Label(self.koerper, text=zusatz, fg=FARBEN["leise"], bg=FARBEN["bg"],
                     font=("Segoe UI", 8)).pack(anchor="e")

        # --- heute ---
        n = r["heute"]["anzahl"]
        wort = self.t("antworten_1") if n == 1 else self.t("antworten_n")
        self._zeile(self.koerper, self.t("heute"), zahl(r["heute"]["echt"]),
                    None, fett=True)
        tk.Label(self.koerper, text=str(n) + " " + wort, fg=FARBEN["leise"],
                 bg=FARBEN["bg"], font=("Segoe UI", 8)).pack(anchor="e")

        # --- Modelle im laufenden Block ---
        if r["modelle"]:
            groesstes = r["modelle"][0][1] or 1
            for name, wert in r["modelle"][:3]:
                self._zeile(self.koerper, kurz_modell(name), zahl(wert),
                            wert / groesstes)

        self._binde(self.root)

    # ---------------------------------------------------------------- Tray

    def _tray_bild(self):
        img = Image.new("RGBA", (64, 64), (20, 26, 12, 255))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([8, 16, 56, 46], radius=5,
                            outline=FARBEN["titel"], width=3)
        d.rectangle([15, 22, 23, 40], fill=FARBEN["titel"])
        d.rectangle([27, 27, 35, 40], fill=FARBEN["titel"])
        d.rectangle([39, 33, 47, 40], fill=FARBEN["titel"])
        return img

    def _baue_tray(self):
        eintraege = []
        for code in TEXTE:
            eintraege.append(pystray.MenuItem(
                TEXTE[code]["_name"],
                (lambda c: (lambda *_: self.ui_queue.put(("sprache", c))))(code),
                checked=(lambda c: (lambda item: self.sprache == c))(code),
                radio=True))
        sprachen = pystray.Menu(*eintraege)

        menue = pystray.Menu(
            pystray.MenuItem(self.t("mOverlay"),
                             lambda *_: self.ui_queue.put(("sichtbar", None)),
                             default=True),
            pystray.MenuItem(self.t("mMitte"),
                             lambda *_: self.ui_queue.put(("mitte", None))),
            pystray.MenuItem(self.t("mJetzt"),
                             lambda *_: self.wake_event.set()),
            pystray.MenuItem(self.t("mSprache"), sprachen),
            pystray.MenuItem(self.t("mBeenden"),
                             lambda *_: self.ui_queue.put(("ende", None))),
        )
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        self.icon = pystray.Icon("zaehlwerk_ticker", self._tray_bild(),
                                 "Zaehlwerk Ticker", menue)
        threading.Thread(target=self.icon.run, daemon=True).start()

    # ---------------------------------------------------------------- Schleife

    def _schleife(self):
        while not self.stop_event.is_set():
            self._einmal_lesen()
            frist = time.monotonic() + AKTUALISIERUNG
            while not self.stop_event.is_set():
                rest = frist - time.monotonic()
                if rest <= 0:
                    break
                if self.wake_event.wait(timeout=min(0.25, rest)):
                    self.wake_event.clear()
                    break

    def _einmal_lesen(self):
        if not self._lese_sperre.acquire(blocking=False):
            return
        try:
            if not self.protokolle.ordner_da():
                self.ui_queue.put(("kein_ordner", None))
                return
            self.protokolle.einlesen()
            self.ui_queue.put(("daten", auswerten(self.protokolle.antworten)))
        except Exception as e:          # Lesen darf niemals das Fenster mitreissen
            self.ui_queue.put(("fehler", str(e)))
        finally:
            self._lese_sperre.release()

    def _queue_abarbeiten(self):
        try:
            while True:
                art, last = self.ui_queue.get_nowait()
                if art == "daten":
                    self.ergebnis = last
                    self.status_lbl.config(
                        text=datetime.now().strftime(self.t("aktualisiert")),
                        fg=FARBEN["leise"])
                    self._zeichnen()
                elif art == "kein_ordner":
                    self.status_lbl.config(text=self.t("keinOrdner"), fg=FARBEN["warn"])
                elif art == "fehler":
                    self.status_lbl.config(text=str(last)[:40], fg=FARBEN["warn"])
                elif art == "sichtbar":
                    self._sichtbarkeit()
                elif art == "mitte":
                    self._zur_mitte()
                elif art == "sprache":
                    self._sprache_setzen(last)
                elif art == "ende":
                    self.beenden()
                    return
        except queue.Empty:
            pass
        self.root.after(200, self._queue_abarbeiten)

    def _sprache_setzen(self, code):
        if code not in TEXTE or code == self.sprache:
            return
        self.sprache = code
        self.cfg["sprache"] = code
        speichere_einstellungen(self.cfg)
        self.titel_lbl.config(text=self.t("titel"))
        self._zeichnen()
        self._baue_tray()               # Menuebeschriftungen neu aufbauen

    def _sichtbarkeit(self):
        self.sichtbar = not self.sichtbar
        if self.sichtbar:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
        else:
            self.root.withdraw()

    def beenden(self):
        self.stop_event.set()
        self.wake_event.set()
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        sperre_freigeben()

    def start(self):
        self.root.mainloop()


# ------------------------------ Start ---------------------------------------

if __name__ == "__main__":
    if not sperre_holen():
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showinfo("Zaehlwerk Ticker", TEXTE[systemsprache()]["laeuftBereits"])
        _r.destroy()
        sys.exit(0)
    try:
        TickerApp().start()
    except KeyboardInterrupt:
        pass
    finally:
        sperre_freigeben()
