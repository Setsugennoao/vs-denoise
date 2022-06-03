"""
This module implements wrappers for mvtool
"""

from __future__ import annotations

from enum import Enum, IntEnum, auto
from math import ceil, e, exp, log, pi, sin, sqrt
from typing import Any, Callable, Dict, List, NamedTuple, Sequence, Tuple, Type, cast

import vapoursynth as vs
from havsfunc import DitherLumaRebuild, MinBlur
from vsutil import (
    Dither, depth, disallow_variable_format, disallow_variable_resolution,
    fallback, get_depth, get_y, scale_value, Range as CRange  # get_peak_value,
)

from .bm3d import BM3D, AbstractBM3D, Profile, _AbstractBM3DCuda
from .knlm import ChannelMode, knl_means_cl
from .types import KwArgsT, LambdaVSFunction

core = vs.core
blackman_args: Dict[str, Any] = dict(filter_param_a=-0.6, filter_param_b=0.4)


# here until vsutil gets a new release
def get_peak_value(clip: vs.VideoNode, chroma: bool = False) -> float:
    assert clip.format
    return (0.5 if chroma else 1.) if clip.format.sample_type == vs.FLOAT else (1 << get_depth(clip)) - 1.


class SourceType(IntEnum):
    BFF = 0
    TFF = 1
    PROGRESSIVE = 2

    @property
    def is_inter(self) -> bool:
        return self != SourceType.PROGRESSIVE


class PelType(IntEnum):
    AUTO = auto()
    NONE = auto()
    BICUBIC = auto()
    WIENER = auto()
    NNEDI3 = auto()


class Prefilter(IntEnum):
    MINBLUR1 = 0
    MINBLUR2 = 1
    MINBLUR3 = 2
    MINBLURFLUX = 3
    DFTTEST = 4
    KNLMEANSCL = 5
    BM3D = 6
    DGDENOISE = 7
    AUTO = 8
    NONE = 9


class MVTools:
    """MVTools wrapper for motion analysis / degrain / compensation"""
    analyze_args: Dict[str, Any]
    recalculate_args: Dict[str, Any]
    degrain_args: Dict[str, Any]

    bm3d_arch: Type[AbstractBM3D] = BM3D
    device_id: int = 0

    vectors: Dict[str, Any]

    clip: vs.VideoNode

    isHD: bool
    isUHD: bool
    tr: int
    refine: int
    source_type: SourceType
    prefilter: Prefilter | vs.VideoNode
    pel_type: Tuple[PelType, PelType]
    range_in: CRange
    pel: int
    subpixel: int
    chroma: bool
    is_gray: bool
    planes: List[int]
    mvplane: int
    rangeConversion: float
    hpad: int
    hpadU: int
    vpad: int
    vpadU: int
    rfilter: int
    mvtools: _MVTools

    class _SceneAnalyzeThreshold(NamedTuple):
        luma: float
        chroma: float

    class _SceneChangeThreshold(NamedTuple):
        first: int
        second: int

    class _MVTools(Enum):
        INTEGER = 0
        FLOAT_OLD = 1
        FLOAT_NEW = 2

        @property
        def namespace(self) -> Any:
            if self == MVTools._MVTools.INTEGER:
                return core.mv
            else:
                return core.mvsf

        @property
        def Super(self) -> Callable[..., vs.VideoNode]:
            return cast(Callable[..., vs.VideoNode], self.namespace.Super)

        @property
        def Analyse(self) -> Callable[..., vs.VideoNode]:
            if self == MVTools._MVTools.FLOAT_NEW:
                return cast(Callable[..., vs.VideoNode], self.namespace.Analyze)
            else:
                return cast(Callable[..., vs.VideoNode], self.namespace.Analyse)

        @property
        def Recalculate(self) -> Callable[..., vs.VideoNode]:
            return cast(Callable[..., vs.VideoNode], self.namespace.Recalculate)

        @property
        def Compensate(self) -> Callable[..., vs.VideoNode]:
            return cast(Callable[..., vs.VideoNode], self.namespace.Compensate)

        @property
        def Mask(self) -> Callable[..., vs.VideoNode]:
            return cast(Callable[..., vs.VideoNode], self.namespace.Mask)

        def Degrain(self, radius: int | None = None) -> Callable[..., vs.VideoNode]:
            if radius is None and self != MVTools._MVTools.FLOAT_NEW:
                raise ValueError(f"{self.name}.Degrain needs radius")

            try:
                return cast(Callable[..., vs.VideoNode], getattr(
                    self.namespace, f"Degrain{fallback(radius, '')}"
                ))
            except BaseException:
                raise ValueError(f"{self.name}.Degrain doesn't support a radius of {radius}")

    @disallow_variable_format
    @disallow_variable_resolution
    def __init__(
        self, clip: vs.VideoNode,
        tr: int = 2, refine: int = 3,
        source_type: SourceType = SourceType.PROGRESSIVE,
        prefilter: Prefilter | vs.VideoNode = Prefilter.AUTO,
        pel_type: Tuple[PelType, PelType] = (PelType.AUTO, PelType.AUTO),
        range_in: CRange = CRange.LIMITED,
        pel: int | None = None, subpixel: int = 3,
        planes: int | Sequence[int] | None = None,
        highprecision: bool = False,
        fixFades: bool = False, rangeConversion: float = 5.0,
        hpad: int | None = None, vpad: int | None = None,
        rfilter: int = 3, vectors: Dict[str, Any] = {}
    ) -> None:
        assert clip.format

        if clip.format.color_family not in {vs.GRAY, vs.YUV}:
            raise ValueError("MVTools: Only GRAY or YUV format clips supported")
        self.clip = clip

        self.isHD = clip.width >= 1100 or clip.height >= 600
        self.isUHD = self.clip.width >= 2600 or self.clip.height >= 1500

        if not isinstance(tr, int):
            raise ValueError("MVTools: 'tr' has to be an int!")
        self.tr = tr

        if not isinstance(refine, int):
            raise ValueError("MVTools: 'refine' has to be an int!")
        if refine > 6:
            raise ValueError("refine > 6 is not supported")
        self.refine = refine

        if source_type is None or source_type not in SourceType:
            raise ValueError("MVTools: 'source_type' has to be from SourceType (enum)!")
        self.source_type = source_type

        prefvn = isinstance(prefilter, vs.VideoNode)
        if prefilter is None or (not prefvn and prefilter not in Prefilter) and not prefvn:
            raise ValueError("MVTools: 'prefilter' has to be from Prefilter (enum) or a VideoNode!")
        self.prefilter = prefilter

        if pel_type is None or not isinstance(pel_type, tuple) or any(p is None or p not in PelType for p in pel_type):
            raise ValueError("MVTools: 'source_type' has to be a tuple of PelType (enum)!")
        self.pel_type = pel_type

        if range_in is None or range_in not in CRange:
            raise ValueError("MVTools: 'range_in' has to be 0 (limited) or 1 (full)!")
        self.range_in = range_in

        if not isinstance(pel, int) and pel is not None:
            raise ValueError("MVTools: 'pel' has to be an int or None!")
        self.pel = fallback(pel, 1 + int(not self.isHD))

        if not isinstance(subpixel, int):
            raise ValueError("MVTools: 'subpixel' has to be an int!")
        self.subpixel = subpixel

        if planes is not None and isinstance(planes, int):
            planes = [planes]

        if clip.format.color_family == vs.GRAY:
            planes = [0]
            self.chroma = False
        elif planes is None:
            planes = [0, 1, 2]
            self.chroma = True

        self.is_gray = planes == [0]

        self.planes, self.mvplane = self._get_planes(planes)

        if not hasattr(self, 'chroma'):
            self.chroma = 1 in self.planes or 2 in self.planes

        if not isinstance(fixFades, bool):
            raise ValueError("MVTools: 'fixFades' has to be a boolean!")

        if not isinstance(rangeConversion, float):
            raise ValueError("MVTools: 'rangeConversion' has to be a float!")
        self.rangeConversion = rangeConversion

        self.vectors = vectors

        if not isinstance(hpad, int) and hpad is not None:
            raise ValueError("MVTools: 'hpad' has to be an int or None!")
        self.hpad = fallback(hpad, 8 if self.isHD else 16)
        self.hpadU = self.hpad // 2 if self.isUHD else self.hpad

        if not isinstance(vpad, int) and hpad is not None:
            raise ValueError("MVTools: 'vpad' has to be an int or None!")
        self.vpad = fallback(vpad, 8 if self.isHD else 16)
        self.vpadU = self.vpad // 2 if self.isUHD else self.vpad

        if not isinstance(rfilter, int):
            raise ValueError("MVTools: 'rfilter' has to be an int!")
        self.rfilter = rfilter

        self.DCT = 5 if fixFades else 0

        if self.source_type == SourceType.PROGRESSIVE:
            self.workclip = self.clip
        else:
            self.workclip = self.clip.std.SeparateFields(int(self.source_type))

        fmt = self.workclip.format
        assert fmt

        if highprecision or fmt.bits_per_sample == 32 or fmt.sample_type == vs.FLOAT or refine == 6 or tr > 3:
            self.workclip = depth(self.workclip, 32)
            self.mvtools = self._MVTools.FLOAT_NEW
            if not hasattr(core, 'mvsf'):
                raise ImportError(
                    "MVTools: With the current settings, the processing has to be done in float precision, but you're"
                    "missing mvsf.\n\tPlease download it from: https://github.com/IFeelBloated/vapoursynth-mvtools-sf"
                )
            if not hasattr(core.mvsf, 'Degrain'):
                if tr > 24:
                    raise ImportError(
                        "MVTools: With the current settings, (temporal radius > 24) you're gonna need the latest "
                        "master of mvsf and you're using an older version."
                        "\n\tPlease build it from: https://github.com/IFeelBloated/vapoursynth-mvtools-sf"
                    )
                self.mvtools = self._MVTools.FLOAT_OLD
        else:
            if not hasattr(core, 'mv'):
                raise ImportError(
                    "MVTools: You're missing mvtools."
                    "\n\tPlease download it from: https://github.com/dubhater/vapoursynth-mvtools"
                )
            self.mvtools = self._MVTools.INTEGER

        if isinstance(prefilter, vs.VideoNode):
            self._check_ref_clip(prefilter)

    def analyze(
        self, ref: vs.VideoNode | None = None,
        blksize: int | None = None, overlap: int | None = None,
        search: int | None = None, pelsearch: int | None = None,
        searchparam: int | None = None, truemotion: bool | None = None,
        force: bool = False
    ) -> MVTools:
        ref = fallback(ref, self.workclip)

        self._check_ref_clip(ref)

        if not isinstance(blksize, int) and blksize is not None:
            raise ValueError("MVTools.analyse: 'blksize' has to be an int or None!")

        if not isinstance(overlap, int) and overlap is not None:
            raise ValueError("MVTools.analyse: 'overlap' has to be an int or None!")

        if not isinstance(search, int) and search is not None:
            raise ValueError("MVTools.analyse: 'search' has to be an int or None!")

        if not isinstance(pelsearch, int) and pelsearch is not None:
            raise ValueError("MVTools.analyse: 'pelsearch' has to be an int or None!")

        if not isinstance(searchparam, int) and searchparam is not None:
            raise ValueError("MVTools.analyse: 'searchparam' has to be an int or None!")

        if not isinstance(truemotion, bool) and truemotion is not None:
            raise ValueError("MVTools: 'truemotion' has to be a boolean or None!")
        truemotion = fallback(truemotion, not self.isHD)

        searchparam = fallback(
            searchparam, (2 if self.isUHD else 5) if (
                self.refine and truemotion
            ) else (1 if self.isUHD else 2)
        )

        searchparamr = max(0, round(exp(0.69 * searchparam - 1.79) - 0.67))

        pelsearch = fallback(pelsearch, max(0, searchparam * 2 - 2))

        blocksize = max(
            self.refine and 2 ** (self.refine + 2),
            fallback(blksize, 16 if self.isHD else 8)
        )

        halfblocksize = max(8, blocksize // 2)
        halfoverlap = max(2, halfblocksize // 2)

        overlap = fallback(overlap, halfblocksize)

        search = fallback(search, 4 if self.refine else 2)

        pref = self._get_prefiltered_clip(ref)
        pelclip, pelclip2 = self._get_subpel_clip(pref, ref)

        common_args: Dict[str, Any] = dict(
            sharp=min(self.subpixel, 2), pel=self.pel, vpad=self.vpadU, hpad=self.hpadU, chroma=self.chroma
        )
        super_render_args: Dict[str, Any] = common_args | dict(
            hpad=self.hpad, vpad=self.vpad, chroma=not self.is_gray, levels=1
        )

        if pelclip or pelclip2:
            common_args |= dict(pelclip=pelclip)
            super_render_args |= dict(pelclip=pelclip2)

        super_search = self.mvtools.Super(ref, **common_args, rfilter=self.rfilter)
        super_render = self.mvtools.Super(self.workclip, **super_render_args)
        super_recalculate = self.mvtools.Super(pref, **common_args, levels=1) if self.refine else super_render

        recalculate_SAD = round(exp(-101. / (150 * 0.83)) * 360)
        t2 = (self.tr * 2 if self.tr > 1 else self.tr) if self.source_type.is_inter else self.tr

        analyse_args: Dict[str, Any] = dict(
            overlap=overlap, blksize=blocksize, search=search, chroma=self.chroma, truemotion=truemotion,
            dct=self.DCT, searchparam=searchparam, pelsearch=pelsearch, plevel=0, pglobal=11
        )

        recalculate_args: Dict[str, Any] = dict(
            overlap=halfoverlap, blksize=halfblocksize,
            search=0, chroma=self.chroma, truemotion=truemotion,
            dct=5, searchparam=searchparamr, thsad=recalculate_SAD
        )

        if self.mvtools == MVTools._MVTools.FLOAT_NEW:
            vmulti = self.mvtools.Analyse(super_search, radius=t2, **analyse_args)

            if self.source_type.is_inter:
                vmulti = vmulti.std.SelectEvery(4, 2, 3)

            self.vectors['vmulti'] = vmulti

            for i in range(self.refine):
                recalculate_args.update(
                    blksize=blocksize / 2 ** i, overlap=blocksize / 2 ** (i + 1)
                )
                self.vectors['vmulti'] = self.mvtools.Recalculate(
                    super_recalculate, self.vectors['vmulti'], **recalculate_args
                )
        else:
            def _add_vector(delta: int, recalculate: bool = False) -> None:
                if recalculate:
                    vects = {
                        'b': self.mvtools.Recalculate(
                            super_recalculate, self.vectors[f'bv{delta}'], **recalculate_args
                        ),
                        'f': self.mvtools.Recalculate(
                            super_recalculate, self.vectors[f'fv{delta}'], **recalculate_args
                        )
                    }
                else:
                    vects = {
                        'b': self.mvtools.Analyse(super_search, isb=True, delta=delta, **analyse_args),
                        'f': self.mvtools.Analyse(super_search, isb=False, delta=delta, **analyse_args)
                    }

                for k, vect in vects.items():
                    self.vectors[f'{k}v{delta}'] = vect

            for i in range(1, self.tr + 1):
                _add_vector(i)

            if self.refine:
                refblks = blocksize
                for i in range(1, t2 + 1):
                    if not self.vectors[f'bv{i}'] or not self.vectors[f'fv{i}']:
                        continue

                    for j in range(1, self.refine):
                        val = (refblks / 2 ** j)
                        if val > 128:
                            refblks = 128
                        elif val < 4:
                            refblks = blocksize

                        recalculate_args.update(
                            blksize=refblks / 2 ** j, overlap=refblks / 2 ** (j + 1)
                        )

                        _add_vector(i, True)

        self.vectors['super_render'] = super_render

        return self

    def get_vectors_bv(self, func_name: str = '') -> Tuple[List[vs.VideoNode], List[vs.VideoNode]]:
        if not self.vectors:
            raise RuntimeError(
                f"MVTools{'.' if func_name else ''}{func_name}: you first need to analyze the clip!"
            )

        t2 = (self.tr * 2 if self.tr > 1 else self.tr) if self.source_type.is_inter else self.tr

        vectors_backward: List[vs.VideoNode] = []
        vectors_forward: List[vs.VideoNode] = []

        if self.mvtools == MVTools._MVTools.FLOAT_NEW:
            vmulti = self.vectors['vmulti']

            for i in range(0, t2 * 2, 2):
                vectors_backward.append(vmulti.std.SelectEvery(t2 * 2, i))
                vectors_forward.append(vmulti.std.SelectEvery(t2 * 2, i + 1))
        else:
            for i in range(1, self.tr + 1):
                vectors_backward.append(self.vectors[f'bv{i}'])
                vectors_forward.append(self.vectors[f'fv{i}'])

        return (vectors_backward, vectors_forward)

    def compensate(
        self, func: LambdaVSFunction, thSAD: int = 150, **kwargs: KwArgsT
    ) -> vs.VideoNode:
        if not callable(func):
            raise RuntimeError("MVTools.compensate: 'func' has to be a function!")

        if not isinstance(thSAD, int):
            raise ValueError("MVTools.compensate: 'thSAD' has to be an int!")

        vect_b, vect_f = self.get_vectors_bv('compensate')

        comp_back, comp_forw = tuple(
            map(
                lambda vect: self.mvtools.Compensate(
                    self.workclip, super=self.vectors['super_render'],
                    vectors=vect, thsad=thSAD,
                    tff=self.source_type.is_inter and self.source_type.value or None
                ), vectors
            ) for vectors in (reversed(vect_b), vect_f)
        )

        comp_clips = [*comp_forw, self.workclip, *comp_back]
        n_clips = len(comp_clips)

        interleaved = core.std.Interleave(comp_clips)

        processed = func(interleaved, **kwargs)

        return processed.std.SelectEvery(cycle=n_clips, offsets=ceil(n_clips / 2))

    def degrain(
        self, ref: vs.VideoNode | None = None,
        thSAD: int = 300, thSADC: int | None = None,
        thSCD1: int | None = None, thSCD2: int = 130,
        limit: int | None = None, limitC: float | None = None
    ) -> vs.VideoNode:
        self._check_ref_clip(ref)

        if not isinstance(thSAD, int):
            raise ValueError("MVTools.degrain: 'thSAD' has to be an int!")

        if not isinstance(thSADC, int) and thSADC is not None:
            raise ValueError("MVTools.degrain: 'thSADC' has to be an int or None!")

        if not isinstance(thSCD1, int) and thSCD1 is not None:
            raise ValueError("MVTools.degrain: 'thSCD1' has to be an int or None!")

        if not isinstance(thSCD2, int):
            raise ValueError("MVTools.degrain: 'thSCD2' has to be an int!")

        if not isinstance(limit, int) and limit is not None:
            raise ValueError("MVTools.degrain: 'limit' has to be an int or None!")
        limit = fallback(limit, 2 if self.isUHD else 255)

        if not isinstance(limitC, float) and limitC is not None:
            raise ValueError("MVTools.degrain: 'limitC' has to be a float or None!")
        limitC = fallback(limitC, limit)

        thrSAD = self._SceneAnalyzeThreshold(
            round(exp(-101. / (thSAD * 0.83)) * 360),
            fallback(thSADC, round(thSAD * 0.18875 * exp(2 * 0.693)))

        )

        thrSCD = self._SceneChangeThreshold(
            fallback(thSCD1, round(0.35 * thSAD + 260)),
            fallback(thSCD2, 130)
        )

        t2 = (self.tr * 2 if self.tr > 1 else self.tr) if self.source_type.is_inter else self.tr

        vect_b, vect_f = self.get_vectors_bv('degrain')

        # Finally, MDegrain

        degrain_args: Dict[str, Any] = dict(
            thscd1=thrSCD.first, thscd2=thrSCD.second, plane=self.mvplane
        )

        if self.mvtools == MVTools._MVTools.INTEGER:
            degrain_args.update({
                'thsad': thrSAD.luma, 'thsadc': thrSAD.chroma,
                'limit': limit, 'limitc': limitC
            })
        else:
            degrain_args.update({
                'thsad': [thrSAD.luma, thrSAD.chroma, thrSAD.chroma],
                'limit': [limit, limitC]
            })

            if self.mvtools == MVTools._MVTools.FLOAT_NEW:
                degrain_args.update({
                    'thsad2': [thrSAD.luma / 2, thrSAD.chroma / 2]
                })

        to_degrain = ref or self.workclip

        if self.mvtools != MVTools._MVTools.FLOAT_NEW:
            degrain_vectors = []
            it = 1 + int(self.source_type.is_inter)
            for i in range(it, t2 + 1, it):
                degrain_vectors.append(self.vectors[f'bv{i}'])
                degrain_vectors.append(self.vectors[f'fv{i}'])
            output: vs.VideoNode = self.mvtools.Degrain(self.tr)(
                to_degrain, self.vectors['super_render'], *degrain_vectors, **degrain_args
            )
        else:
            output = self.mvtools.Degrain()(
                to_degrain, self.vectors['super_render'], self.vectors['vmulti'], **degrain_args
            )

        return output.std.DoubleWeave(self.source_type.value) if self.source_type.is_inter else output

    def _get_subpel(self, clip: vs.VideoNode, pel_type: PelType) -> vs.VideoNode | None:
        bicubic_args: Dict[str, Any] = dict(width=clip.width * self.pel, height=(clip.height * self.pel))

        if pel_type == PelType.BICUBIC or pel_type == PelType.WIENER:
            if pel_type == PelType.WIENER:
                bicubic_args |= blackman_args
            return clip.resize.Bicubic(**bicubic_args)
        elif pel_type == PelType.NNEDI3:
            nnargs = dict(nsize=0, nns=1, qual=1, pscrn=2)

            nmsp = 'znedi3' if hasattr(core, 'znedi3') else 'nnedi3'

            nnedi3_cpu = getattr(
                getattr(clip.std.Transpose(), nmsp).nnedi3(0, True, **nnargs).std.Transpose(), nmsp
            ).nnedi3(0, True, **nnargs)

            if hasattr(core, 'nnedi3cl'):
                upscale = core.std.Interleave([
                    nnedi3_cpu[::2], clip[1::2].nnedi3cl.NNEDI3CL(0, True, True, **nnargs)  # type: ignore
                ])
            else:
                upscale = nnedi3_cpu

            return upscale.resize.Bicubic(src_top=.5, src_left=.5)

        return None

    def _get_subpel_clip(
        self, pref: vs.VideoNode, ref: vs.VideoNode
    ) -> Tuple[vs.VideoNode | None, vs.VideoNode | None]:
        pel_types = list(self.pel_type)

        for i, val in enumerate(pel_types):
            if val != PelType.AUTO:
                continue

            if i == 0:
                if self.prefilter == Prefilter.NONE:
                    pel_types[i] = PelType.NONE
                else:
                    if self.subpixel == 4:
                        pel_types[i] = PelType.NNEDI3
                    else:
                        pel_types[i] = PelType.BICUBIC
            else:
                pel_types[i] = PelType.NNEDI3 if self.subpixel == 4 else PelType.WIENER

        pel_type, pel2_type = pel_types

        return self._get_subpel(pref, pel_type), self._get_subpel(ref, pel2_type)

    def _get_pref(self, clip: vs.VideoNode, pref_type: Prefilter | vs.VideoNode) -> vs.VideoNode:
        if pref_type == Prefilter.NONE or isinstance(pref_type, vs.VideoNode):
            return clip
        elif pref_type.value in {0, 1, 2}:
            return MinBlur(clip, pref_type.value, self.planes)
        elif pref_type == Prefilter.MINBLURFLUX:
            return MinBlur(clip, 2).flux.SmoothST(2, 2, self.planes)
        elif pref_type == Prefilter.DFTTEST:
            bits = get_depth(clip)
            peak = get_peak_value(clip)

            y = get_y(clip)
            i = scale_value(16, 8, bits, range=CRange.FULL)
            j = scale_value(75, 8, bits, range=CRange.FULL)

            dfft = clip.dfttest.DFTTest(
                tbsize=1, slocation=[0.0, 4.0, 0.2, 9.0, 1.0, 15.0],
                sbsize=12, sosize=6, swin=2
            )

            prefmask = y.std.Expr(f'x {i} < {peak} x {j} > 0 {peak} x {i} - {peak} {j} {i} - / * - ? ?')

            return dfft.std.MaskedMerge(clip, prefmask)
        elif pref_type == Prefilter.KNLMEANSCL:
            knl = knl_means_cl(
                clip, 7.0, 1, 2, 2, ChannelMode.ALL_PLANES if self.chroma else ChannelMode.LUMA,
                device_id=self.device_id
            )

            return self._ReplaceLowFrequency(knl, clip, 600 * (clip.width / 1920), chroma=self.chroma)
        elif pref_type == Prefilter.BM3D:
            return self.bm3d_arch(
                clip, sigma=10 if isinstance(self.bm3d_arch, _AbstractBM3DCuda) else 8,
                radius=1, profile=Profile.LOW_COMPLEXITY
            ).clip
        elif pref_type == Prefilter.DGDENOISE:
            # dgd = core.dgdecodenv.DGDenoise(pref, 0.10)

            # pref = self._ReplaceLowFrequency(dgd, pref, w / 2, chroma=self.chroma)
            return clip.bilateral.Gaussian(1)

        return clip

    def _get_prefiltered_clip(self, pref: vs.VideoNode) -> vs.VideoNode:
        if isinstance(self.prefilter, vs.VideoNode):
            return self.prefilter

        pref = self._get_pref(pref, Prefilter.MINBLUR3 if self.prefilter == Prefilter.AUTO else self.prefilter)

        # Luma expansion TV->PC (up to 16% more values for motion estimation)
        if self.range_in == CRange.LIMITED:
            if self.rangeConversion > 1.0:
                pref = DitherLumaRebuild(pref, self.rangeConversion)
            elif self.rangeConversion > 0.0:
                pref = pref.retinex.MSRCP(None, self.rangeConversion, None, False, True)
            else:
                pref = depth(pref, 8, range=CRange.FULL, range_in=CRange.LIMITED, dither_type=Dither.NONE)

        return pref

    @staticmethod
    def _ReplaceLowFrequency(
        flt: vs.VideoNode, ref: vs.VideoNode, LFR: float, DCTFlicker: bool = False, chroma: bool = True
    ) -> vs.VideoNode:
        assert flt.format
        LFR = max(LFR or (300 * flt.width / 1920), 50)

        freq_sample = max(flt.width, flt.height) * 2    # Frequency sample rate is resolution * 2 (for Nyquist)
        k = sqrt(log(2) / 2) * LFR                      # Constant for -3dB
        LFR = freq_sample / (k * 2 * pi)                # Frequency Cutoff for Gaussian Sigma
        sec0 = sin(e) + .1

        sec = scale_value(sec0, 8, flt.format.bits_per_sample, range=CRange.FULL)

        expr = "x y - z + "

        if DCTFlicker:
            expr += f"y z - d! y z = swap dup d@ 0 = 0 d@ 0 < -1 1 ? ? {sec} * + ?"

        final = core.akarin.Expr([flt, flt.bilateral.Gaussian(LFR), ref.bilateral.Gaussian(LFR)], expr)

        return final if chroma else core.std.ShufflePlanes([final, flt], [0, 1, 2], vs.YUV)

    def _get_planes(self, planes: Sequence[int]) -> Tuple[List[int], int]:
        if not (isinstance(planes, Sequence) and isinstance(planes[0], int)):
            raise ValueError("'planes' has to be a sequence of ints!")

        if planes == [0, 1, 2]:
            mvplane = 4
        elif len(planes) == 1 and planes[0] in {0, 1, 2}:
            mvplane = planes[0]
        elif planes == [1, 2]:
            mvplane = 3
        else:
            raise ValueError("Invalid planes specified!")

        return list(planes), mvplane

    def _check_ref_clip(self, ref: vs.VideoNode | None) -> vs.VideoNode | None:
        if not isinstance(ref, vs.VideoNode) and ref is not None:
            raise ValueError('Ref clip has to be a VideoNode or None!')

        if ref is None:
            return None

        assert self.workclip.format
        assert ref.format

        if ref.format.id != self.workclip.format.id:
            raise ValueError("Ref clip format must match the source clip's!")

        if ref.width != self.workclip.width or ref.height != self.workclip.height:
            raise ValueError("Ref clip sizes must match the source clip's!")

        return ref
