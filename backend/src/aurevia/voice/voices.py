"""Approved agent voices (Cartesia voice ids), chosen by listening on 2026-10-10.

Both are from Cartesia's Indian catalogue and handle Indian English, Hindi and Hinglish
(samples: ``python -m aurevia_voice.voice_samples``). Meera is the default for new agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Voice:
    key: str
    id: str
    name: str
    gender: Literal["female", "male"]


MEERA = Voice(key="meera", id="a81fccdc-5595-4dfc-ae76-4de6a515b8a2", name="Meera", gender="female")
DEV = Voice(key="dev", id="910fb75e-1d20-4840-ac63-ac6b26a71bdc", name="Dev", gender="male")

APPROVED_VOICES: tuple[Voice, ...] = (MEERA, DEV)
DEFAULT_VOICE = MEERA
