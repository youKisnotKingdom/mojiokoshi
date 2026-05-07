#!/usr/bin/env python3
"""Evaluate CER before and after LLM post-correction.

Inputs are existing ASR benchmark predictions.jsonl files, or explicit
reference/hypothesis pairs. The script writes per-case corrected text and a
JSON/Markdown summary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.config import get_settings  # noqa: E402
from app.services.summarization import (  # noqa: E402
    CHUNK_REFINEMENT_SYSTEM_PROMPT,
    CHUNK_REFINEMENT_USER_PROMPT_TEMPLATE,
    call_llm_api_with_metadata,
)
from app.services.text_metrics import compare_cer, relative_cer_reduction  # noqa: E402


CONSERVATIVE_SYSTEM_PROMPT = """あなたは日本語ASR文字起こしの後段補正を行うアシスタントです。
入力された文字起こしに含まれる事実だけを使い、誤字、助詞、句読点、文の切れ目を最小限だけ整えてください。

制約:
- 出力は補正後の本文のみ
- 要約しない
- 話者ラベルを追加しない
- 入力にない内容を補わない
- 音声なしでは断定できない固有名詞は変更しない
- 数字表記は入力の意味を保つ範囲で整える
"""

CONSERVATIVE_USER_PROMPT_TEMPLATE = """以下は日本語のASR文字起こしです。内容を変えずに、読みやすい文字起こしへ最小限だけ補正してください。

入力:
{text}
"""


class _PromptContext(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--predictions",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="benchmark predictions.jsonl。例: clean=benchmark_runs/.../predictions.jsonl",
    )
    parser.add_argument(
        "--pair",
        nargs=3,
        action="append",
        default=[],
        metavar=("NAME", "REFERENCE", "HYPOTHESIS"),
        help="単発の reference/hypothesis ファイルペア",
    )
    parser.add_argument(
        "--chunk-report",
        nargs=3,
        action="append",
        default=[],
        metavar=("NAME", "REFERENCE", "SUMMARY_JSON"),
        help="実ASRベンチ summary.json の chunks を、実運用チャンクとして評価します",
    )
    parser.add_argument("--limit", type=int, default=None, help="各 predictions から先頭N件だけ評価")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-llm", action="store_true", help="LLM補正を実行する")
    parser.add_argument("--force", action="store_true", help="既存の corrected/*.txt を再生成する")
    parser.add_argument("--model", default=None, help="LLMモデル名。未指定なら環境設定")
    parser.add_argument("--api-base", default=None, help="OpenAI互換API URL。未指定なら環境設定")
    parser.add_argument("--api-key", default=None, help="OpenAI互換API Key。未指定なら環境設定")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--retries", type=int, default=2, help="LLM API エラー時のリトライ回数")
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=0,
        help="長文をこの文字数前後で分割して補正します。--chunk-report では summary.json の実チャンクを優先します",
    )
    parser.add_argument(
        "--context-chars",
        type=int,
        default=1000,
        help="チャンク補正時に直前の補正済み文脈として渡す最大文字数",
    )
    parser.add_argument(
        "--prompt-profile",
        choices=("app_chunk", "conservative"),
        default="app_chunk",
        help="app_chunk はアプリ本体のチャンク精緻化プロンプトを使います",
    )
    return parser.parse_args()


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "case"


def _parse_labeled_path(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        path = Path(raw)
        return path.parent.name or path.stem, path
    label, path = raw.split("=", 1)
    label = label.strip()
    if not label:
        raise SystemExit(f"predictions label が空です: {raw}")
    return label, Path(path)


def load_prediction_cases(raw_predictions: list[str], limit: int | None) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for raw in raw_predictions:
        label, path = _parse_labeled_path(raw)
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                reference = str(row.get("reference_text", "")).strip()
                hypothesis = str(row.get("hypothesis_text", "")).strip()
                if not reference or not hypothesis:
                    raise ValueError(f"reference_text/hypothesis_text が空です: {path}")
                case_id = str(row.get("id") or f"{count + 1:04d}")
                cases.append(
                    {
                        "group": label,
                        "id": case_id,
                        "reference_text": reference,
                        "hypothesis_text": hypothesis,
                    }
                )
                count += 1
                if limit is not None and count >= limit:
                    break
    return cases


def load_pair_cases(raw_pairs: list[list[str]]) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for name, reference_path, hypothesis_path in raw_pairs:
        reference = Path(reference_path).read_text(encoding="utf-8").strip()
        hypothesis = Path(hypothesis_path).read_text(encoding="utf-8").strip()
        cases.append(
            {
                "group": "pairs",
                "id": name,
                "reference_text": reference,
                "hypothesis_text": hypothesis,
            }
        )
    return cases


def load_chunk_report_cases(raw_reports: list[list[str]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for name, reference_path, summary_path in raw_reports:
        reference = Path(reference_path).read_text(encoding="utf-8").strip()
        data = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        report = data[0] if isinstance(data, list) else data
        raw_chunks = report.get("chunks") or []
        chunks = [
            {
                "index": int(chunk.get("index", index)),
                "text": str(chunk.get("text", "")).strip(),
                "audio_duration_s": float(chunk.get("audio_duration_s", 0.0) or 0.0),
            }
            for index, chunk in enumerate(raw_chunks)
            if str(chunk.get("text", "")).strip()
        ]
        if not chunks:
            raise ValueError(f"chunks がありません: {summary_path}")
        cases.append(
            {
                "group": "chunk_reports",
                "id": name,
                "reference_text": reference,
                "hypothesis_text": "\n".join(chunk["text"] for chunk in chunks),
                "chunks": chunks,
                "chunk_source": str(summary_path),
                "total_audio_s": float(report.get("total_audio_s", 0.0) or 0.0),
                "model_alias": report.get("model_alias"),
            }
        )
    return cases


def split_text_for_correction(text: str, chunk_chars: int) -> list[str]:
    if chunk_chars <= 0 or len(text) <= chunk_chars:
        return [text.strip()]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + chunk_chars)
        if hard_end == len(text):
            end = hard_end
        else:
            search_from = max(start + int(chunk_chars * 0.6), start + 1)
            end = hard_end
            for index in range(hard_end, search_from, -1):
                if text[index - 1] in "。．.!?！？\n":
                    end = index
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


async def correct_text_once(
    case: dict[str, str],
    *,
    text: str,
    chunk_index: int,
    previous_context: str,
    model: str | None,
    api_base: str | None,
    api_key: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float | None,
    prompt_profile: str,
    retries: int,
) -> tuple[str, dict[str, Any]]:
    if prompt_profile == "app_chunk":
        system_prompt = CHUNK_REFINEMENT_SYSTEM_PROMPT
        prompt = CHUNK_REFINEMENT_USER_PROMPT_TEMPLATE.format_map(
            _PromptContext(
                {
                    "filename": case["id"],
                    "chunk_index": chunk_index,
                    "start_time": "unknown",
                    "end_time": "unknown",
                    "previous_context": previous_context or "なし",
                    "text": text,
                }
            )
        )
    else:
        system_prompt = CONSERVATIVE_SYSTEM_PROMPT
        prompt = CONSERVATIVE_USER_PROMPT_TEMPLATE.format(text=text)
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = await call_llm_api_with_metadata(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                api_base=api_base,
                api_key=api_key,
                timeout=timeout,
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                raise
            wait_seconds = min(2 ** attempt, 8)
            print(
                f"  retry chunk={chunk_index} attempt={attempt + 1}/{retries} "
                f"after {type(exc).__name__}: {exc}",
                flush=True,
            )
            await asyncio.sleep(wait_seconds)
    else:
        raise RuntimeError("LLM correction failed") from last_error
    elapsed = time.perf_counter() - started
    metadata = result.metadata or {}
    metadata["elapsed_s"] = elapsed
    return result.content.strip(), metadata


async def correct_text(
    case: dict[str, str],
    *,
    model: str | None,
    api_base: str | None,
    api_key: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float | None,
    prompt_profile: str,
    chunk_chars: int,
    context_chars: int,
    retries: int,
) -> tuple[str, dict[str, Any]]:
    if case.get("chunks"):
        chunks = [chunk["text"] for chunk in case["chunks"] if chunk.get("text")]
        chunk_source = "input_chunks"
    else:
        chunks = split_text_for_correction(case["hypothesis_text"].strip(), chunk_chars)
        chunk_source = "text_split" if chunk_chars > 0 else "single_text"
    corrected_parts: list[str] = []
    chunk_metadata: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index, chunk in enumerate(chunks):
        previous_context = "".join(corrected_parts)[-context_chars:] if context_chars > 0 else ""
        corrected, metadata = await correct_text_once(
            case,
            text=chunk,
            chunk_index=index,
            previous_context=previous_context,
            model=model,
            api_base=api_base,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            prompt_profile=prompt_profile,
            retries=retries,
        )
        corrected_parts.append(corrected)
        chunk_metadata.append(
            {
                "chunk_index": index,
                "input_chars": len(chunk),
                "output_chars": len(corrected),
                **metadata,
            }
        )

    return "\n".join(corrected_parts).strip(), {
        "elapsed_s": time.perf_counter() - started,
        "chunk_count": len(chunks),
        "chunk_source": chunk_source,
        "chunks": chunk_metadata,
    }


def _cer(metrics: dict[str, Any], kind: str) -> float | None:
    value = metrics[kind]["cer"]
    return float(value) if isinstance(value, (int, float)) else None


def _fmt_percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def _build_comparison(
    reference_text: str,
    hypothesis_text: str,
    corrected_text: str,
) -> dict[str, Any]:
    baseline = compare_cer(reference_text, hypothesis_text)
    corrected = compare_cer(reference_text, corrected_text)
    return {
        "baseline": baseline,
        "corrected": corrected,
        "strict_relative_cer_reduction": relative_cer_reduction(_cer(baseline, "strict"), _cer(corrected, "strict")),
        "content_relative_cer_reduction": relative_cer_reduction(_cer(baseline, "content"), _cer(corrected, "content")),
    }


def _summarize_group(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    reference_text = "\n".join(row["reference_text"] for row in rows)
    hypothesis_text = "\n".join(row["hypothesis_text"] for row in rows)
    corrected_text = "\n".join(row["corrected_text"] for row in rows)
    comparison = _build_comparison(reference_text, hypothesis_text, corrected_text)
    worse_content_cases = 0
    improved_content_cases = 0
    for row in rows:
        base = _cer(row["metrics"]["baseline"], "content")
        corrected = _cer(row["metrics"]["corrected"], "content")
        if base is None or corrected is None:
            continue
        if corrected > base:
            worse_content_cases += 1
        elif corrected < base:
            improved_content_cases += 1
    return {
        "group": label,
        "num_items": len(rows),
        "metrics": comparison,
        "improved_content_cases": improved_content_cases,
        "worse_content_cases": worse_content_cases,
    }


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# LLM post-correction CER evaluation",
        "",
        f"- model: `{summary['model_name']}`",
        f"- run_llm: `{summary['run_llm']}`",
        f"- prompt_profile: `{summary['prompt_profile']}`",
        f"- chunk_chars: `{summary['chunk_chars']}`",
        f"- retries: `{summary['retries']}`",
        f"- items: `{summary['num_items']}`",
        "",
        "| group | items | strict raw | strict corrected | strict rel. reduction | content raw | content corrected | content rel. reduction | improved | worse |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in summary["groups"]:
        metrics = group["metrics"]
        baseline = metrics["baseline"]
        corrected = metrics["corrected"]
        lines.append(
            "| {group} | {items} | {strict_base} | {strict_corr} | {strict_rel} | "
            "{content_base} | {content_corr} | {content_rel} | {improved} | {worse} |".format(
                group=group["group"],
                items=group["num_items"],
                strict_base=_fmt_percent(_cer(baseline, "strict")),
                strict_corr=_fmt_percent(_cer(corrected, "strict")),
                strict_rel=_fmt_percent(metrics["strict_relative_cer_reduction"]),
                content_base=_fmt_percent(_cer(baseline, "content")),
                content_corr=_fmt_percent(_cer(corrected, "content")),
                content_rel=_fmt_percent(metrics["content_relative_cer_reduction"]),
                improved=group["improved_content_cases"],
                worse=group["worse_content_cases"],
            )
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- `strict` は句読点・空白も含むCERです。",
            "- `content` はUnicode正規化後、空白と句読点を除いたCERです。",
            "- `content` のほうが、LLMが読みやすさのために句読点を追加した影響を受けにくいです。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run(args: argparse.Namespace) -> None:
    cases = (
        load_prediction_cases(args.predictions, args.limit)
        + load_pair_cases(args.pair)
        + load_chunk_report_cases(args.chunk_report)
    )
    if not cases:
        raise SystemExit("--predictions、--pair、--chunk-report のいずれかを指定してください")

    settings = get_settings()
    model_name = args.model or settings.llm_model_name
    api_base = args.api_base
    api_key = args.api_key
    timeout = args.timeout
    args.output_dir.mkdir(parents=True, exist_ok=True)
    corrected_dir = args.output_dir / "corrected"
    corrected_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        case_name = f"{case['group']}__{case['id']}"
        corrected_path = corrected_dir / f"{_safe_filename(case_name)}.txt"
        llm_metadata: dict[str, Any] = {}
        if args.run_llm:
            if corrected_path.exists() and not args.force:
                corrected_text = corrected_path.read_text(encoding="utf-8").strip()
                llm_metadata["reused"] = True
            else:
                print(f"[{index}/{len(cases)}] correcting {case_name}")
                corrected_text, llm_metadata = await correct_text(
                    case,
                    model=model_name,
                    api_base=api_base,
                    api_key=api_key,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    timeout=timeout,
                    prompt_profile=args.prompt_profile,
                    chunk_chars=args.chunk_chars,
                    context_chars=args.context_chars,
                    retries=args.retries,
                )
                corrected_path.write_text(corrected_text.rstrip() + "\n", encoding="utf-8")
        else:
            corrected_text = case["hypothesis_text"]
            llm_metadata["skipped"] = True

        metrics = _build_comparison(case["reference_text"], case["hypothesis_text"], corrected_text)
        row = {
            **case,
            "corrected_text": corrected_text,
            "corrected_path": str(corrected_path),
            "llm_metadata": llm_metadata,
            "metrics": metrics,
        }
        rows.append(row)

    groups = [
        _summarize_group(group, [row for row in rows if row["group"] == group])
        for group in sorted({row["group"] for row in rows})
    ]
    summary = {
        "model_name": model_name,
        "run_llm": args.run_llm,
        "prompt_profile": args.prompt_profile,
        "chunk_chars": args.chunk_chars,
        "context_chars": args.context_chars,
        "retries": args.retries,
        "num_items": len(rows),
        "groups": groups,
    }

    with (args.output_dir / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_markdown(args.output_dir / "summary.md", summary)
    print(f"wrote {args.output_dir / 'summary.md'}")


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
