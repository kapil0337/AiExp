# 🌸 Bloom Budget

A very pink, very cute expense tracker built for one person. No budget cap — just
log what you spend (cash / GPay / card, or a mix of all three), keep a real account
balance you edit by hand, track cash-in-hand and your credit card billing cycle,
see who still owes you money, and get a sassy AI money coach's take on it all.

Responsive down to a phone and up to a desktop, with an iPad-friendly middle.

```
┌─ Home ──────────┐  ┌─ Stats ─────────┐  ┌─ Owes me ───────┐
│  ₹13,421 balance│  │ KPI row         │  │ owed to you     │
│  spent this mo. │  │ payment split   │  │ you owe         │
│  💅 Bloomie says│  │ daily/monthly   │  │ the ledger      │
│  quick add form │  │ by category     │  │ settle / undo   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## What it does

| Feature | Notes |
|---|---|
| **Account balance** | One number that's actually yours — never resets monthly, edit it any time (rent in, rent out, whatever), six currencies |
| **Expenses** | Name, emoji, category, note, date — spend tracking resets to the current calendar month, with a monthly-history chart for the trend |
| **Three payment modes** | Tick cash / GPay / card. Tick more than one and you get a per-method amount box — one purchase can be split across all three |
| **Credit card cycle** | Card spend is tracked on its own 8th-to-8th cycle (not calendar month) and auto-deducted from your balance on the 26th — or settle a finished cycle early by hand |
| **Cash in hand** | Track physical INR notes by denomination — informational, kept separate from the account balance |
| **Dashboard** | Spent per method (share-of-total bar), daily spend columns, monthly history, category ranking, KPI row |
| **Splits / IOUs** | "They owe me" and "I owe them", standalone or attached to an expense |
| **Bloomie 💅** | An NVIDIA NIM model reads your numbers and delivers one funny, neutral-toned line — no verdict, just vibes. Falls back to canned lines with no API key |
| **Extras** | Light/dark/auto theme, motion toggle, table view under every chart, PWA manifest, keyboard-accessible charts |

---

## Quick start (venv)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
cp .env.example .env
```

Fill in `GOOGLE_CLIENT_ID`, `ALLOWED_EMAILS`, and `SESSION_SECRET` in `.env` —
see [Setting up Google Sign-In](#setting-up-google-sign-in) below. The app
still boots without them, but you won't be able to sign in.

```bash
uvicorn backend.main:app --reload --port 8000
```

Open <http://localhost:8000>. That's it — it creates `data/bloom.db` (SQLite) on
first run and serves the frontend from `/public` at the same origin.

Run the tests:

```bash
pytest -q          # 38 tests
ruff check .
```

---

## Docker

```bash
docker compose up --build
```

Brings up Postgres 16 + the app on <http://localhost:8000>, with the database on a
named volume so your data survives restarts. To pass the AI key through:

```bash
NVIDIA_API_KEY=nvapi-xxxx docker compose up --build
```

Image only, no Postgres (uses SQLite inside the container):

```bash
docker build -t bloom-budget .
docker run -p 8000:8000 bloom-budget
```

---

## Deploying to Vercel

Vercel serves `public/` from its CDN and runs `api/index.py` as a Python
serverless function; `vercel.json` rewrites `/api/*` onto it.

1. **You need a hosted Postgres** — serverless filesystems are ephemeral, so SQLite
   will silently lose data between invocations. Free options: [Neon](https://neon.tech),
   [Supabase](https://supabase.com), or Vercel Postgres.
2. Push the repo to GitHub and import it at [vercel.com/new](https://vercel.com/new).
   Framework preset: **Other**. No build command, no output directory.
3. Add environment variables in *Project → Settings → Environment Variables*:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | `postgresql://user:pass@host/db?sslmode=require` |
   | `GOOGLE_CLIENT_ID` | from Google Cloud Console — see [Setting up Google Sign-In](#setting-up-google-sign-in) |
   | `ALLOWED_EMAILS` | comma-separated Google account emails allowed to sign in |
   | `SESSION_SECRET` | random string — `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
   | `NVIDIA_API_KEY` | your key from [build.nvidia.com](https://build.nvidia.com) (optional) |
   | `NVIDIA_MODEL` | `meta/llama-3.3-70b-instruct` (optional) |
   | `APP_NAME` | whatever you want the header to say |
   | `DEFAULT_CURRENCY` | `INR` |

4. Deploy. Tables are created automatically on the first request.

> `postgres://` and `postgresql://` URLs are rewritten to `postgresql+psycopg://`
> automatically, so paste whatever your provider gives you.

### ⚠️ Changing a model after the database exists

There are **no migrations**. `create_all()` creates missing *tables*, but it never
adds *columns* to a table that already exists. So if you add a field to a model and
redeploy against a database created before that field, every request touching that
table fails with `UndefinedColumn`.

Startup now catches this and refuses to run with a message naming the missing
columns, instead of serving a wall of 500s. When you see it:

```bash
docker compose down -v && docker compose up --build   # local: recreate the volume
rm data/bloom.db                                      # local SQLite
```

On a deployed Postgres you cannot just wipe it once there's real data — add the
column by hand (`ALTER TABLE budgets ADD COLUMN user_id INTEGER ...`) or bring in
Alembic before the data matters. This is worth doing *before* she starts using it
for real.

---

## Setting up Google Sign-In

One-time setup at [console.cloud.google.com](https://console.cloud.google.com):

1. Create or select a project.
2. **APIs & Services → OAuth consent screen** — choose **External** (a personal
   Gmail account can't use Internal). While the app is in "Testing" publishing
   status, Google *also* restricts sign-in to test users you list there — a
   second allowlist independent of this app's own `ALLOWED_EMAILS`. Either add
   the same emails as test users, or move the consent screen to "In production"
   (no verification needed for an app that only requests basic profile/email).
3. **Credentials → Create Credentials → OAuth client ID** → Application type
   **Web application**.
4. Add an **Authorized JavaScript origin** for every origin you'll use it from —
   e.g. `http://localhost:8000` and your real deployed domain (e.g.
   `https://your-app.vercel.app`). Leave **Authorized redirect URIs** empty —
   the "Sign In With Google" button flow used here isn't the redirect-based
   OAuth code flow, so it doesn't need one.
5. Copy the generated Client ID into `GOOGLE_CLIENT_ID`.
6. Set `ALLOWED_EMAILS` to the comma-separated list of Google account emails
   allowed to sign in — anyone else's Google sign-in is rejected even though
   Google itself verified their identity fine.
7. Generate a random `SESSION_SECRET` (command above) — this signs the login
   session cookie.

Each Google account that signs in gets its own private budget, expenses, and
splits.

---

## The AI bit (NVIDIA NIM)

`backend/ai.py` posts to NVIDIA's OpenAI-compatible endpoint
(`https://integrate.api.nvidia.com/v1/chat/completions`) with the current
numbers — account balance, spend this month, top category, pace per day, card
cycle, who owes what — and asks for one short, funny, neutral-toned line.

It is **fail-open by design**: no key, a timeout, a bad response, or a 500 all fall
back to a canned line. The bubble never shows an error, because a joke generator
should never break an expense tracker.

Swap the model with `NVIDIA_MODEL`. Measured on this account (2026-08-24):

| Model | Result |
|---|---|
| `meta/llama-3.1-8b-instruct` | ✅ ~1s, funny — **the default** |
| `meta/llama-3.1-70b-instruct` | ⚠️ works but ~13s — too slow for the bubble |
| `meta/llama-3.3-70b-instruct` | ❌ connects, then never responds (hangs past 90s) |
| `mistralai/mistral-large-2-instruct` | ❌ 404, not on this tier |

If you swap models, time it first — the client gives up after 20s and falls back to
a canned line, so a slow model looks identical to no key at all. `<think>` blocks
from reasoning models are stripped before display, and models that return their
answer in `reasoning_content` instead of `content` (some Nemotron builds) fall back.

---

## Project layout

```
backend/
  config.py     settings from env (+ .env locally)
  database.py   engine, sessions, SQLite↔Postgres switching
  models.py     User, Budget, Expense, Split, CashHolding, CardCycleSettlement — money is Numeric(12,2), never float
  schemas.py    pydantic request/response shapes
  auth.py       Google token verification + signed session cookie
  ai.py         Bloomie, the NVIDIA-powered sass generator
  cycles.py     8th-to-8th credit card cycle math + lazy settlement
  main.py       all /api routes + summary maths
api/index.py    Vercel entrypoint (imports the same app)
public/         index.html, styles.css, app.js — no build step, no dependencies
tests/          38 end-to-end API tests + cycle unit tests
```

### How the money maths works

There's no budget cap — `account_balance` is a number you set by hand (rent in,
rent out, whatever), and it only otherwise moves when a credit card cycle
auto-settles. Everything else in the summary (spend, by-method breakdown,
biggest expense, top category) is scoped to the **current calendar month**;
multi-month trend lives in the dashboard's monthly-history chart instead.

```
remaining_if_everyone_pays = account_balance + open "they owe me" − open "I owe them"
recovered = settled "they owe me" − settled "I owe them"   (bookkeeping only — doesn't touch the balance)
```

An expense you split with a friend is still fully your spend for the month —
their share coming back is tracked via `recovered`, but (unlike the old
budget-pot model) it no longer feeds back into any total automatically, since
there's no pot for it to return to. Edit `account_balance` by hand once they
actually pay you.

### Credit card cycle

Runs the 8th of one month to the 8th of the next (not a calendar month). The
prior cycle's card spend auto-deducts from `account_balance` once its settle
date (the 26th of the month the cycle ended in) has passed. There's no
scheduler in this app, so settlement is lazy: it runs at the top of every
summary read (`backend/cycles.py::run_auto_settlements`) and catches up on
anything overdue, however late you next open the app. A "Settle now" button in
Settings lets you close out an already-finished cycle early, without waiting
for the 26th.

---

## API

`health`, `meta`, and `auth/*` are public; every other route requires a valid
session and only ever sees the signed-in user's own budget.

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/health` | liveness + whether the AI key is set |
| `GET` | `/api/meta` | app name, categories, AI status, Google client ID |
| `POST` | `/api/auth/google` | sign in with a Google ID token, sets the session cookie |
| `POST` | `/api/auth/logout` | clear the session cookie |
| `GET` | `/api/auth/me` | who's logged in, if anyone (never 401s) |
| `GET` `PUT` | `/api/budget` | read / set the name + currency |
| `PUT` | `/api/account-balance` | set the account balance |
| `POST` | `/api/budget/reset` | wipe expenses + IOUs (balance, cash counts, card-cycle history stay) |
| `GET` `PUT` | `/api/cash-holdings` | read / set cash-in-hand note counts |
| `POST` | `/api/card-cycle/settle-now` | manually settle an already-finished credit card cycle early |
| `GET` | `/api/card-cycle/history` | past settlements |
| `GET` `POST` | `/api/expenses` | list (filters: `q`, `method`, `category`, `month`) / create |
| `PATCH` `DELETE` | `/api/expenses/{id}` | edit / delete |
| `GET` `POST` | `/api/splits` | list (filters: `settled`, `direction`) / create |
| `PATCH` `DELETE` | `/api/splits/{id}` | settle, edit, delete |
| `GET` | `/api/splits/people` | per-person rollup |
| `GET` | `/api/summary` | just the numbers (month-scoped) |
| `GET` | `/api/dashboard?days=14` | summary + daily series + monthly history + categories + recent |
| `POST` | `/api/vibe-check` | ask Bloomie |

Interactive docs at `/docs` when running locally.

---

## Chart colours

The three payment methods are a categorical palette, so they were validated rather
than eyeballed — light and dark are separately chosen steps, not an automatic flip:

| Method | Light | Dark |
|---|---|---|
| Cash | `#E8579A` | `#E05494` |
| GPay | `#7C5CE0` | `#8A6BE8` |
| Card | `#17A398` | `#16A99A` |

Both sets pass the lightness band, chroma floor, adjacent-pair separation under
protanopia/deuteranopia/tritanopia (worst pair ΔE 12.3), and 3:1 contrast against
their surface. Identity is never carried by colour alone — every chart has a legend,
direct labels, keyboard-focusable marks with tooltips, and a table view.

---

## Notes

- Sign-in is Google-only and allowlisted — only the emails listed in
  `ALLOWED_EMAILS` can create an account, and each account's budget, expenses,
  and splits are private to that account. There's no way to add a collaborator
  to a single budget today; each Google account is its own separate space.
- `prefers-reduced-motion` is respected, and there's a manual "sparkles & wiggles"
  switch in Settings for when the floating hearts are too much.
