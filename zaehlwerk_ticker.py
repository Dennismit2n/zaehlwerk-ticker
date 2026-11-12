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
import math
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
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except ImportError:
    print("Bitte zuerst installieren:  pip install pystray pillow")
    sys.exit(1)

VERSION = "1.2"

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
# 14 Sprachen wie die Browser-Fassung und die Startseite, von Hand geschrieben.
# Mengen stehen als Mehrzahlformen (one/few/many/other) mit Platzhalter {n}.

TEXTE = {
    "de": {
        "_name": "Deutsch",
        "titel": "Zählwerk",
        "block": "Block",
        "blockGeschaetzt": "geschätzt",
        "heute": "Heute",
        "endetIn": "endet in",
        "abgelaufen": "abgelaufen",
        "antworten": {"one": "{n} Antwort", "other": "{n} Antworten"},
        "lade": "lese Protokolle …",
        "keineDaten": "Noch keine Nutzung heute",
        "keinOrdner": "Ordner nicht gefunden",
        "keinOrdnerLang": "Der Ordner mit den Protokollen wurde nicht gefunden:\n\n{pfad}\n\nEr entsteht, sobald Claude Code das erste Mal gelaufen ist.",
        "aktualisiert": "aktualisiert {zeit}",
        "mOverlay": "Overlay an/aus",
        "mMitte": "Overlay zur Mitte holen",
        "mJetzt": "Jetzt aktualisieren",
        "mSprache": "Sprache",
        "mBrowser": "Ausführliche Auswertung im Browser",
        "mBeenden": "Beenden",
        "laeuftBereits": "Der Zählwerk Ticker läuft bereits.\n\nDas Symbol steckt im Infobereich der Taskleiste, Rechtsklick darauf.",
    },
    "en": {
        "_name": "English",
        "titel": "Zählwerk",
        "block": "Block",
        "blockGeschaetzt": "estimated",
        "heute": "Today",
        "endetIn": "ends in",
        "abgelaufen": "expired",
        "antworten": {"one": "{n} reply", "other": "{n} replies"},
        "lade": "reading logs …",
        "keineDaten": "No usage today yet",
        "keinOrdner": "Folder not found",
        "keinOrdnerLang": "The folder holding the logs was not found:\n\n{pfad}\n\nIt appears once Claude Code has run for the first time.",
        "aktualisiert": "updated {zeit}",
        "mOverlay": "Show/hide overlay",
        "mMitte": "Bring overlay to centre",
        "mJetzt": "Refresh now",
        "mSprache": "Language",
        "mBrowser": "Full analysis in the browser",
        "mBeenden": "Quit",
        "laeuftBereits": "Zählwerk Ticker is already running.\n\nIts icon sits in the notification area, right-click it.",
    },
    "es": {
        "_name": "Español",
        "titel": "Zählwerk",
        "block": "Bloque",
        "blockGeschaetzt": "estimado",
        "heute": "Hoy",
        "endetIn": "termina en",
        "abgelaufen": "terminado",
        "antworten": {"one": "{n} respuesta", "other": "{n} respuestas"},
        "lade": "leyendo registros …",
        "keineDaten": "Todavía no hay uso hoy",
        "keinOrdner": "Carpeta no encontrada",
        "keinOrdnerLang": "No se encontró la carpeta con los registros:\n\n{pfad}\n\nAparece en cuanto Claude Code se ejecuta por primera vez.",
        "aktualisiert": "actualizado {zeit}",
        "mOverlay": "Mostrar/ocultar overlay",
        "mMitte": "Traer el overlay al centro",
        "mJetzt": "Actualizar ahora",
        "mSprache": "Idioma",
        "mBrowser": "Análisis completo en el navegador",
        "mBeenden": "Salir",
        "laeuftBereits": "Zählwerk Ticker ya está en marcha.\n\nSu icono está en el área de notificación: haz clic derecho en él.",
    },
    "fr": {
        "_name": "Français",
        "titel": "Zählwerk",
        "block": "Bloc",
        "blockGeschaetzt": "estimé",
        "heute": "Aujourd’hui",
        "endetIn": "se termine dans",
        "abgelaufen": "terminé",
        "antworten": {"one": "{n} réponse", "other": "{n} réponses"},
        "lade": "lecture des journaux …",
        "keineDaten": "Pas encore d’utilisation aujourd’hui",
        "keinOrdner": "Dossier introuvable",
        "keinOrdnerLang": "Le dossier des journaux est introuvable :\n\n{pfad}\n\nIl apparaît dès que Claude Code a été lancé une première fois.",
        "aktualisiert": "mis à jour {zeit}",
        "mOverlay": "Afficher/masquer l’overlay",
        "mMitte": "Ramener l’overlay au centre",
        "mJetzt": "Actualiser maintenant",
        "mSprache": "Langue",
        "mBrowser": "Analyse complète dans le navigateur",
        "mBeenden": "Quitter",
        "laeuftBereits": "Zählwerk Ticker est déjà lancé.\n\nSon icône se trouve dans la zone de notification : faites un clic droit dessus.",
    },
    "it": {
        "_name": "Italiano",
        "titel": "Zählwerk",
        "block": "Blocco",
        "blockGeschaetzt": "stimato",
        "heute": "Oggi",
        "endetIn": "termina tra",
        "abgelaufen": "scaduto",
        "antworten": {"one": "{n} risposta", "other": "{n} risposte"},
        "lade": "lettura dei registri …",
        "keineDaten": "Ancora nessun utilizzo oggi",
        "keinOrdner": "Cartella non trovata",
        "keinOrdnerLang": "Non ho trovato la cartella con i registri:\n\n{pfad}\n\nCompare appena Claude Code viene avviato la prima volta.",
        "aktualisiert": "aggiornato {zeit}",
        "mOverlay": "Mostra/nascondi overlay",
        "mMitte": "Riporta l’overlay al centro",
        "mJetzt": "Aggiorna ora",
        "mSprache": "Lingua",
        "mBrowser": "Analisi completa nel browser",
        "mBeenden": "Esci",
        "laeuftBereits": "Zählwerk Ticker è già in esecuzione.\n\nLa sua icona è nell’area di notifica: fai clic destro su di essa.",
    },
    "nl": {
        "_name": "Nederlands",
        "titel": "Zählwerk",
        "block": "Blok",
        "blockGeschaetzt": "geschat",
        "heute": "Vandaag",
        "endetIn": "eindigt over",
        "abgelaufen": "verlopen",
        "antworten": {"one": "{n} antwoord", "other": "{n} antwoorden"},
        "lade": "logboeken lezen …",
        "keineDaten": "Vandaag nog geen gebruik",
        "keinOrdner": "Map niet gevonden",
        "keinOrdnerLang": "De map met de logboeken is niet gevonden:\n\n{pfad}\n\nDie ontstaat zodra Claude Code voor het eerst heeft gedraaid.",
        "aktualisiert": "bijgewerkt {zeit}",
        "mOverlay": "Overlay tonen/verbergen",
        "mMitte": "Overlay naar het midden halen",
        "mJetzt": "Nu bijwerken",
        "mSprache": "Taal",
        "mBrowser": "Uitgebreide analyse in de browser",
        "mBeenden": "Afsluiten",
        "laeuftBereits": "Zählwerk Ticker draait al.\n\nHet pictogram staat in het systeemvak: klik er met rechts op.",
    },
    "pl": {
        "_name": "Polski",
        "titel": "Zählwerk",
        "block": "Blok",
        "blockGeschaetzt": "szacunkowo",
        "heute": "Dziś",
        "endetIn": "kończy się za",
        "abgelaufen": "minął",
        "antworten": {"one": "{n} odpowiedź", "few": "{n} odpowiedzi", "many": "{n} odpowiedzi", "other": "{n} odpowiedzi"},
        "lade": "czytam dzienniki …",
        "keineDaten": "Dziś jeszcze bez użycia",
        "keinOrdner": "Nie znaleziono folderu",
        "keinOrdnerLang": "Nie znaleziono folderu z dziennikami:\n\n{pfad}\n\nPowstaje, gdy Claude Code uruchomi się pierwszy raz.",
        "aktualisiert": "aktualizacja {zeit}",
        "mOverlay": "Pokaż/ukryj nakładkę",
        "mMitte": "Przenieś nakładkę na środek",
        "mJetzt": "Odśwież teraz",
        "mSprache": "Język",
        "mBrowser": "Pełna analiza w przeglądarce",
        "mBeenden": "Zakończ",
        "laeuftBereits": "Zählwerk Ticker już działa.\n\nIkona jest w obszarze powiadomień: kliknij ją prawym przyciskiem.",
    },
    "pt": {
        "_name": "Português",
        "titel": "Zählwerk",
        "block": "Bloco",
        "blockGeschaetzt": "estimado",
        "heute": "Hoje",
        "endetIn": "termina em",
        "abgelaufen": "expirado",
        "antworten": {"one": "{n} resposta", "other": "{n} respostas"},
        "lade": "lendo registros …",
        "keineDaten": "Ainda sem uso hoje",
        "keinOrdner": "Pasta não encontrada",
        "keinOrdnerLang": "A pasta com os registros não foi encontrada:\n\n{pfad}\n\nEla aparece assim que o Claude Code roda pela primeira vez.",
        "aktualisiert": "atualizado {zeit}",
        "mOverlay": "Mostrar/ocultar overlay",
        "mMitte": "Trazer o overlay para o centro",
        "mJetzt": "Atualizar agora",
        "mSprache": "Idioma",
        "mBrowser": "Análise completa no navegador",
        "mBeenden": "Sair",
        "laeuftBereits": "O Zählwerk Ticker já está em execução.\n\nO ícone fica na área de notificação: clique nele com o botão direito.",
    },
    "tr": {
        "_name": "Türkçe",
        "titel": "Zählwerk",
        "block": "Blok",
        "blockGeschaetzt": "tahmini",
        "heute": "Bugün",
        "endetIn": "kalan",
        "abgelaufen": "süresi doldu",
        "antworten": {"one": "{n} yanıt", "other": "{n} yanıt"},
        "lade": "günlükler okunuyor …",
        "keineDaten": "Bugün henüz kullanım yok",
        "keinOrdner": "Klasör bulunamadı",
        "keinOrdnerLang": "Günlüklerin bulunduğu klasör bulunamadı:\n\n{pfad}\n\nClaude Code ilk kez çalıştığında oluşur.",
        "aktualisiert": "güncellendi {zeit}",
        "mOverlay": "Katmanı göster/gizle",
        "mMitte": "Katmanı ortaya getir",
        "mJetzt": "Şimdi güncelle",
        "mSprache": "Dil",
        "mBrowser": "Tarayıcıda ayrıntılı analiz",
        "mBeenden": "Çık",
        "laeuftBereits": "Zählwerk Ticker zaten çalışıyor.\n\nSimgesi bildirim alanında: üzerine sağ tıklayın.",
    },
    "ru": {
        "_name": "Русский",
        "titel": "Zählwerk",
        "block": "Блок",
        "blockGeschaetzt": "оценка",
        "heute": "Сегодня",
        "endetIn": "закончится через",
        "abgelaufen": "истёк",
        "antworten": {"one": "{n} ответ", "few": "{n} ответа", "many": "{n} ответов", "other": "{n} ответа"},
        "lade": "читаю журналы …",
        "keineDaten": "Сегодня ещё нет использования",
        "keinOrdner": "Папка не найдена",
        "keinOrdnerLang": "Папка с журналами не найдена:\n\n{pfad}\n\nОна появится после первого запуска Claude Code.",
        "aktualisiert": "обновлено {zeit}",
        "mOverlay": "Показать/скрыть оверлей",
        "mMitte": "Вернуть оверлей в центр",
        "mJetzt": "Обновить сейчас",
        "mSprache": "Язык",
        "mBrowser": "Подробный анализ в браузере",
        "mBeenden": "Выход",
        "laeuftBereits": "Zählwerk Ticker уже запущен.\n\nЗначок находится в области уведомлений: щёлкните по нему правой кнопкой.",
    },
    "hi": {
        "_name": "हिन्दी",
        "titel": "Zählwerk",
        "block": "ब्लॉक",
        "blockGeschaetzt": "अनुमानित",
        "heute": "आज",
        "endetIn": "शेष",
        "abgelaufen": "समाप्त",
        "antworten": {"one": "{n} उत्तर", "other": "{n} उत्तर"},
        "lade": "लॉग पढ़ रहे हैं …",
        "keineDaten": "आज अभी कोई उपयोग नहीं",
        "keinOrdner": "फ़ोल्डर नहीं मिला",
        "keinOrdnerLang": "लॉग वाला फ़ोल्डर नहीं मिला:\n\n{pfad}\n\nयह Claude Code के पहली बार चलने पर बनता है।",
        "aktualisiert": "अपडेट {zeit}",
        "mOverlay": "ओवरले दिखाएँ/छिपाएँ",
        "mMitte": "ओवरले को बीच में लाएँ",
        "mJetzt": "अभी अपडेट करें",
        "mSprache": "भाषा",
        "mBrowser": "ब्राउज़र में पूरा विश्लेषण",
        "mBeenden": "बंद करें",
        "laeuftBereits": "Zählwerk Ticker पहले से चल रहा है।\n\nइसका आइकन सूचना क्षेत्र में है: उस पर राइट-क्लिक करें।",
    },
    "zh": {
        "_name": "中文",
        "titel": "Zählwerk",
        "block": "区块",
        "blockGeschaetzt": "估算",
        "heute": "今天",
        "endetIn": "剩余",
        "abgelaufen": "已过期",
        "antworten": {"other": "{n} 条回复"},
        "lade": "正在读取日志 …",
        "keineDaten": "今天还没有使用",
        "keinOrdner": "找不到文件夹",
        "keinOrdnerLang": "找不到日志所在的文件夹：\n\n{pfad}\n\nClaude Code 第一次运行后它就会出现。",
        "aktualisiert": "更新于 {zeit}",
        "mOverlay": "显示/隐藏悬浮窗",
        "mMitte": "把悬浮窗移到屏幕中央",
        "mJetzt": "立即更新",
        "mSprache": "语言",
        "mBrowser": "在浏览器中查看完整分析",
        "mBeenden": "退出",
        "laeuftBereits": "Zählwerk Ticker 已在运行。\n\n它的图标在通知区域：右键单击它。",
    },
    "ja": {
        "_name": "日本語",
        "titel": "Zählwerk",
        "block": "ブロック",
        "blockGeschaetzt": "推定",
        "heute": "今日",
        "endetIn": "残り",
        "abgelaufen": "終了",
        "antworten": {"other": "{n} 件の応答"},
        "lade": "ログを読み込み中 …",
        "keineDaten": "今日はまだ使用していません",
        "keinOrdner": "フォルダーが見つかりません",
        "keinOrdnerLang": "ログのフォルダーが見つかりません：\n\n{pfad}\n\nClaude Code を初めて実行すると作成されます。",
        "aktualisiert": "更新 {zeit}",
        "mOverlay": "オーバーレイの表示/非表示",
        "mMitte": "オーバーレイを中央に戻す",
        "mJetzt": "今すぐ更新",
        "mSprache": "言語",
        "mBrowser": "ブラウザーで詳しい分析",
        "mBeenden": "終了",
        "laeuftBereits": "Zählwerk Ticker はすでに起動しています。\n\nアイコンは通知領域にあります。右クリックしてください。",
    },
    "ko": {
        "_name": "한국어",
        "titel": "Zählwerk",
        "block": "블록",
        "blockGeschaetzt": "추정",
        "heute": "오늘",
        "endetIn": "남은 시간",
        "abgelaufen": "만료됨",
        "antworten": {"other": "{n}개 응답"},
        "lade": "로그 읽는 중 …",
        "keineDaten": "오늘은 아직 사용 기록이 없습니다",
        "keinOrdner": "폴더를 찾을 수 없음",
        "keinOrdnerLang": "로그 폴더를 찾을 수 없습니다:\n\n{pfad}\n\nClaude Code를 처음 실행하면 생깁니다.",
        "aktualisiert": "업데이트 {zeit}",
        "mOverlay": "오버레이 표시/숨기기",
        "mMitte": "오버레이를 가운데로",
        "mJetzt": "지금 업데이트",
        "mSprache": "언어",
        "mBrowser": "브라우저에서 자세한 분석",
        "mBeenden": "종료",
        "laeuftBereits": "Zählwerk Ticker가 이미 실행 중입니다.\n\n아이콘은 알림 영역에 있습니다. 마우스 오른쪽 버튼으로 클릭하세요.",
    },
}


# Windows-Anzeigesprache (primäre LANGID) → Sprachcode
_LANGID = {0x07: "de", 0x09: "en", 0x0A: "es", 0x0C: "fr", 0x10: "it", 0x13: "nl", 0x15: "pl",
           0x16: "pt", 0x1F: "tr", 0x19: "ru", 0x39: "hi", 0x04: "zh", 0x11: "ja", 0x12: "ko"}


def systemsprache() -> str:
    """Windows-Anzeigesprache, wenn der Ticker sie spricht, sonst Englisch."""
    try:
        if ctypes is not None:
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return _LANGID.get(lcid & 0x3FF, "en")
    except (AttributeError, OSError):
        pass
    return "en"


def mehrzahl(n: int, sprache: str) -> str:
    """Mehrzahlform wie Intl.PluralRules im Browser: Polnisch und Russisch kennen one/few/many."""
    if sprache in ("zh", "ja", "ko"):
        return "other"
    if sprache in ("pl", "ru"):
        e, z = n % 10, n % 100
        if (n == 1) if sprache == "pl" else (e == 1 and z != 11):
            return "one"
        if 2 <= e <= 4 and not 12 <= z <= 14:
            return "few"
        return "many"
    if sprache in ("fr", "hi", "pt"):               # 0 und 1 sind dort Einzahl
        return "one" if n in (0, 1) else "other"
    return "one" if n == 1 else "other"


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


# ------------------------------ Beschlag ------------------------------------
# Der Look der Werkstatt: eine Platte mit runder Außenkante, darin ein eckiger
# Rahmen, an jeder Ecke eine kleine Schraube in Weißgold, jede anders gedreht.
# Das Licht kommt von rechts oben, darum fällt der Schatten nach links unten.
#
# tkinter kann weder weiche Schatten noch geglättete Rundungen. Deshalb liegt
# hinter der Anzeige ein zweites Fenster, das nur ein Bild zeigt (Platte,
# Rahmen, Schrauben, Schatten) und dort ein Loch hat, wo die Anzeige sitzt.

B_RADIUS = 14                          # Rundung der Platte
B_INNEN = 5                            # Abstand des Rahmens von der Kante
B_ABSTAND = 3                          # Abstand der Schraube vom Rahmen
B_SCHRAUBE = 10                        # Größe einer Schraube
B_RAND = B_INNEN + B_ABSTAND + B_SCHRAUBE   # so breit ist die Platte um die Anzeige
B_SCHATTEN = (-7, 8)                   # Versatz: nach links unten
B_WEICH = 9                            # Unschärfe des Schattens
B_LUFT = 26                            # Platz für den Schatten um die Platte
B_WINKEL = (32, -58, 78, -14)          # Schlitz je Schraube, in Grad


def _hex(farbe: str) -> tuple[int, int, int]:
    return int(farbe[1:3], 16), int(farbe[3:5], 16), int(farbe[5:7], 16)


def _mische(a: str, b: str, anteil: float) -> tuple[int, int, int]:
    """Farbe a mit dem Anteil von b."""
    x, y = _hex(a), _hex(b)
    return tuple(round(x[i] + (y[i] - x[i]) * anteil) for i in range(3))


def _verlauf(stufen, t: float):
    """Wert eines Farbverlaufs an der Stelle t. stufen: (stelle, (r, g, b, deckung))"""
    if t <= stufen[0][0]:
        return stufen[0][1]
    for (t0, f0), (t1, f1) in zip(stufen, stufen[1:]):
        if t <= t1:
            k = (t - t0) / ((t1 - t0) or 1)
            return tuple(f0[i] + (f1[i] - f0[i]) * k for i in range(4))
    return stufen[-1][1]


_KOPF = ((0.0, (255, 255, 255, 1)), (0.2, (255, 252, 238, 1)), (0.5, (241, 228, 188, 1)),
         (0.8, (196, 169, 100, 1)), (1.0, (122, 98, 38, 1)))
_RING = ((0.0, (138, 106, 34, .55)), (0.5, (255, 243, 196, 0)), (1.0, (255, 251, 234, .7)))
_SCHRAUBEN: dict = {}


def schraube(winkel: float, groesse: int = B_SCHRAUBE):
    """Eine Schraube in Weißgold, Punkt für Punkt gerechnet: Schatten nach
    links unten, gewölbter Kopf, Schlitz im Winkel, Glanzpunkt rechts oben.
    Dieselbe Zeichnung wie auf der Startseite, dort als SVG auf 12 × 12."""
    if (winkel, groesse) in _SCHRAUBEN:
        return _SCHRAUBEN[(winkel, groesse)]
    n = groesse * 6                    # sechsfach gerechnet, dann verkleinert: glatte Kanten
    co, si = math.cos(math.radians(-winkel)), math.sin(math.radians(-winkel))
    gc, gs = math.cos(math.radians(35)), math.sin(math.radians(35))
    punkte = []

    def strich(x, y, x0, x1, y0):
        """Abstand zu einer waagrechten Strecke mit runden Enden"""
        return math.hypot(x - max(x0, min(x1, x)), y - y0)

    for j in range(n):
        v = (j + .5) * 12 / n
        for i in range(n):
            u = (i + .5) * 12 / n
            r = g = b = a = 0.0        # Farbe mal Deckung, wird Schicht für Schicht belegt

            def auf(farbe, deckung):
                nonlocal r, g, b, a
                r = farbe[0] * deckung + r * (1 - deckung)
                g = farbe[1] * deckung + g * (1 - deckung)
                b = farbe[2] * deckung + b * (1 - deckung)
                a = deckung + a * (1 - deckung)

            # Schatten der Schraube auf der Platte
            if math.hypot(u - 5.1, v - 6.9) <= 5:
                t = math.hypot(u - 4.3, v - 7.7) / 5
                auf((0, 0, 0), .6 if t <= .55 else max(0.0, .6 * (1 - (t - .55) / .45)))
            m = math.hypot(u - 6, v - 6)
            # Kopf, heller Fleck rechts oben
            if m <= 4.3:
                f = _verlauf(_KOPF, math.hypot(u - 7.376, v - 4.28) / 6.708)
                auf(f, 1)
            # dunkle Kante
            if abs(m - 4.3) <= .225:
                auf((85, 62, 12), .6)
            # feiner Ring: oben rechts dunkel, unten links hell
            if abs(m - 2.9) <= .25:
                f = _verlauf(_RING, ((8.9 - u) / 5.8 + (v - 3.1) / 5.8) / 2)
                auf(f, f[3])
            # Schlitz und sein heller Rand
            x = 6 + (u - 6) * co - (v - 6) * si
            y = 6 + (u - 6) * si + (v - 6) * co
            if strich(x, y, 2.5, 9.5, 6) <= .6:
                auf((58, 42, 7), 1)
            if strich(x, y, 2.7, 9.3, 6.62) <= .15:
                auf((255, 247, 218), .75)
            # Glanzpunkt
            ex = (u - 7.7) * gc - (v - 3.9) * gs
            ey = (u - 7.7) * gs + (v - 3.9) * gc
            if (ex / 1.05) ** 2 + (ey / .6) ** 2 <= 1:
                auf((255, 255, 255), .9)
            punkte.append((round(r), round(g), round(b), round(a * 255)))

    bild = Image.new("RGBa", (n, n))
    bild.putdata(punkte)
    bild = bild.resize((groesse, groesse), Image.LANCZOS).convert("RGBA")
    _SCHRAUBEN[(winkel, groesse)] = bild
    return bild


def beschlag_bild(w: int, h: int, deckkraft: float):
    """Das Bild hinter einer Anzeige von w × h Punkten: Schatten, Platte,
    Rahmen, Schrauben. Wo die Anzeige sitzt, bleibt es durchsichtig."""
    pw, ph = w + 2 * B_RAND, h + 2 * B_RAND
    bw, bh = pw + 2 * B_LUFT, ph + 2 * B_LUFT
    k = 4                              # Platte vierfach zeichnen, dann verkleinern

    form = Image.new("L", (bw * k, bh * k), 0)
    kante = [B_LUFT * k, B_LUFT * k, (B_LUFT + pw) * k - 1, (B_LUFT + ph) * k - 1]
    ImageDraw.Draw(form).rounded_rectangle(kante, radius=B_RADIUS * k, fill=255)

    gross = Image.new("RGB", (bw * k, bh * k), _hex(FARBEN["bg"]))
    d = ImageDraw.Draw(gross)
    d.rounded_rectangle(kante, radius=B_RADIUS * k, width=k,
                        outline=_mische(FARBEN["bg"], FARBEN["titel"], .20))
    i = (B_LUFT + B_INNEN) * k
    d.rectangle([i, i, (B_LUFT + pw - B_INNEN) * k - 1, (B_LUFT + ph - B_INNEN) * k - 1],
                width=k, outline=_mische(FARBEN["bg"], FARBEN["titel"], .34))
    platte = gross.resize((bw, bh), Image.LANCZOS).convert("RGBA")
    form = form.resize((bw, bh), Image.LANCZOS)
    platte.putalpha(form)

    # Schatten: dieselbe Form, versetzt und weich. Unter der Platte selbst
    # ausgespart, sonst wäre sie dunkler als die Anzeige in ihrer Mitte.
    schatten = ImageChops.offset(form, B_SCHATTEN[0], B_SCHATTEN[1])
    schatten = schatten.filter(ImageFilter.GaussianBlur(B_WEICH)).point(lambda v: int(v * .62))
    schatten = ImageChops.multiply(schatten, ImageChops.invert(form))
    bild = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bild.putalpha(schatten)
    bild.alpha_composite(platte)

    links = B_LUFT + B_INNEN + B_ABSTAND
    rechts = B_LUFT + pw - B_INNEN - B_ABSTAND - B_SCHRAUBE
    unten = B_LUFT + ph - B_INNEN - B_ABSTAND - B_SCHRAUBE
    for (x, y), winkel in zip(((links, links), (rechts, links), (links, unten), (rechts, unten)),
                              B_WINKEL):
        bild.alpha_composite(schraube(winkel), (x, y))

    loch = B_LUFT + B_RAND
    bild.paste((0, 0, 0, 0), (loch, loch, loch + w, loch + h))
    if deckkraft < 1:
        bild.putalpha(bild.getchannel("A").point(lambda v: int(v * deckkraft)))
    return bild


# Windows zeigt ein Bild mit weichen Kanten nur über ein „geschichtetes"
# Fenster. Das Bild wird dem Fenster direkt übergeben, tkinter malt dort nichts.

if ctypes is not None:
    class _PUNKT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _MASS(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class _MISCHUNG(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class _BILDKOPF(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

_WIN = None


def _win():
    """user32 und gdi32 mit sauberen Typen (64-Bit-Zeiger), einmal eingerichtet."""
    global _WIN
    if _WIN is None:
        z, p = ctypes.c_void_p, ctypes.POINTER
        u, g = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
        u.GetAncestor.restype, u.GetAncestor.argtypes = z, [z, ctypes.c_uint]
        u.GetDC.restype, u.GetDC.argtypes = z, [z]
        u.ReleaseDC.argtypes = [z, z]
        u.GetWindowLongPtrW.restype, u.GetWindowLongPtrW.argtypes = ctypes.c_ssize_t, [z, ctypes.c_int]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [z, ctypes.c_int, ctypes.c_ssize_t]
        u.UpdateLayeredWindow.argtypes = [z, z, p(_PUNKT), p(_MASS), z, p(_PUNKT),
                                          ctypes.c_uint32, p(_MISCHUNG), ctypes.c_uint32]
        g.CreateCompatibleDC.restype, g.CreateCompatibleDC.argtypes = z, [z]
        g.CreateDIBSection.restype = z
        g.CreateDIBSection.argtypes = [z, p(_BILDKOPF), ctypes.c_uint, p(z), z, ctypes.c_uint32]
        g.SelectObject.restype, g.SelectObject.argtypes = z, [z, z]
        g.DeleteObject.argtypes = [z]
        g.DeleteDC.argtypes = [z]
        _WIN = (u, g)
    return _WIN


def schicht_vorbereiten(tk_id: int) -> int:
    """Macht aus einem tkinter-Fenster ein geschichtetes. Rückgabe: sein Handle."""
    u, _ = _win()
    hwnd = u.GetAncestor(tk_id, 2) or tk_id
    stil = u.GetWindowLongPtrW(hwnd, -20)
    u.SetWindowLongPtrW(hwnd, -20, stil | 0x00080000 | 0x00000080)   # geschichtet, kein Taskleisten-Knopf
    return hwnd


def schicht_zeigen(hwnd: int, bild, x: int, y: int) -> bool:
    """Legt das Bild (mit Durchsicht je Punkt) an die Stelle x, y auf den Bildschirm."""
    u, g = _win()
    w, h = bild.size
    # Windows will Farbe mal Deckung (gerundet, sonst sieht man die Naht zur
    # Anzeige), Reihenfolge Blau-Grün-Rot
    roh = bild.convert("RGBa").tobytes("raw", "BGRa")
    kopf = _BILDKOPF(ctypes.sizeof(_BILDKOPF), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    schirm = u.GetDC(None)
    speicher = g.CreateCompatibleDC(schirm)
    stelle = ctypes.c_void_p()
    karte = g.CreateDIBSection(schirm, ctypes.byref(kopf), 0, ctypes.byref(stelle), None, 0)
    if not karte or not stelle:
        g.DeleteDC(speicher)
        u.ReleaseDC(None, schirm)
        return False
    ctypes.memmove(stelle, roh, len(roh))
    alt = g.SelectObject(speicher, karte)
    ok = u.UpdateLayeredWindow(hwnd, schirm, ctypes.byref(_PUNKT(x, y)), ctypes.byref(_MASS(w, h)),
                               speicher, ctypes.byref(_PUNKT(0, 0)), 0,
                               ctypes.byref(_MISCHUNG(0, 0, 255, 1)), 2)
    g.SelectObject(speicher, alt)
    g.DeleteObject(karte)
    g.DeleteDC(speicher)
    u.ReleaseDC(None, schirm)
    return bool(ok)


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


# Tausendertrenner je Sprache (ohne locale-Abhängigkeit)
_TRENNER = {"en": ",", "hi": ",", "zh": ",", "ja": ",", "ko": ",", "fr": "\u202f", "ru": "\u00a0", "pl": "\u00a0"}


def zahl(n: int, sprache: str = "de") -> str:
    """Tausendertrennung in der Schreibweise der Sprache: 1.234.567, 1,234,567, 1 234 567."""
    return f"{int(n):,}".replace(",", _TRENNER.get(sprache, "."))


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

    def tn(self, schluessel: str, n: int) -> str:
        """Text mit Menge in der passenden Mehrzahlform"""
        formen = TEXTE[self.sprache][schluessel]
        return (formen.get(mehrzahl(n, self.sprache)) or formen["other"]).replace("{n}", str(n))

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

        self._baue_platte()
        # Mit Beschlag hält die Platte den Abstand zum Rand, ohne ihn der Rahmen selbst.
        self.rahmen = tk.Frame(self.root, bg=FARBEN["bg"],
                               padx=3 if self.platte else 11, pady=1 if self.platte else 9)
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
        self.root.bind("<Configure>", self._root_bewegt, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.beenden)

    # ---------------------------------------------------------------- Beschlag

    def _baue_platte(self):
        """Das Fenster hinter der Anzeige: Platte, Rahmen, Schrauben, Schatten."""
        self.platte = None
        self._platte_hwnd = None
        self._platte_bild = None
        self._platte_mass = None
        self._platte_stand = None
        if ctypes is None or os.name != "nt":
            return
        try:
            p = tk.Toplevel(self.root)
            p.withdraw()
            p.overrideredirect(True)
            p.attributes("-topmost", True)
            p.configure(bg=FARBEN["bg"])
            p.update_idletasks()
            self._platte_hwnd = schicht_vorbereiten(p.winfo_id())
            self.platte = p
        except Exception:               # ohne Beschlag läuft die Anzeige trotzdem
            self.platte = None

    def _root_bewegt(self, e):
        if e.widget is self.root:
            self._platte_folgen()

    def _platte_folgen(self, x=None, y=None):
        """Zieht die Platte hinter die Anzeige: neue Stelle, bei Bedarf neues Bild."""
        if not self.platte or not self.sichtbar:
            return
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if w <= 1 or h <= 1:
            return
        if x is None:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        deckkraft = int(self.cfg.get("deckkraft", 88)) / 100.0
        if self._platte_mass != (w, h, deckkraft):
            self._platte_bild = beschlag_bild(w, h, deckkraft)
            self._platte_mass = (w, h, deckkraft)
        px, py = x - B_RAND - B_LUFT, y - B_RAND - B_LUFT
        if self._platte_stand == (self._platte_mass, px, py):
            return
        try:
            bw, bh = self._platte_bild.size
            self.platte.geometry(f"{bw}x{bh}+{px}+{py}")
            if schicht_zeigen(self._platte_hwnd, self._platte_bild, px, py):
                self._platte_stand = (self._platte_mass, px, py)
            if self.platte.state() == "withdrawn":
                self.platte.deiconify()
                self.root.lift()
        except (tk.TclError, OSError):
            pass

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
        self._platte_folgen(x, y)
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
                     text=self.t("heute") + ": " + zahl(r["heute"]["echt"], self.sprache),
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
                        zahl(r["block"]["echt"], self.sprache), anteil, fett=True, farbe=farbe)
            tk.Label(self.koerper, text=zusatz, fg=FARBEN["leise"], bg=FARBEN["bg"],
                     font=("Segoe UI", 8)).pack(anchor="e")

        # --- heute ---
        n = r["heute"]["anzahl"]
        self._zeile(self.koerper, self.t("heute"), zahl(r["heute"]["echt"], self.sprache),
                    None, fett=True)
        tk.Label(self.koerper, text=self.tn("antworten", n), fg=FARBEN["leise"],
                 bg=FARBEN["bg"], font=("Segoe UI", 8)).pack(anchor="e")

        # --- Modelle im laufenden Block ---
        if r["modelle"]:
            groesstes = r["modelle"][0][1] or 1
            for name, wert in r["modelle"][:3]:
                self._zeile(self.koerper, kurz_modell(name), zahl(wert, self.sprache),
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
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("© 2026 Dennis_mit_2n", None, enabled=False),
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
                        text=self.t("aktualisiert").replace("{zeit}", datetime.now().strftime("%H:%M:%S")),
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
            self._platte_stand = None
            self.root.after(30, self._platte_folgen)
        else:
            self.root.withdraw()
            if self.platte:
                self.platte.withdraw()

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
