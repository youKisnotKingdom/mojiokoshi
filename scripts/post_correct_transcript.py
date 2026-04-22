#!/usr/bin/env python3
"""Post-correct ASR transcript with an OpenAI-compatible LLM."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.services.summarization import call_llm_api


SYSTEM_PROMPT = """あなたは日本語の会議・講義文字起こしを後段補正するアシスタントです。
ASR の出力に対して、誤変換・固有名詞・英字語・文のつながりを最小限だけ修正してください。

制約:
- 出力は修正後の本文のみ
- 要約しない
- 話者ラベルを追加しない
- 聞こえていない内容を創作しない
- glossary にある語は、文脈的に不自然でない限りその表記を優先する
- glossary に置換ルールがある場合は、そのルールを優先して適用する
- 人名や固有名詞は、音が近い誤変換でも glossary の表記に寄せる
- 口語的な文体は必要以上に書き換えない
"""


USER_PROMPT_TEMPLATE = """以下は日本語の文字起こし結果です。後段補正を行ってください。

glossary:
{glossary}

置換ルール:
{replacements}

入力テキスト:
{text}
"""


def load_glossary(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def format_glossary(terms: list[str]) -> str:
    raw_terms = [term for term in terms if "=>" not in term]
    mapped_terms = [term.split("=>", 1)[1].strip() for term in terms if "=>" in term]
    all_terms = raw_terms + mapped_terms
    if not all_terms:
        return "- (なし)"
    return "\n".join(f"- {term}" for term in all_terms)


def format_replacements(terms: list[str]) -> str:
    pairs = []
    for term in terms:
        if "=>" not in term:
            continue
        source, target = term.split("=>", 1)
        source = source.strip()
        target = target.strip()
        if source and target:
            pairs.append((source, target))
    if not pairs:
        return "- (なし)"
    return "\n".join(f"- {source} -> {target}" for source, target in pairs)


async def post_correct(text: str, glossary_terms: list[str], model: str | None = None) -> str:
    prompt = USER_PROMPT_TEMPLATE.format(
        glossary=format_glossary(glossary_terms),
        replacements=format_replacements(glossary_terms),
        text=text.strip(),
    )
    return await call_llm_api(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        model=model,
        temperature=0.0,
        max_tokens=4000,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="補正対象の transcript.txt")
    parser.add_argument("--glossary", type=Path, default=None, help="1 行 1 語の glossary ファイル")
    parser.add_argument("--output", type=Path, required=True, help="補正後の出力先")
    parser.add_argument("--model", default=None, help="明示的に使う LLM モデル名")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    text = args.input.read_text(encoding="utf-8")
    glossary_terms = load_glossary(args.glossary)
    corrected = asyncio.run(post_correct(text, glossary_terms, model=args.model))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(corrected.rstrip() + "\n", encoding="utf-8")
    print(f"wrote corrected transcript to {args.output}")


if __name__ == "__main__":
    main()
