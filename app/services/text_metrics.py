"""Text error-rate helpers for transcription evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import unicodedata


@dataclass(frozen=True)
class CERResult:
    cer: float | None
    distance: int
    reference_length: int
    hypothesis_length: int
    normalized_reference: str
    normalized_hypothesis: str

    def to_dict(self) -> dict[str, float | int | str | None]:
        return asdict(self)


def _edit_distance(a: list[str], b: list[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, token_a in enumerate(a, start=1):
        current = [i]
        for j, token_b in enumerate(b, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (token_a != token_b)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def levenshtein_distance(a: list[str], b: list[str]) -> int:
    try:
        from rapidfuzz.distance import Levenshtein

        return int(Levenshtein.distance(a, b))
    except ImportError:
        return _edit_distance(a, b)


def character_levenshtein_distance(a: str, b: str) -> int:
    try:
        from rapidfuzz.distance import Levenshtein

        return int(Levenshtein.distance(a, b))
    except ImportError:
        return _edit_distance(list(a), list(b))


def normalize_for_strict_cer(text: str) -> str:
    return text.strip()


def normalize_for_content_cer(text: str) -> str:
    """Normalize text for content-focused Japanese CER.

    Strict CER is useful for checking exact transcript formatting, but LLM
    correction often adds punctuation and spaces. This normalizer keeps lexical
    content while removing whitespace and punctuation.
    """

    normalized = unicodedata.normalize("NFKC", text).casefold()
    chars: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if char.isspace() or category.startswith("P"):
            continue
        chars.append(char)
    return "".join(chars)


def character_error_rate(reference: str, hypothesis: str) -> CERResult:
    distance = character_levenshtein_distance(reference, hypothesis)
    reference_length = len(reference)
    return CERResult(
        cer=distance / reference_length if reference_length else None,
        distance=distance,
        reference_length=reference_length,
        hypothesis_length=len(hypothesis),
        normalized_reference=reference,
        normalized_hypothesis=hypothesis,
    )


def compare_cer(reference: str, hypothesis: str) -> dict[str, dict[str, float | int | str | None]]:
    strict = character_error_rate(
        normalize_for_strict_cer(reference),
        normalize_for_strict_cer(hypothesis),
    )
    content = character_error_rate(
        normalize_for_content_cer(reference),
        normalize_for_content_cer(hypothesis),
    )
    return {
        "strict": strict.to_dict(),
        "content": content.to_dict(),
    }


def relative_cer_reduction(baseline_cer: float | None, corrected_cer: float | None) -> float | None:
    if baseline_cer is None or corrected_cer is None or baseline_cer <= 0:
        return None
    return (baseline_cer - corrected_cer) / baseline_cer
