# Zählwerk Ticker 📊

**Keep an eye on usage while you work.** A small floating readout for Windows: current five-hour block, daily total, breakdown by model. Reads nothing but the log files Claude Code writes onto your own disk.

![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-a3e635) ![No network](https://img.shields.io/badge/Network%20access-none-4d7c0f) ![Languages](https://img.shields.io/badge/Languages-DE%20%7C%20EN-65a30d) ![Licence](https://img.shields.io/badge/Licence-MIT-6ee7b7)

**Full analysis in the browser: [Zählwerk](https://dennismit2n.github.io/zaehlwerk/)** · [Deutsche Fassung](README.de.md)

---

## What it is for

The browser version is for sitting down and studying. This one is for running alongside: it sits in a corner of the screen and answers a single question — *how much of the current window is gone, and when does it flip?*

## What it shows

| | |
|---|---|
| **Block** | usage in the running five-hour window, with a bar and the time remaining |
| **Today** | daily total and number of replies |
| **Models** | the top three in the current block |

## What it does NOT show

- **No percentage of an allowance.** How much you have left is not in these files. The ticker can only count what has been spent — a bar against a limit would be invented.
- **No costs.** The logs contain no prices, and on a subscription Claude Code costs nothing extra.
- **Claude Code only.** What you do on claude.ai in the browser leaves no logs on disk.

## About the five-hour block

Exactly when a new window starts is **not documented** by Anthropic. The ticker reconstructs it from the timestamps: the first window begins with the first reply and runs five hours; the first reply after that starts the next one — regardless of whether there was a pause in between. That chains forward to the current window.

This is a reasoned assumption, not a confirmed fact. Hence the label **"estimated"** in the readout, and hence this paragraph.

## Getting started

**With the prebuilt exe** — download it from [Releases](../../releases/latest), put it anywhere, double-click. On first launch Windows will say "Unknown publisher": the file is not signed, which costs money. Use **More info → Run anyway**.

**From source:**

```
pip install pystray pillow
pythonw zaehlwerk_ticker.py
```

## Controls

| | |
|---|---|
| Drag | move the overlay — position is remembered when you let go |
| Double-click | switch between small and large |
| Right-click the tray icon | show/hide, bring to centre, refresh now, language, quit |

Lost it? **Bring overlay to centre** in the menu. This happens when a second monitor is unplugged — the overlay is frameless and has no title bar to grab.

## Privacy

**There is no network access.** Not "we don't send anything", but: the capability is not built in at all. Verifiable from the program's import list — `requests`, `urllib`, `socket`, `http` and `webbrowser` do not appear in it. No update check, no telemetry, no identifier.

The only files read are the `.jsonl` logs under `%USERPROFILE%\.claude\projects`, and from those only the accounting lines: timestamp, model name and the four token figures. Conversation content is neither analysed nor displayed.

Exactly one file is written: `einstellungen.json` next to the program, holding position, opacity, language and the small/large state. No log, no cache.

## Under the hood

One file, roughly 810 lines, two third-party packages (`pystray`, `pillow`) — everything else is the Python standard library.

**Two things decide whether the numbers are right:**

1. **De-duplication by `message.id`.** A reply appears several times in the log — once per block it consists of (thinking, text, tool call) — and *each* of those lines carries the full accounting. On real data, naive addition yields more than double.
2. **Incremental reading.** Everything is read once at startup (about 0.6 seconds for 16,000 lines); after that only the newly appended part of each file, which typically takes under 10 milliseconds. A partially written final line is deliberately left alone and only read once complete.

**The log format is not documented.** If Anthropic changes it, the ticker will show too little or nothing at all.

## Licence

MIT — see [LICENSE](LICENSE).

---

Zählwerk Ticker is a personal tool and is **not affiliated with Anthropic**. "Claude" is a trademark of Anthropic PBC.

Part of the [workshop](https://dennismit2n.github.io/) by Dennis_mit_2n.
