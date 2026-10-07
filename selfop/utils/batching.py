from __future__ import annotations

import math
import random


def make_batches(ids: list[str], batch_size: int, epoch: int) -> list[list[str]]:
    """Deterministically shuffled batches for one epoch."""
    ids = list(ids)
    random.Random(epoch).shuffle(ids)
    return [ids[i : i + batch_size] for i in range(0, len(ids), batch_size)]


def make_steps(ids: list[str], batch_size: int, epochs: int) -> list[list[str]]:
    """Generate a flat list of steps across multiple epochs.

    Each epoch shuffles `ids` with a different seed, splits into batches,
    and all batches are concatenated into a single ordered list of steps.
    Total steps = epochs * ceil(len(ids) / batch_size).
    """
    steps: list[list[str]] = []
    for epoch in range(1, epochs + 1):
        steps.extend(make_batches(ids, batch_size, epoch=epoch))
    return steps
