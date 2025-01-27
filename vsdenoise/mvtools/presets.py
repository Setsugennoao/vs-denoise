
from dataclasses import dataclass
from typing import Any, Iterator, MutableMapping, NoReturn, TypedDict

from vstools import KwargsT, PlanesT, VSFunction, classproperty, vs

from .enums import FlowMode, MaskMode, MotionMode, PenaltyMode, RFilterMode, SADMode, SearchMode, SharpMode


__all__ = [
    "SuperArgs",
    "AnalyzeArgs",
    "RecalculateArgs",
    "CompensateArgs",
    "FlowArgs",
    "DegrainArgs",
    "FlowInterpolateArgs",
    "FlowFpsArgs",
    "BlockFpsArgs",
    "FlowBlurArgs",
    "MaskArgs",
    "ScDetectionArgs",
    "MVToolsPreset",
    "MVToolsPresets"
]


class SuperArgs(TypedDict, total=False):
    pad: int | tuple[int | None, int | None] | None
    levels: int | None
    sharp: SharpMode | None
    rfilter: RFilterMode | None
    pelclip: vs.VideoNode | VSFunction | None


class AnalyzeArgs(TypedDict, total=False):
    blksize: int | None
    blksizev: int | None
    levels: int | None
    search: SearchMode | None
    searchparam: int | None
    pelsearch: int | None
    lambda_: int | None
    truemotion: MotionMode | None
    lsad: int | None
    plevel: PenaltyMode | None
    global_: bool | None
    pnew: int | None
    pzero: int | None
    pglobal: int | None
    overlap: int | None
    overlapv: int | None
    divide: bool | None
    badsad: int | None
    badrange: int | None
    meander: bool | None
    trymany: bool | None
    dct: SADMode | None


class RecalculateArgs(TypedDict, total=False):
    blksize: int | None
    blksizev: int | None
    search: SearchMode | None
    searchparam: int | None
    lambda_: int | None
    truemotion: MotionMode | None
    pnew: int | None
    overlap: int | None
    overlapv: int | None
    divide: bool | None
    meander: bool | None
    dct: SADMode | None


class CompensateArgs(TypedDict, total=False):
    scbehavior: bool | None
    thsad: int | None
    time: float | None
    thscd1: int | None
    thscd2: int | None


class FlowArgs(TypedDict, total=False):
    time: float | None
    mode: FlowMode | None
    thscd1: int | None
    thscd2: int | None


class DegrainArgs(TypedDict, total=False):
    thsad: int | None
    thsadc: int | None
    limit: int | None
    limitc: int | None
    thscd1: int | None
    thscd2: int | None


class FlowInterpolateArgs(TypedDict, total=False):
    time: float | None
    ml: float | None
    blend: bool | None
    thscd1: int | None
    thscd2: int | None


class FlowFpsArgs(TypedDict, total=False):
    mask: int | None
    ml: float | None
    blend: bool | None
    thscd1: int | None
    thscd2: int | None
    num: int
    den: int


class BlockFpsArgs(TypedDict, total=False):
    mode: int | None
    ml: float | None
    blend: bool | None
    thscd1: int | None
    thscd2: int | None
    num: int
    den: int


class FlowBlurArgs(TypedDict, total=False):
    blur: float | None
    prec: int | None
    thscd1: int | None
    thscd2: int | None


class MaskArgs(TypedDict, total=False):
    ml: float | None
    gamma: float | None
    kind: MaskMode | None
    time: float | None
    ysc: int | None
    thscd1: int | None
    thscd2: int | None


class ScDetectionArgs(TypedDict, total=False):
    thscd1: int | None
    thscd2: int | None


@dataclass(kw_only=True)
class MVToolsPreset(MutableMapping[str, Any]):
    tr: int = 1
    pel: int | None
    planes: PlanesT | None = None
    super_args: SuperArgs | KwargsT | None = None
    analyze_args: AnalyzeArgs | KwargsT | None = None
    recalculate_args: RecalculateArgs | KwargsT | None = None
    compensate_args: CompensateArgs | KwargsT | None = None
    flow_args: FlowArgs | KwargsT | None = None
    degrain_args: DegrainArgs | KwargsT | None = None
    flow_interpolate_args: FlowInterpolateArgs | KwargsT | None = None
    flow_fps_args: FlowFpsArgs | KwargsT | None = None
    block_fps_args: BlockFpsArgs | KwargsT | None = None
    flow_blur_args: FlowBlurArgs | KwargsT | None = None
    mask_args: MaskArgs | KwargsT | None = None
    sc_detection_args: ScDetectionArgs | KwargsT | None = None

    def __getitem__(self, key: str) -> Any:
        return self.__dict__.__getitem__(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.__dict__.__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self.__dict__.__delitem__(key)

    def __iter__(self) -> Iterator[str]:
        return self.__dict__.__iter__()

    def __len__(self) -> int:
        return self.__dict__.__len__()


class MVToolsPresets:
    """Presets for MVTools analyzing/refining."""

    def __init__(self) -> NoReturn:
        raise NotImplementedError

    @classproperty
    def SMDE(self) -> MVToolsPreset:
        return MVToolsPreset(
            pel=2,
            super_args=SuperArgs(
                sharp=SharpMode.WIENER,
                rfilter=RFilterMode.CUBIC,
                # prefilter=Prefilter.NONE,
                pad=8
            ),
            analyze_args=AnalyzeArgs(
                blksize=8,
                overlap=2,
                dct=SADMode.SPATIAL,
                search=SearchMode.HEXAGON,
                truemotion=MotionMode.COHERENCE,
            ),
            recalculate_args=RecalculateArgs(
                blksize=8,
                overlap=2,
                dct=SADMode.SPATIAL,
                search=SearchMode.HEXAGON,
                truemotion=MotionMode.COHERENCE,
            ),
            degrain_args=DegrainArgs(thsad=300)
        )

    @classproperty
    def CMDE(self) -> MVToolsPreset:
        return MVToolsPreset(
            pel=1,
            super_args=SuperArgs(
                sharp=SharpMode.WIENER,
                rfilter=RFilterMode.CUBIC,
                # prefilter=Prefilter.NONE,
                pad=32
            ),
            analyze_args=AnalyzeArgs(
                blksize=32,
                overlap=16,
                dct=SADMode.SPATIAL,
                search=SearchMode.HEXAGON,
                truemotion=MotionMode.SAD,
            ),
            recalculate_args=RecalculateArgs(
                blksize=32,
                overlap=16,
                dct=SADMode.SPATIAL,
                search=SearchMode.HEXAGON,
                truemotion=MotionMode.SAD,
            ),
            degrain_args=DegrainArgs(thsad=300)
        )

    @classproperty
    def FAST(self) -> MVToolsPreset:
        return MVToolsPreset(
            pel=1,
            super_args=SuperArgs(
                sharp=SharpMode.WIENER,
                rfilter=RFilterMode.TRIANGLE,
                # prefilter=Prefilter.MINBLUR3,
                pad=32
            ),
            analyze_args=AnalyzeArgs(
                blksize=32,
                overlap=16,
                dct=SADMode.SPATIAL,
                search=SearchMode.DIAMOND,
                truemotion=MotionMode.SAD,
            ),
            recalculate_args=RecalculateArgs(
                blksize=32,
                overlap=16,
                dct=SADMode.SPATIAL,
                search=SearchMode.DIAMOND,
                truemotion=MotionMode.SAD,
            ),
            degrain_args=DegrainArgs(thsad=60)
        )

    @classproperty
    def NOISY(self) -> MVToolsPreset:
        # prefilter=Prefilter.DFTTEST,
        return MVToolsPreset(
            pel=2,
            analyze_args=AnalyzeArgs(
                blksize=16,
                overlap=8,
                dct=SADMode.ADAPTIVE_SPATIAL_MIXED,
                truemotion=MotionMode.SAD,
            ),
            recalculate_args=RecalculateArgs(
                blksize=16,
                overlap=8,
                dct=SADMode.ADAPTIVE_SATD_MIXED,
                truemotion=MotionMode.SAD,
            ),
            degrain_args=DegrainArgs(thsad=100)
        )
