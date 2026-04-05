"""
Lightweight in-process timer registry.

Two timer types:
  • Refresh timer  — short countdown (≤60 s) on the "Update" button.
                     Ticks every 2 s to stay well within Telegram's edit rate limit.
  • Cooldown timer — long countdown (minutes) shown in a message after activation.
                     Ticks every 30 s; no need for second-level accuracy here.
"""

import asyncio
from collections.abc import Awaitable, Callable

_refresh_tasks:  dict[int, asyncio.Task] = {}
_cooldown_tasks: dict[int, asyncio.Task] = {}


# ── Refresh timer ─────────────────────────────────────────────────────────────

def is_refresh_locked(user_id: int) -> bool:
    task = _refresh_tasks.get(user_id)
    return task is not None and not task.done()


def start_refresh_timer(
    user_id: int,
    seconds: int,
    on_tick: Callable[[int], Awaitable[None]],
    on_done: Callable[[], Awaitable[None]],
) -> None:
    _cancel(_refresh_tasks, user_id)

    async def _run() -> None:
        loop = asyncio.get_event_loop()
        end  = loop.time() + seconds
        try:
            while True:
                remaining = int(end - loop.time())
                if remaining <= 0:
                    break
                await on_tick(remaining)
                await asyncio.sleep(min(2, remaining))
            await on_done()
        except asyncio.CancelledError:
            pass
        finally:
            _refresh_tasks.pop(user_id, None)

    _refresh_tasks[user_id] = asyncio.create_task(_run())


def cancel_refresh(user_id: int) -> None:
    _cancel(_refresh_tasks, user_id)


# ── Cooldown display timer ────────────────────────────────────────────────────

def start_cooldown_display(
    user_id: int,
    total_seconds: int,
    on_tick: Callable[[int], Awaitable[None]],
    on_done: Callable[[], Awaitable[None]],
) -> None:
    _cancel(_cooldown_tasks, user_id)

    async def _run() -> None:
        loop = asyncio.get_event_loop()
        end  = loop.time() + total_seconds
        try:
            while True:
                remaining = int(end - loop.time())
                if remaining <= 0:
                    break
                await on_tick(remaining)
                await asyncio.sleep(min(30, remaining))
            await on_done()
        except asyncio.CancelledError:
            pass
        finally:
            _cooldown_tasks.pop(user_id, None)

    _cooldown_tasks[user_id] = asyncio.create_task(_run())


def cancel_cooldown_display(user_id: int) -> None:
    _cancel(_cooldown_tasks, user_id)


# ── Internal ──────────────────────────────────────────────────────────────────

def _cancel(store: dict[int, asyncio.Task], user_id: int) -> None:
    task = store.pop(user_id, None)
    if task and not task.done():
        task.cancel()
