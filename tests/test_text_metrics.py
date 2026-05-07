"""Tests for text-level transcription metrics."""

from app.services.text_metrics import (
    compare_cer,
    normalize_for_content_cer,
    relative_cer_reduction,
)


def test_content_cer_ignores_punctuation_and_spacing():
    reference = "ペリー氏はテキサスに戻って今夜の結果を見極めました"
    hypothesis = "ペリー氏はテキサスに戻って、今夜の結果を見極めました。"

    metrics = compare_cer(reference, hypothesis)

    assert metrics["strict"]["cer"] > 0
    assert metrics["content"]["cer"] == 0


def test_content_cer_keeps_lexical_substitutions():
    reference = "ペリー氏はテキサスに戻りました"
    hypothesis = "ケリー氏はテキサスに戻りました。"

    metrics = compare_cer(reference, hypothesis)

    assert normalize_for_content_cer(hypothesis) == "ケリー氏はテキサスに戻りました"
    assert metrics["content"]["distance"] == 1
    assert metrics["content"]["cer"] > 0


def test_relative_cer_reduction():
    assert relative_cer_reduction(0.2, 0.1) == 0.5
    assert relative_cer_reduction(0.0, 0.0) is None
