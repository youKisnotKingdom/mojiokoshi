# Seminar Sample Noise Check

条件:
- noise: `speech babble + reverb`
- babble: 4 本の別話者音声
- babble SNR: `10dB`
- RIR: OpenRIR `SLR26` simulated `mediumroom/Room116-00032.wav`

対象サンプル:
- `2026-04-16 00:45-01:15`
- `2026-04-03 70:20-70:50`

## 2026-04-16 sample

音声:
- clean: [2026-04-16_seminar_sample_00m45s_30s.wav](/home/ykadono/dev/mojiokoshi/benchmark_runs/seminar_samples/2026-04-16_seminar_sample_00m45s_30s.wav)
- noisy: [2026-04-16_seminar_sample_00m45s_30s_babble10_reverb.wav](/home/ykadono/dev/mojiokoshi/benchmark_runs/seminar_samples/2026-04-16_seminar_sample_00m45s_30s_babble10_reverb.wav)

### Parakeet
- clean:
  - `結構、たたかせてもらってるで、あれ。クロード以外にも使えますもんね、あれそうね、いや、今、そう、クロードコードでやってて、なんか、木村先生もなんか、結局、ソーシャルデータサイエンス研究所の中でやっぱり作りたいって、レコード聴くのも含めてっていう話で、なんかあれやね、角野さんがやってくれたんかもしれんけど。`
- noisy:
  - `都市はモロッコのスルタンによって再建されています。`

### Cohere
- clean:
  - `結構たたかしてもらってるで俺クロード以外にも使えますもんねあれそうねいや今うそクロードコードでやっててなんかあのキム木村先生もなんか結局ソーシャルデータサイエンス研究所の中でやっぱり作りたいでコード弾くのを含めてっていう話でなんかあれやね角野さんがやってくれたのかもしれんけど`
- noisy:
  - `結構、戦してもらってるよね。`

## 2026-04-03 sample

音声:
- clean: [2026-04-03_seminar_sample_70m20s_30s.wav](/home/ykadono/dev/mojiokoshi/benchmark_runs/seminar_samples/2026-04-03_seminar_sample_70m20s_30s.wav)
- noisy: [2026-04-03_seminar_sample_70m20s_30s_babble10_reverb.wav](/home/ykadono/dev/mojiokoshi/benchmark_runs/seminar_samples/2026-04-03_seminar_sample_70m20s_30s_babble10_reverb.wav)

### Parakeet
- clean:
  - `やらなきゃいけないでこれにちょっとここに近いんですけどあとはその純粋にお金の話で研究するためのっていうところで一つはさっき言ってた黒潤の競争の場なんですけどこれはまた桜井さんにしゃべってもらったら競争の場全体それでいいんじゃないかなと思うんだけどちょっと待って下さい。`
- noisy:
  - `やらなきゃいけないこれにちょっとここに近いんですけどあとは要するにお金の話で研究するためのっていうところで一つはさっき言ってた黒需要の競争の場なんですけどこれはまたサボライさんにしゃべってもらったら都市はモロッコのスルタンによってダルルバリアとして再建されました。`

### Cohere
- clean:
  - `あのでこれにちょっとまあここに近いんですけどあとはその純粋にお金の話で研究するためのっていうところであのまあ一つはさっき言ってた黒人の競争の場なんですけどこれはまた櫻井さんにしゃべってもらったら競争の場全体それでいいんじゃないかなと思うんだけどちょっと待ってください`
- noisy:
  - `で、これにちょっと、まあ、ここに近いんですけど、あとは、お金の話で、きっと、協力するためによって、カサブランカと名付けられました。一つはさっき言ってた黒人の競争の場なんですけど、これはまた櫻井さんにしゃべってもらったら、競争の場全体。`

## 所見

- seminar の実サンプルでは、`speech babble + reverb` はかなり強く効いた。
- 単純な white noise より、`他人の声` が混ざる方が破壊的だった。
- しかも transcript が単に崩れるだけでなく、babble source 側の内容が混入している。
- この条件はかなり厳しめで、実運用でここまで重なることは少ないが、`被り発話` と `残響` が危険という方向性は確認できた。
- seminar / 会議用途では、ノイズ耐性を見るなら white noise ではなく `babble + reverb` を優先した方がよい。
