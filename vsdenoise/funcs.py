"""
This module contains general denoising functions built on top of base denoisers.
"""

from __future__ import annotations

from typing import Any

from vsscale import Waifu2x
from vsscale.scale import BaseWaifu2x
from vstools import CustomIndexError, vs

__all__ = [
    'mlm_degrain',

    'mc_degrain',

    'waifu2x_denoise'
]


def mlm_degrain(clip):
    pass


def mc_degrain(clip):
    pass


def waifu2x_denoise(
    clip: vs.VideoNode, noise: int = 1, model: type[BaseWaifu2x] = Waifu2x.Cunet, **kwargs: Any
) -> vs.VideoNode:
    if noise < 0 or noise > 3:
        raise CustomIndexError('"noise" must be in range 0-3 (inclusive).')

    if not isinstance(model, type):
        model = model.__class__  # type: ignore

    return model(**kwargs).scale(clip, clip.width, clip.height, _static_args=dict(scale=1, noise=noise, force=True))
