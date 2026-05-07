# LLM post-correction CER evaluation

- model: `google/gemma-4-E4B-it`
- run_llm: `True`
- prompt_profile: `app_chunk`
- chunk_chars: `0`
- retries: `2`
- items: `1`

| group | items | strict raw | strict corrected | strict rel. reduction | content raw | content corrected | content rel. reduction | improved | worse |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clean | 1 | 3.64% | 10.00% | -175.00% | 2.73% | 2.73% | 0.00% | 0 | 0 |

Notes:
- `strict` は句読点・空白も含むCERです。
- `content` はUnicode正規化後、空白と句読点を除いたCERです。
- `content` のほうが、LLMが読みやすさのために句読点を追加した影響を受けにくいです。
