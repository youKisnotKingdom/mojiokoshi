# LLM post-correction CER evaluation

- model: `qwen3.5-35b-awq-a5000-14`
- run_llm: `False`
- prompt_profile: `app_chunk`
- chunk_chars: `0`
- retries: `2`
- items: `1`

| group | items | strict raw | strict corrected | strict rel. reduction | content raw | content corrected | content rel. reduction | improved | worse |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| chunk_reports | 1 | 22.55% | 22.55% | 0.00% | 20.56% | 20.56% | 0.00% | 0 | 0 |

Notes:
- `strict` は句読点・空白も含むCERです。
- `content` はUnicode正規化後、空白と句読点を除いたCERです。
- `content` のほうが、LLMが読みやすさのために句読点を追加した影響を受けにくいです。
