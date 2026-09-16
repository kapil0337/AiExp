"""The sassy money coach 💅

Calls an NVIDIA NIM model (OpenAI-compatible chat completions) for a playful,
neutral-toned take on the current spending — no budget-cap verdict, just a
reaction to the numbers. If there is no API key, or the call fails/times out,
we fall back to canned one-liners so the UI never shows an error — the bubble
is decoration, not a critical path.
"""

from __future__ import annotations

import logging
import random

import httpx

from .config import get_settings
from .schemas import Summary, VibeCheck

log = logging.getLogger("bloom.ai")

SYSTEM_PROMPT = """You are "Bloomie", a bubbly, chaotic-good money bestie living \
inside a pink expense tracker. You give ONE short, neutral-toned observation on \
the user's spending — not a verdict, just a specific, funny remark.

Hard rules:
- 1 or 2 sentences. Under 240 characters. Never more.
- Playful, girly, gen-z, teasing but NEVER mean about the person's worth or body.
- Use 1-3 emojis, naturally placed.
- React to the actual numbers you are given (spend this month, biggest category, \
who owes money, pace per day, card cycle). Be specific, not generic.
- Don't moralize or judge whether the spending is "good" or "bad" — there's no \
budget cap here, just react to what's actually happening.
- No markdown, no bullet points, no quotes around your answer. Just the line.
"""


def _system_prompt(nickname: str | None) -> str:
    if not nickname:
        return SYSTEM_PROMPT
    return (
        f'{SYSTEM_PROMPT}\n- The user goes by "{nickname}". Address them by that '
        "nickname sometimes for a personal touch — not in every single line, just "
        "naturally, like a real bestie would."
    )

# Neutral-toned canned lines — no mood/verdict framing, just reused when the
# NVIDIA call is disabled/failed so the bubble never shows an error.
FALLBACK: list[str] = [
    "Your money, your rules. Just here vibing with the numbers 🌸",
    "Tracking it all so you don't have to remember it all. Teamwork ✨",
    "No judgment here, just receipts. Literally 🧾",
    "The spreadsheet-in-a-dress era continues. Carry on 💅",
]

EMOJIS = ["🌸", "✨", "💅", "🌷"]


def _offline() -> VibeCheck:
    return VibeCheck(
        message=random.choice(FALLBACK), emoji=random.choice(EMOJIS), source="offline"
    )


def _facts(s: Summary) -> str:
    cur = s.currency
    pace = (
        f"She's averaging {cur} {s.avg_per_day:,.0f} a day this month."
        if s.spent_this_month
        else "No spending logged yet this month."
    )
    owed = (
        f"{cur} {s.owed_to_her:,.0f} is still owed to her by other people."
        if s.owed_to_her > 0
        else "Nobody owes her anything right now."
    )
    return (
        f"Account balance: {cur} {s.account_balance:,.0f}. "
        f"Spent this month ({s.month_label}): {cur} {s.spent_this_month:,.0f}. "
        f"Paid by cash {cur} {s.by_method.cash:,.0f}, "
        f"GPay {cur} {s.by_method.gpay:,.0f}, "
        f"card {cur} {s.by_method.card:,.0f}. "
        f"Top category: {s.top_category or 'nothing yet'}. "
        f"Biggest single expense: {cur} {s.biggest_expense:,.0f}. "
        f"{pace} {owed} "
        f"Current credit card cycle ({s.card_cycle.cycle_start} to "
        f"{s.card_cycle.cycle_end}) so far: {cur} {s.card_cycle.card_spent_so_far:,.0f}, "
        f"settles on {s.card_cycle.settle_date}."
    )


async def vibe_check(summary: Summary, nickname: str | None = None) -> VibeCheck:
    settings = get_settings()

    if not settings.ai_enabled:
        return _offline()

    payload = {
        "model": settings.nvidia_model,
        "messages": [
            {"role": "system", "content": _system_prompt(nickname)},
            {"role": "user", "content": _facts(summary)},
        ],
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": 120,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            resp = await client.post(
                f"{settings.nvidia_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.nvidia_api_key}",
                    "Accept": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        text = (data["choices"][0]["message"]["content"] or "").strip()
        # Some reasoning models prefix a <think> block — keep only the payload.
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        text = text.strip().strip('"').strip()
        if not text:
            return _offline()
        return VibeCheck(message=text[:280], emoji=random.choice(EMOJIS), source="nvidia")
    except Exception as exc:  # network, auth, shape — all non-fatal
        log.warning("NVIDIA vibe check failed (%s); using offline line", exc)
        return _offline()
