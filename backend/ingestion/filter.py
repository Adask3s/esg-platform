from __future__ import annotations
from typing import List, Tuple
import re
from .models import KeywordFilterConfig


def _normalize(s: str, case_sensitive: bool) -> str:
    return s if case_sensitive else s.lower()


def _block_matches(block: str, cfg: KeywordFilterConfig) -> bool:
    if not cfg.keywords:
        return True
    b = _normalize(block, cfg.case_sensitive)
    keys = [_normalize(k, cfg.case_sensitive) for k in cfg.keywords if k]
    if not keys:
        return True
    if cfg.match_all:
        return all(k in b for k in keys)
    else:
        return any(k in b for k in keys)


def keyword_filter_blocks(blocks: List[str], cfg: KeywordFilterConfig) -> Tuple[List[str], List[int]]:
    """
    Select blocks that match keywords and include context windows.
    Returns (filtered_blocks, indices_kept)
    """
    if not blocks:
        return [], []

    hits = [i for i, b in enumerate(blocks) if _block_matches(b, cfg)]
    if not hits and cfg.keywords:
        # nothing matched, return empty
        return [], []

    keep: set[int] = set()
    for i in (hits if hits else range(len(blocks))):
        start = max(0, i - cfg.context_before)
        end = min(len(blocks), i + 1 + cfg.context_after)
        for j in range(start, end):
            keep.add(j)

    kept_indices = sorted(list(keep))
    filtered = [blocks[i] for i in kept_indices]
    return filtered, kept_indices
