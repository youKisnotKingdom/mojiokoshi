# LLM post-correction CER evaluation: UTokyo long lectures

- model: `qwen3.5-35b-awq-a5000-14`
- prompt_profile: `app_chunk`
- chunk_chars: `5000`
- context_chars: `1000`
- status: partial; LLM API became unavailable on the third item

| id | raw strict | raw content | corrected strict | corrected content |
| --- | ---: | ---: | ---: | ---: |
| BmtnWaUvX_0 | 22.55% | 20.56% | 26.68% | 20.62% |
| Uw6rKydVzX4 | 22.35% | 20.60% | 26.22% | 20.91% |
| WSiPUcXNzHU | 28.35% | 25.72% | - | - |
| e73XbWLt5w0 | 24.14% | 22.45% | - | - |
| jkUMzOFAVV4 | 16.06% | 13.41% | - | - |
| ztkteH9oQJ4 | 17.07% | 14.69% | - | - |

Notes:
- `strict` includes punctuation and whitespace.
- `content` removes whitespace and punctuation after Unicode normalization.
- The completed long items did not show CER improvement after LLM correction.
