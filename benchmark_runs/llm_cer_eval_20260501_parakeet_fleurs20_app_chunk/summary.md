# LLM post-correction CER evaluation

- model: `qwen3.5-35b-awq-a5000-14`
- run_llm: `True`
- prompt_profile: `app_chunk`
- items: `40`

| group | items | strict raw | strict corrected | strict rel. reduction | content raw | content corrected | content rel. reduction | improved | worse |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| babble10_reverb | 20 | 22.11% | 26.53% | -20.00% | 19.01% | 19.71% | -3.64% | 0 | 2 |
| clean | 20 | 10.20% | 13.86% | -35.83% | 7.52% | 7.52% | 0.00% | 0 | 0 |

Notes:
- `strict` は句読点・空白も含むCERです。
- `content` はUnicode正規化後、空白と句読点を除いたCERです。
- `content` のほうが、LLMが読みやすさのために句読点を追加した影響を受けにくいです。
