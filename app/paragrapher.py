from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

ABBREV_RE = re.compile(
    r"(?:^|\s)(?:"
    r"Mr|Mrs|Ms|Dr|Prof|Rev|Hon|Pres|Gov|Sen|Rep|Gen|Col|Maj|Capt|Lt|Sgt|"
    r"St|Mt|Ft|Ave|Blvd|Rd|Inc|Ltd|Corp|Co|Jr|Sr|vs|etc|No|Vol|Fig|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
    r"U\.S|U\.K|U\.N|B\.C|P\.E\.I|N\.S|N\.B|N\.L|N\.W\.T|D\.C|E\.U|C\.B\.C|"
    r"a\.m|p\.m|e\.g|i\.e|[A-Z]"
    r")\.$",
    re.IGNORECASE,
)

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to", "for", "of", "by", "with",
    "from", "as", "is", "was", "are", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might", "must", "can", "it", "its",
    "he", "him", "his", "she", "her", "they", "them", "their", "we", "us", "our", "you", "your",
    "i", "me", "my", "this", "that", "these", "those", "there", "here", "where", "when", "who",
    "which", "what", "why", "how", "not", "no", "so", "up", "out", "about", "into", "over", "after",
    "before", "between", "under", "again", "then", "once", "all", "any", "both", "each", "few",
    "more", "most", "other", "some", "such", "only", "own", "same", "than", "too", "very", "just",
    "also", "now", "say", "says", "said", "new", "one", "two", "year", "years", "day", "days",
    "time", "people", "make", "made", "get", "getting", "got", "going", "go", "still", "even",
    "well", "back", "way", "take", "taking", "took", "many", "much", "around", "through", "part",
    "calling", "proposing", "seeing", "helping", "using", "starting", "next", "week", "last",
}

CONTINUATION_START_RE = re.compile(
    r"^(?:He|She|They|It|Its|His|Her|Their|This|That|These|Those|But|However|Still|Also|Yet|So|And\s+now|"
    r"Because|Although|While|Then|Later|Earlier|Simply|Either|Neither|One\s+of|Here(?:'s|\s+is)|"
    r"Put\s+very\s+simply|If\s+passed|If\s+you|Targeted|Starting\s+(?:next|this|today|tomorrow)|"
    r"The\s+(?:province|company|group|court|board|minister|report|study|move|decision|deal|plan|"
    r"bill|law|agency|lab|team|city|country|union|police|military|officials|spokesperson|ruling|"
    r"case|investigation|statement|proposal|program|project|organization|committee|department|"
    r"bank|market|system|storm|fire|search|strike|provincial|oil\s+revenue|ultra\s+project)\b|"
    r"The\s+government\s+(?:is|was|has|says|said|will|wants|plans)\b)",
    re.IGNORECASE,
)

EXPLICIT_SECTION_START_RE = re.compile(
    r"^(?:From\s+CBC\s+News|This\s+is\s+CBC\s+News|And\s+(?:that's|to)\s+(?:the\s+)?world\s+this\s+hour|"
    r"That(?:'s|\s+is)\s+(?:the\s+latest|The\s+World\s+This\s+Hour)|"
    r"Meanwhile,|In\s+other\s+news|Turning\s+to|Internationally,|Overseas,|On\s+the\s+(?:West|East)\s+Coast|"
    r"And\s+finally|Finally,|Now\s+to\b)",
    re.IGNORECASE,
)

STORY_CLOSER_RE = re.compile(
    r"(?:declin(?:ed|ing)\s+to\s+comment(?:\s+on\s+[^.]+)?\.?$|"
    r"wherever\s+you\s+get\s+your\s+podcasts\.?$|"
    r"Except\s+maybe\s+there\.?$|"
    r"on\s+CBC\s+(?:Listen|Gem)\.?$|"
    r"The\s+World\s+This\s+Hour\.\s*I'm\s+[^.]+\.?$)",
    re.IGNORECASE,
)

REPORTER_SIGNOFF_RE = re.compile(
    r"^(?!From\s+CBC|This\s+is\s+CBC)[A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){1,2},\s+CBC\s+News,\s+[A-Z][A-Za-z.'\s]+\.?$"
)
REPORTER_INTRO_RE = re.compile(r"^[A-Z][a-z]+\s+[A-Z][a-z.'-]+\s+reports\.?$")

NEW_ENTITY_OPEN_RE = re.compile(
    r"^(?:The\s+(?:government\s+of\s+[A-Z]|head\s+of\s+the\s+[A-Z]|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(?:government|prime\s+minister|president|military|court|bank|central\s+bank|parliament|senate|house))|"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}(?:'s)?\s+(?:return|is|has|says|said|announced|warns|warned|wants|called|calls|resigned|faces|will)\b|"
    r"(?:Finance|Health|Foreign|Defence|Defense|Justice|Transport|Housing|Environment|Trade)\s+Minister\s+[A-Z])",
)


def _split_segment_into_clauses(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts: list[str] = []
    start = 0
    for m in re.finditer(r"([.?!])([\"'”’\)]*)(?=\s+[A-Z0-9\"'“‘]|$)", text):
        end_pos = m.end()
        candidate = text[start:end_pos].strip()
        if m.group(1) == ".":
            if re.search(r"\d\.$", candidate) or ABBREV_RE.search(candidate):
                continue
        parts.append(candidate)
        start = end_pos
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _ends_complete_sentence(text: str) -> bool:
    t = (text or "").strip().rstrip("\"'”’)]")
    if not t or t[-1] not in ".?!":
        return False
    if t[-1] in "?!":
        return True
    if re.search(r"\d\.$", t) or ABBREV_RE.search(t):
        return False
    return True


def _split_zh_clauses(zh: str, n: int) -> list[str]:
    zh = (zh or "").strip()
    if n <= 1:
        return [zh]
    parts = [p.strip() for p in re.split(r"(?<=[。？！])", zh) if p.strip()]
    if len(parts) == n:
        return parts
    comma_parts = [p.strip() for p in re.split(r"(?<=[，。？！；])", zh) if p.strip()]
    if len(comma_parts) >= n:
        out: list[str] = []
        per = len(comma_parts) / n
        for i in range(n):
            a = int(round(i * per))
            b = int(round((i + 1) * per)) if i < n - 1 else len(comma_parts)
            out.append("".join(comma_parts[a:b]).strip())
        return out
    out, cur, step = [], 0, max(1, len(zh) // n)
    for i in range(n):
        nxt = len(zh) if i == n - 1 else cur + step
        out.append(zh[cur:nxt].strip())
        cur = nxt
    return out


def build_complete_sentences(raw_segments: list[dict[str, Any]], keep_zh: bool = False) -> list[dict[str, Any]]:
    """Reconstruct complete English sentences (and optionally paired Chinese) from Whisper segments."""
    pieces: list[dict[str, Any]] = []
    for seg in raw_segments:
        s_start = float(seg["start"])
        s_end = max(float(seg["end"]), s_start + 0.2)
        raw_text = re.sub(r"\s+", " ", (seg.get("en") or seg.get("text") or "")).strip()
        if not raw_text:
            continue

        clauses = _split_segment_into_clauses(raw_text)
        zh_clauses = _split_zh_clauses(seg.get("zh", ""), len(clauses)) if keep_zh else [""] * len(clauses)
        total_chars = max(1, sum(len(c) for c in clauses))
        cursor = s_start
        for idx, (clause, zh_c) in enumerate(zip(clauses, zh_clauses)):
            frac = len(clause) / total_chars
            c_end = s_end if idx == len(clauses) - 1 else round(cursor + (s_end - s_start) * frac, 2)
            pieces.append(
                {
                    "start": round(cursor, 2),
                    "end": max(round(c_end, 2), round(cursor + 0.2, 2)),
                    "en": clause,
                    "zh": zh_c,
                }
            )
            cursor = c_end

    sentences: list[dict[str, Any]] = []
    for p in pieces:
        if sentences and not _ends_complete_sentence(sentences[-1]["en"]):
            sentences[-1]["en"] = f"{sentences[-1]['en']} {p['en']}".strip()
            if keep_zh:
                sentences[-1]["zh"] = f"{sentences[-1]['zh']}{p['zh']}".strip()
            sentences[-1]["end"] = p["end"]
        elif (
            sentences
            and re.search(r"The\s+World\s+This\s+Hour\.$", sentences[-1]["en"], re.IGNORECASE)
            and re.match(r"^I'm\s+[A-Z]", p["en"])
        ):
            sentences[-1]["en"] = f"{sentences[-1]['en']} {p['en']}"
            if keep_zh:
                sentences[-1]["zh"] = f"{sentences[-1]['zh']}{p['zh']}"
            sentences[-1]["end"] = p["end"]
        else:
            sentences.append({"start": p["start"], "end": p["end"], "en": p["en"], "zh": p["zh"]})

    for idx, s in enumerate(sentences):
        s["id"] = idx
        s["gap_before"] = round(max(0.0, s["start"] - sentences[idx - 1]["end"]), 2) if idx > 0 else 0.0
    return sentences


def _content_tokens(text: str) -> Counter:
    raw = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text.lower())
    out = Counter()
    for tok in raw:
        tok = tok.strip("'-")
        if len(tok) < 3 or tok in STOPWORDS:
            continue
        for suf in ("ings", "ing", "ions", "ion", "ies", "ful", "ed", "es", "s"):
            if len(tok) > len(suf) + 3 and tok.endswith(suf):
                tok = tok[: -len(suf)]
                break
        out[tok] += 1
    return out


def _cosine_sim(c1: Counter, c2: Counter) -> float:
    if not c1 or not c2:
        return 0.0
    common = set(c1.keys()) & set(c2.keys())
    num = sum(c1[k] * c2[k] for k in common)
    if num == 0:
        return 0.0
    den = math.sqrt(sum(v * v for v in c1.values()) * sum(v * v for v in c2.values()))
    return num / den if den > 0 else 0.0


def assign_paragraphs(sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign coherent topic/story `paragraph` indices to complete sentences."""
    if not sentences:
        return []

    paragraphs: list[list[dict[str, Any]]] = [[sentences[0]]]

    for i in range(1, len(sentences)):
        cur_para = paragraphs[-1]
        prev_s = sentences[i - 1]
        curr_s = sentences[i]

        prev_en = prev_s["en"]
        curr_en = curr_s["en"]
        gap = float(curr_s.get("gap_before", max(0.0, curr_s["start"] - prev_s["end"])))
        para_words = sum(len(s["en"].split()) for s in cur_para)

        left_text = " ".join(s["en"] for s in cur_para[-4:])
        right_text = curr_en + (" " + sentences[i + 1]["en"] if i + 1 < len(sentences) else "")
        sim = _cosine_sim(_content_tokens(left_text), _content_tokens(right_text))

        # Keep reporter sign-off / lead-in attached to its paragraph
        if REPORTER_SIGNOFF_RE.match(curr_en) or REPORTER_INTRO_RE.match(curr_en):
            cur_para.append(curr_s)
            continue

        hard_break = False
        if STORY_CLOSER_RE.search(prev_en) or REPORTER_SIGNOFF_RE.match(prev_en):
            hard_break = True
        if EXPLICIT_SECTION_START_RE.search(curr_en):
            hard_break = True
        if gap >= 3.0:
            hard_break = True

        if hard_break:
            paragraphs.append([curr_s])
            continue

        # Never orphan a 1-sentence tail right before a reporter sign-off
        if i + 1 < len(sentences) and REPORTER_SIGNOFF_RE.match(sentences[i + 1]["en"]):
            cur_para.append(curr_s)
            continue

        score = 0.0
        if gap >= 1.2:
            score += 1.6
        elif gap >= 0.7:
            score += 0.7

        if NEW_ENTITY_OPEN_RE.search(curr_en):
            score += 1.7

        if sim == 0.0 and len(cur_para) >= 2:
            score += 1.4
        elif sim < 0.07 and len(cur_para) >= 3:
            score += 0.8
        elif sim >= 0.18:
            score -= 1.6

        if CONTINUATION_START_RE.search(curr_en):
            score -= 2.4

        if para_words >= 95 and not CONTINUATION_START_RE.search(curr_en) and (sim < 0.14 or NEW_ENTITY_OPEN_RE.search(curr_en)):
            score += 1.4

        if len(cur_para) == 1 and para_words < 22:
            score -= 1.5

        if score >= 1.9:
            paragraphs.append([curr_s])
        else:
            cur_para.append(curr_s)

    out: list[dict[str, Any]] = []
    for p_idx, para in enumerate(paragraphs):
        for s in para:
            out.append(
                {
                    "id": len(out),
                    "paragraph": p_idx,
                    "start": round(float(s["start"]), 2),
                    "end": round(float(s["end"]), 2),
                    "en": s["en"],
                    "zh": s.get("zh", ""),
                }
            )
    return out


def upgrade_subtitles_with_paragraphs(subtitles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upgrade legacy flat subtitles (already containing en & zh) into complete-sentence paragraph-grouped subtitles."""
    if not subtitles:
        return []
    if all("paragraph" in s for s in subtitles):
        return subtitles
    complete = build_complete_sentences(subtitles, keep_zh=True)
    return assign_paragraphs(complete)
