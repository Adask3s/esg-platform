from __future__ import annotations
from typing import List, Tuple
import re
from .models import Chunk, ChunkConfig


BULLET_RE = re.compile(r"^\s*([\-•\*\u2022\u25CB\u25CF]|\d+\.|[a-zA-Z]\))\s+")
HEADING_RE = re.compile(r"^\s*(?:[A-Z][A-Z0-9\s\-]{3,}|\d+(?:\.|\))\s+.+)$")


def estimate_tokens(text: str) -> int:
    """
    Lightweight token estimator: assumes ~1.3 words per token in many LLMs.
    Fallback approximation using whitespace-separated words and punctuation density.
    """
    if not text:
        return 0
    # Count words
    words = re.findall(r"\w+", text)
    word_count = len(words)
    # Adjust for punctuation-heavy text
    punct = len(re.findall(r"[,:;.!?]", text))
    approx = int((word_count + 0.5 * punct) / 0.75)  # conservative
    return max(1, approx)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def make_blocks(text: str) -> List[str]:
    """
    Create structure-aware blocks from text:
    - Split by double newlines for paragraphs.
    - Merge consecutive bullet list lines into a single block.
    - Keep headings with following short paragraph (if tiny alone).
    - Repair common PDF line issues (hyphenation and mid-word line breaks).
    """
    text = normalize_newlines(text)

    # 1) Repair hyphenation across line breaks: "foto-\n
    # woltaicznych" -> "fotowoltaicznych"
    text = re.sub(r"-\n\s*", "", text)
    # 2) Join mid-word hard breaks without hyphen: "foto\n
    # woltaicznych" -> "fotowoltaicznych"
    text = re.sub(r"(?<=\w)\n(?=\w)", " ", text)

    # Primary paragraph split by double newlines
    raw_blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]

    # Further split blocks that are long but contain many list items
    split_blocks: List[str] = []
    for b in raw_blocks:
        lines = [ln.strip() for ln in b.split("\n") if ln.strip()]
        if len(lines) > 1 and sum(1 for ln in lines if BULLET_RE.match(ln)) >= max(2, len(lines)//3):
            # treat each bullet sequence as a block
            cur: List[str] = []
            for ln in lines:
                if BULLET_RE.match(ln):
                    if cur:
                        split_blocks.append("\n".join(cur).strip())
                        cur = []
                    split_blocks.append(ln)
                else:
                    cur.append(ln)
            if cur:
                split_blocks.append("\n".join(cur))
        else:
            split_blocks.append("\n".join(lines))

    # Attach headings to next block if heading is too short
    merged: List[str] = []
    i = 0
    while i < len(split_blocks):
        cur = split_blocks[i]
        if HEADING_RE.match(cur) and (i + 1) < len(split_blocks):
            # if heading is short, attach
            if estimate_tokens(cur) < 30:
                merged.append(cur + "\n" + split_blocks[i+1])
                i += 2
                continue
        merged.append(cur)
        i += 1

    return merged


def chunk_text(text: str, config: ChunkConfig) -> List[Chunk]:
    blocks = make_blocks(text)
    return chunk_blocks(blocks, config)


def chunk_blocks(blocks: List[str], config: ChunkConfig) -> List[Chunk]:
    chunks: List[Chunk] = []
    if not blocks:
        return chunks

    token_cache = [estimate_tokens(b) for b in blocks]

    # Aggressive handling: if we have a single block and it's reasonably long, split it by sentences
    if len(blocks) == 1:
        t = token_cache[0]
        if t >= config.target_tokens or t > config.max_tokens:
            parts = split_large_block(blocks[0], config)
            for part_text in parts:
                chunks.append(Chunk(text=part_text, token_count=estimate_tokens(part_text), start_block=0, end_block=0))
            return chunks

    i = 0
    while i < len(blocks):
        # If the next block alone exceeds max_tokens, split it immediately
        if token_cache[i] > config.max_tokens:
            big_block = blocks[i]
            parts = split_large_block(big_block, config)
            for part_text in parts:
                chunks.append(Chunk(text=part_text, token_count=estimate_tokens(part_text), start_block=i, end_block=i))
            i += 1
            continue

        # Grow window up to target, but not exceed max
        start = i
        total = 0
        end = i
        while end < len(blocks):
            next_total = total + token_cache[end]
            if next_total > config.max_tokens and end > start:
                break
            total = next_total
            end += 1
            if total >= config.target_tokens:
                break

        # If no progress (shouldn't happen due to the check above), advance safely
        if end == start:
            # include at least current block
            end = min(start + 1, len(blocks))
            total = token_cache[start]

        # If we're under min and can extend, try to add one more block
        if total < config.min_tokens and end < len(blocks):
            if total + token_cache[end] <= config.max_tokens:
                total += token_cache[end]
                end += 1

        chunk_text_str = "\n\n".join(blocks[start:end]).strip()
        chunks.append(Chunk(text=chunk_text_str, token_count=estimate_tokens(chunk_text_str), start_block=start, end_block=end-1))

        # Advance with overlap in tokens (approximate by trimming blocks)
        if end >= len(blocks):
            break
        # compute how many blocks to step back to achieve overlap
        overlap = config.overlap_tokens
        if overlap <= 0:
            i = end
        else:
            # walk backward from end-1 accumulating tokens until reach overlap
            back = end - 1
            acc = 0
            while back >= start and acc < overlap:
                acc += token_cache[back]
                back -= 1
            i = max(back + 1, start + 1)  # avoid infinite loop

    return chunks


def split_large_block(text: str, config: ChunkConfig) -> List[str]:
    # Sentence split naive
    sentences = re.split(r"(?<=[\.!?])\s+", text)
    parts: List[str] = []
    cur: List[str] = []
    cur_tok = 0
    for s in sentences:
        t = estimate_tokens(s)
        if cur and cur_tok + t > config.max_tokens:
            parts.append(" ".join(cur).strip())
            cur = []
            cur_tok = 0
        cur.append(s)
        cur_tok += t
    if cur:
        parts.append(" ".join(cur).strip())
    return parts
