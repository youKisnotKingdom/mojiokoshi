# 文字起こし精緻化 LLM 評価レポート

更新日: 2026-05-01

## 結論

現時点では、文字起こし精緻化の第一候補は **テキスト入力のみの小型 LLM** です。
音声を直接聞けるモデルは PoC 対象として残しますが、本番導入は後回しにします。

理由:

- 現行パイプラインは `Parakeet JA` で ASR を行い、チャンク単位のテキストを LLM で整える構成になっている
- テキスト精緻化は ASR と LLM の責務が分かれ、失敗時の切り戻しが容易
- CPU 小型 LLM は精度上限こそ低いが、GPU ASR と切り離して常時稼働させやすい
- 音声入力 LLM は、聞き漏らし補完の可能性がある一方で、長尺処理、話者境界、推論速度、評価軸が増える

## 実装方針

LLM 設定は用途ごとに分けます。

| 用途 | 設定 |
| --- | --- |
| 要約・議事録・通常 LLM 処理 | `LLM_API_BASE_URL`, `LLM_MODEL_NAME`, `LLM_API_KEY` |
| チャンク単位の文字起こし精緻化 | `CHUNK_REFINEMENT_LLM_API_BASE_URL`, `CHUNK_REFINEMENT_LLM_MODEL_NAME`, `CHUNK_REFINEMENT_LLM_API_KEY` |

`CHUNK_REFINEMENT_LLM_API_BASE_URL` と `CHUNK_REFINEMENT_LLM_MODEL_NAME` が空欄の場合は、従来通り `LLM_*` にフォールバックします。
`CHUNK_REFINEMENT_LLM_API_KEY` は、専用 API URL を設定している場合は空欄のままなら認証なし、専用 API URL が空欄の場合は `LLM_API_KEY` にフォールバックします。
これにより、まずは既存構成を壊さず、後から CPU 推論の小型モデルだけを精緻化に割り当てられます。

## 候補 A: テキスト入力の CPU 小型 LLM

### 想定構成

- ASR: `Parakeet JA`
- 精緻化: OpenAI 互換 API 経由の CPU 小型 LLM
- API サーバー候補:
  - Ollama
  - llama.cpp `llama-server`
  - LocalAI

Ollama は OpenAI API 互換の `/v1/chat/completions` を提供します。
llama.cpp の `llama-server` も OpenAI 互換の HTTP API を提供します。
このアプリの精緻化処理は `/chat/completions` に投げるだけなので、どちらにも差し替えやすいです。

### 推奨初期値

| 項目 | 値 |
| --- | --- |
| `CHUNK_REFINEMENT_LLM_MODEL_NAME` | 7B から 14B 級の instruct モデル |
| `WORKER_CHUNK_REFINEMENT_CONCURRENCY` | `1` |
| `LLM_CHUNK_REFINEMENT_MAX_INPUT_CHARS` | `6000` から `12000` |
| `LLM_CHUNK_REFINEMENT_MAX_OUTPUT_TOKENS` | `1000` から `2000` |
| `CHUNK_REFINEMENT_LLM_TEMPERATURE` | `0.0` から `0.1` |

### 期待できる改善

- 誤字・助詞・句読点・文の切れ目の改善
- 研究室固有名詞や専門用語の表記統一
- チャンク境界で切れた文の整形

### 主なリスク

- ASR に存在しない内容を補う hallucination
- 口語表現を過剰に書き換える
- 小型モデルでは長い文脈の整合性が落ちる

## 候補 B: 音声入力対応モデルによる精緻化

### 位置づけ

音声入力対応モデルは、ASR 結果テキストだけでなく、元音声も入力に含めて補正する候補です。
代表例として、Qwen2-Audio、Qwen2.5-Omni、GPT-4o 系 audio/transcribe モデルがあります。

Qwen2-Audio は音声信号を入力し、音声分析やテキスト応答を行う audio-language model とされています。
Qwen2.5-Omni は text/image/audio/video を扱うエンドツーエンドの multimodal model です。
OpenAI の `gpt-4o-transcribe` は GPT-4o 系の speech-to-text モデルとして提供されています。
これは既存 ASR 後のテキスト整形というより、音声を再度文字起こしして比較する候補として扱います。

### 期待できる改善

- ASR が聞き漏らした語の補完
- 雑音や話速の影響で崩れた箇所の再確認
- 音声イベント、間、話者のニュアンスを見た補助判断

### 主なリスク

- 長尺音声をそのまま扱うと遅い
- ASR と音声 LLM のどちらが原因で悪化したか切り分けにくい
- テキスト精緻化より運用コストが高い
- OpenAI 互換 `/chat/completions` だけでは、音声ファイル入力の実装差が大きい

### PoC 条件

音声入力モデルを試す場合は、いきなり本番経路に入れず、次の条件で比較します。

- 対象は 30 秒から 2 分の切り出し音声
- 入力は「音声 + ASR 仮テキスト + 修正指示」
- 出力は修正済みテキストのみ
- テキスト専用 LLM の精緻化結果と横並びで比較
- 悪化した場合はチャンク単位で無効化できること

## 評価設計

FLEURS 日本語 20 件を使った初回の実測結果は別レポートにまとめています。
現行の 1-best テキストのみのゼロショット補正では、CER 改善は確認できませんでした。

- 実測レポート: `docs/LLM_CER_EVALUATION_20260501.md`

### データセット

1. 研究室・会議音声
2. セミナー音声
3. 雑音あり音声
4. 話者切り替わりが多い音声
5. 固有名詞が多い音声

### 比較対象

| ID | 構成 |
| --- | --- |
| baseline | `Parakeet JA` の生出力 |
| text-small | `Parakeet JA` + CPU 小型テキスト LLM |
| text-large | `Parakeet JA` + 既存 GPU LLM |
| audio-llm | 音声入力 LLM + ASR 仮テキスト |

### 指標

| 指標 | 見る内容 |
| --- | --- |
| CER/WER | 原文に対する文字・単語誤り率 |
| 固有名詞一致率 | 人名、研究テーマ、製品名、略語 |
| hallucination 件数 | 音声にも ASR にもない内容の追加 |
| 読みやすさ | 句読点、文分割、冗長語の処理 |
| 処理時間 | 音声 1 分あたりの補正時間 |
| コスト | GPU/CPU 使用量、常駐メモリ、外部API費用 |

## 推奨判定

### 本番短期

`text-small` を優先します。
CPU 小型 LLM を `CHUNK_REFINEMENT_LLM_*` に割り当て、要約・議事録生成は既存の大きい LLM を使います。

### 検証中期

`audio-llm` は、ASR の聞き漏らしが多いサンプルだけで PoC します。
全件処理ではなく、失敗が目立つチャンクの再確認用途に限定するのが安全です。

### 採用条件

音声入力モデルを本番採用する条件は次の通りです。

- テキスト精緻化より hallucination が増えない
- 固有名詞一致率が明確に改善する
- 1 分音声あたりの処理時間が運用許容内
- 失敗時に ASR 生出力へ戻せる

## 参考

- Ollama OpenAI compatibility: https://docs.ollama.com/api/openai-compatibility
- llama.cpp server: https://www.mintlify.com/ggml-org/llama.cpp/inference/server
- Hugging Face Transformers Qwen2-Audio: https://huggingface.co/docs/transformers/model_doc/qwen2_audio
- Qwen2.5-Omni-7B model card: https://huggingface.co/Qwen/Qwen2.5-Omni-7B
- OpenAI GPT-4o Transcribe model docs: https://developers.openai.com/api/docs/models/gpt-4o-transcribe
- OpenAI next-generation audio models: https://openai.com/index/introducing-our-next-generation-audio-models/
