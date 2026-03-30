# ♠ GTO Poker Tournament Advisor

A local web-based GTO-approximated decision engine for online tournament poker. Run it alongside your tournament client and get real-time preflop and postflop advice with bet sizing.

![Python](https://img.shields.io/badge/Python-3.8+-blue) ![Flask](https://img.shields.io/badge/Flask-3.0+-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

- **Preflop Advisor** — Input your hole cards, position, stack size, and the action you're facing. Get GTO-approximated open-raise, 3-bet, call/fold, and push/fold recommendations with exact sizing.
- **Postflop Advisor** — Input hole cards + community cards, pot size, and villain action. Get board texture analysis, hand strength evaluation, and bet/check/fold recommendations.
- **Range Charts** — Quick-reference open-raise ranges by position and stack depth.
- **Nash Push/Fold** — Short-stack (≤15 BB) recommendations based on Nash equilibrium charts.
- **Tournament-Aware** — Stack-depth adjustments for tournament play (tighter ranges at shallow stacks).

---

## Quick Start

### Prerequisites

- Python 3.8+
- pip

### Installation

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/gto-advisor.git
cd gto-advisor

# Install dependencies
pip3 install -r requirements.txt

# Run the app
python3 app.py
```

Then open **http://127.0.0.1:5000** in your browser.

> **Tip:** Run it on a second monitor or half-screen window next to your tournament client.

### Mac Users

If you get `command not found: pip`, use `pip3` and `python3` instead. You may also need to install Xcode Command Line Tools first:

```bash
xcode-select --install
```

---

## How to Use

### Preflop Tab

1. Click a **rank** (A, K, Q, etc.) then click a **suit** (♠ ♥ ♦ ♣) to select each hole card
2. Set your **position** (UTG, MP, CO, BTN, SB, BB)
3. Set your **stack size** in big blinds
4. Choose the **action you're facing** (unopened, raised, 3-bet, all-in)
5. Click **GET GTO ADVICE** for the recommended play and bet sizing

### Postflop Tab

1. Select your **hole cards** (rank → suit)
2. Select the **community cards** (3–5 cards; street auto-detects)
3. Set the **pot size** in big blinds
4. Set what you're **facing** (checked to you, facing a bet, check-check)
5. Click **GET GTO ADVICE** for board texture analysis and optimal play

### Ranges Tab

Quick-reference chart showing which hands to open-raise from each position at various stack depths.

---

## What the Advice Includes

| Field | Description |
|-------|-------------|
| **Action** | Raise, call, fold, all-in, 3-bet, check, or bet |
| **Sizing** | Exact bet size in BB and as a percentage of pot |
| **Reasoning** | Why this is the GTO-recommended play |
| **Alternatives** | Mixed strategy options when applicable |
| **Confidence** | How clear-cut the decision is (HIGH / MEDIUM / LOW) |

---

## Stack Depth Categories

| Your Stack | Category | General Strategy |
|------------|----------|------------------|
| ≤ 10 BB | Push/Fold | All-in or fold only |
| 11–15 BB | Short | Open-shove with strong hands |
| 16–25 BB | Medium-Short | Standard opens, tighter 3-bet ranges |
| 26–40 BB | Medium | Full open ranges, standard tournament play |
| 41–60 BB | Medium-Deep | Wider ranges, more postflop play |
| 60+ BB | Deep | Full GTO ranges, complex postflop spots |

---

## Project Structure

```
gto_advisor/
├── app.py                 # Flask server + GTO poker engine
├── templates/
│   └── index.html         # Frontend UI (single-page app)
├── requirements.txt       # Python dependencies
├── .gitignore
└── README.md
```

---

## Tech Stack

- **Backend:** Python / Flask
- **Frontend:** Vanilla HTML/CSS/JS (no build step)
- **Logic:** Heuristic-based GTO approximations with Nash push/fold charts

---

## Deploy as a Website (GitHub Pages)

This app can run entirely in the browser with no server needed. To deploy:

1. Go to your repo on GitHub: **Settings → Pages**
2. Under "Source", select **Deploy from a branch**
3. Choose **main** branch and **/ (root)** folder
4. Click **Save**
5. Wait ~1 minute, then visit: `https://YOUR_USERNAME.github.io/GTO-Advisor/`

The `index.html` file contains all the poker logic in JavaScript — no Python or Flask needed for the web version.

---

## Disclaimer

This is a **GTO approximation** based on simplified preflop ranges and heuristic postflop analysis — not a full solver. It's designed for quick in-game reference during tournaments. For deep study, pair it with dedicated solvers like PioSolver or GTO+.

GTO is the baseline — exploitative adjustments based on opponent tendencies win more.

---

## License

MIT — free for personal and educational use.
