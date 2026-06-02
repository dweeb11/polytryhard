from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

_Z = 1.96  # ~95% normal credible interval
_VAR_FLOOR = 1e-9  # avoid divide-by-zero when all ROIs are identical


@dataclass(frozen=True)
class PosteriorEdge:
    mean: float
    ci_low: float
    ci_high: float


def posterior_edge(rois: list[float], *, tau: float = 0.5) -> PosteriorEdge:
    """Normal-Normal posterior on per-trade ROI with skeptical prior N(0, tau^2).

    See docs/design/m5-eval.md §6. Degenerate-n handling:
      n == 0 -> prior (mean 0, CI from tau)
      n == 1 -> prior-scale variance (tau^2): shrinks toward 0, stays wide
      n >= 2 -> sample variance (ddof=1), floored to stay finite
    """
    prior_precision = 1.0 / (tau**2)
    n = len(rois)
    if n == 0:
        sd = math.sqrt(1.0 / prior_precision)
        return PosteriorEdge(mean=0.0, ci_low=-_Z * sd, ci_high=_Z * sd)

    mean_roi = statistics.fmean(rois)
    if n == 1:
        sigma2 = tau**2
    else:
        sigma2 = max(statistics.variance(rois), _VAR_FLOOR)

    data_precision = n / sigma2
    post_precision = prior_precision + data_precision
    post_mean = (mean_roi * data_precision) / post_precision
    post_sd = math.sqrt(1.0 / post_precision)
    return PosteriorEdge(
        mean=post_mean,
        ci_low=post_mean - _Z * post_sd,
        ci_high=post_mean + _Z * post_sd,
    )
