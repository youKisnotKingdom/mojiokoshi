# LLM post-correction CER evaluation

- model: `qwen3.5-35b-awq-a5000-14`
- run_llm: `True`
- prompt_profile: `app_chunk`
- chunk_chars: `0`
- retries: `1`
- items: `10`

| group | items | strict raw | strict corrected | strict rel. reduction | content raw | content corrected | content rel. reduction | improved | worse |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clean | 10 | 5.09% | 9.68% | -90.00% | 2.24% | 2.24% | 0.00% | 0 | 0 |

Notes:
- `strict` は句読点・空白も含むCERです。
- `content` はUnicode正規化後、空白と句読点を除いたCERです。
- `content` のほうが、LLMが読みやすさのために句読点を追加した影響を受けにくいです。
