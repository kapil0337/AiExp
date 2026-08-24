"""The sassy money coach 💅

Calls an NVIDIA NIM model (OpenAI-compatible chat completions) to roast or
praise the current spending. If there is no API key, or the call fails/times
out, we fall back to canned one-liners so the UI never shows an error — the
bubble is decoration, not a critical path.
"""

from __future__ import annotations

import logging
import random

import httpx

from .config import get_settings
from .schemas import Summary, VibeCheck

log = logging.getLogger("bloom.ai")

SYSTEM_PROMPT = """You are "Bloomie", a bubbly, chaotic-good money bestie living \
inside a pink budgeting app. You give ONE short verdict on the user's spending.

Hard rules:
- 1 or 2 sentences. Under 240 characters. Never more.
- Playful, girly, gen-z, teasing but NEVER mean about the person's worth or body.
- Use 1-3 emojis, naturally placed.
- React to the actual numbers you are given (percent used, biggest category, \
who owes money, pace per day). Be specific, not generic.
- If they are overspending, be dramatic and funny about it, then give one tiny \
practical nudge.
- If they are doing well, hype them up.
- No markdown, no bullet points, no quotes around your answer. Just the line.
"""

# mood -> (canned lines, emoji)
FALLBACK: dict[str, tuple[list[str], str]] = {
    "comfy": (
        [
            "Budget looking THICK and healthy. Financial princess behaviour.",
            "You've barely touched the pot. Who is she? A saver?!",
            "Wallet's giving abundance. Keep this exact energy.",
        ],
        "🌸",
    ),
    "watchful": (
        [
            "We're cruising along nicely — just don't blink near a checkout page.",
            "Halfway-ish. Still cute, still in control. Proud of you.",
            "Solid pacing! The cart is watching you though.",
        ],
        "✨",
    ),
    "tight": (
        [
            "Okay bestie, the budget is getting a lil skinny. Maybe cook tonight?",
            "Danger zone approaching. Put the tote bag down. Slowly.",
            "We're in the last stretch of coins. Protect the remaining ones.",
        ],
        "😬",
    ),
    "overboard": (
        [
            "MA'AM. The budget has left the building. It is not coming back.",
            "You didn't overspend, you speedran it. Iconic but concerning.",
            "The money said goodbye and it meant it. Time for instant noodles era.",
        ],
        "🚨",
    ),
}

MOOD_EMOJI = {"comfy": "🌸", "watchful": "✨", "tight": "😬", "overboard": "🚨"}


def _offline(mood: str) -> VibeCheck:
    lines, emoji = FALLBACK.get(mood, FALLBACK["watchful"])
    return VibeCheck(
        message=random.choice(lines), mood=mood, emoji=emoji, source="offline"
    )


def _facts(s: Summary) -> str:
    cur = s.currency
    pace = (
        f"She's averaging {cur} {s.avg_per_day:,.0f} a day over {s.days_tracked} days."
        if s.days_tracked
        else "No spending logged yet."
    )
    owed = (
        f"{cur} {s.owed_to_her:,.0f} is still owed to her by other people."
        if s.owed_to_her > 0
        else "Nobody owes her anything right now."
    )
    return (
        f"Budget: {cur} {s.total_budget:,.0f}. "
        f"Spent: {cur} {s.total_spent:,.0f} ({s.percent_used:.0f}% of the budget). "
        f"Left: {cur} {s.remaining:,.0f}. "
        f"Paid by cash {cur} {s.by_method.cash:,.0f}, "
        f"GPay {cur} {s.by_method.gpay:,.0f}, "
        f"card {cur} {s.by_method.card:,.0f}. "
        f"Top category: {s.top_category or 'nothing yet'}. "
        f"Biggest single expense: {cur} {s.biggest_expense:,.0f}. "
        f"{pace} {owed} "
        f"Overall status: {s.status}."
    )


async def vibe_check(summary: Summary) -> VibeCheck:
    settings = get_settings()
    mood = summary.status

    if not settings.ai_enabled:
        return _offline(mood)

    payload = {
        "model": settings.nvidia_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
            return _offline(mood)
        return VibeCheck(
            message=text[:280], mood=mood, emoji=MOOD_EMOJI.get(mood, "✨"),
            source="nvidia",
        )
    except Exception as exc:  # network, auth, shape — all non-fatal
        log.warning("NVIDIA vibe check failed (%s); using offline line", exc)
        return _offline(mood)
