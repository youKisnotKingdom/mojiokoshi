# Gemma 4 Post-Correction PoC

更新日: 2026-04-21

## 位置づけ

Gemma 4 は、このプロジェクトでは **ASR 本体の第一候補** としてではなく、
**後段の文脈補正器** として扱うのが自然です。

理由:

- 現在の主目的は「長尺日本語音声を安定して速く文字起こしすること」であり、ここでは専用 ASR の `parakeet_ja` や `cohere_transcribe` の方が筋が良い
- Gemma 4 E2B/E4B は音声入力対応だが、マルチモーダル LLM であり、ASR 専用モデルと比較すると評価軸が増えやすい
- Gemma 4 は「5 秒程度の仮文字起こしを、15 秒程度の文脈で補正する」用途に向く

## どう使うか

推奨パイプライン:

1. Stage 1 で ASR 本体が文字起こしする
2. Stage 2 で Gemma 4 が短い文脈窓を補正する
3. 最終的に補正済みテキストを保存する

想定する Stage 1 候補:

- `parakeet_ja`: 精度本命
- `cohere_transcribe`: 実データで見た目が良い可能性あり
- `reazon_zipformer`: partial 用の軽量候補

想定する Stage 2 候補:

- `google/gemma-4-E2B-it`

## Gemma 4 を補正器として使う理由

補正器として効きやすいケース:

- 固有名詞の取り違え
- 専門用語の漢字変換ミス
- チャンク境界で途切れた文
- 数字・単位・略語の整形

補正器として弱いケース:

- 元の ASR が大きく聞き漏らしている
- 話者切り替わりを正しく扱えない
- 長尺 1 本をそのまま 1 セッションで処理する

## 推奨 PoC 範囲

まずは以下に限定するのが良いです。

- 入力は **テキストのみ**
  - 音声を再度 Gemma 4 に食わせず、ASR 結果テキストだけを補正する
- 窓長は **15 秒**
- 更新間隔は **10 秒**
- 前後文脈を少し持たせる
- 補正対象は seminar 音声や研究室会議音声

この方が、

- 実装が軽い
- 失敗時の切り戻しが簡単
- GPU 使用量が読みやすい
- ASR 本体と責務が分かれる

## なぜ音声入力 Gemma 4 を主役にしないか

Gemma 4 E2B/E4B は音声入力に対応しますが、このプロジェクトでは以下の理由で主役にしません。

- 専用 ASR より比較軸が増える
- ストリーミング・長尺・補正の境界が曖昧になる
- 本番運用で「ASR が遅い」のか「LLM が遅い」のか切り分けにくい

そのため、まずは **ASR 本体と補正器を分離** します。

## 実装イメージ

### batch

1. ASR 本体が `result_segments` を出す
2. その segments を 15 秒窓にまとめる
3. 各窓を Gemma 4 に投げて補正する
4. 窓をつなぎ直して最終テキストを作る

### pseudo realtime

1. 2 秒または 5 秒ごとに仮文字起こしを表示
2. 10 秒ごとに 15 秒文脈で Gemma 4 補正をかける
3. UI 上で上書き確定する

## 推奨プロンプト方針

Gemma 4 には次を明示するのがよいです。

- 出力は補正済み本文のみ
- 話者を勝手に増やさない
- 不明な語は無理に作らない
- 研究室固有名詞・人名・略語を優先的に保つ
- 数字は文脈に合う形に整える

例:

```text
以下は日本語の会議文字起こし結果です。誤変換や文の切れ目を、前後文脈に基づいて最小限だけ修正してください。

制約:
- 出力は修正後の本文のみ
- 意味が不明な部分を創作しない
- 話者ラベルを追加しない
- 固有名詞、研究室名、製品名、略語はできるだけ保つ
- 数字、時刻、単位は自然な表記へ整える
```

## 事前に用意しておくと良いもの

- 研究室名
- 教員名・学生名
- 研究テーマ名
- 論文名
- 装置名
- 研究室でよく出る略語

これは将来 `Parakeet` の word boosting にも、そのまま流用できます。

## 期待できる効果

- `Parakeet` の高精度をベースに、固有名詞や文脈整形をさらに改善できる可能性がある
- `Cohere` で印象が良かった「読みやすさ」を、別モデルの後段補正で再現できる可能性がある

## 期待しすぎない方がよい点

- 補正器は、ASR 本体の完全な代替ではない
- 補正器が hallucination を起こすと、むしろ悪化する
- 固有名詞を完全に直したいなら、Gemma 4 単独より `Parakeet + word boosting` の方が本筋

## 優先順位

実装順は以下を推奨します。

1. `Parakeet` を batch 本番候補として組み込む
2. 研究室固有名詞リストを作る
3. `Parakeet` の word boosting を試す
4. その後に Gemma 4 を **補正器** として PoC する

## 参考

- Gemma 4 E2B / audio 対応モデルカード
  - https://huggingface.co/google/gemma-4-E2B-it
- Gemma 4 音声リアルタイム検証記事
  - https://zenn.dev/kozoka_ai/articles/3c17156f9f660e
- NeMo Word Boosting
  - https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/asr_customization/word_boosting.html
- Parakeet TDT-CTC 0.6B ja
  - https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja
- Cohere discussion: guidance words 未対応
  - https://huggingface.co/CohereLabs/cohere-transcribe-03-2026/discussions/32
