"""
Whisper モデル事前ダウンロードスクリプト

エアギャップ環境への持ち込み前に、インターネット接続環境でこのスクリプトを実行してください。
ダウンロードしたモデルは Docker ボリューム (models) に保存されます。

使い方:
  # モデルをダウンロードしてボリュームに保存（インターネット接続が必要）
  docker compose run --rm -v mojiokoshi_models:/app/models worker python scripts/download_models.py

  # ボリュームを tar に書き出す（オフライン持ち込み用）
  docker run --rm -v mojiokoshi_models:/data -v $(pwd):/out alpine \
    tar czf /out/whisper-models.tar.gz -C /data .

  # オンプレミスサーバーでボリュームに展開
  docker volume create mojiokoshi_models
  docker run --rm -v mojiokoshi_models:/data -v $(pwd):/out alpine \
    tar xzf /out/whisper-models.tar.gz -C /data
"""
import os
import sys

MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "large")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")


def main():
    print(f"Whisper モデルをダウンロードします: {MODEL_SIZE} (device={DEVICE})")
    print(f"保存先: {os.environ.get('HF_HOME', '~/.cache/huggingface')}")
    print()

    try:
        from faster_whisper import WhisperModel
        compute_type = "float16" if DEVICE == "cuda" else "int8"
        print("ダウンロード中... (モデルサイズによっては数分かかります)")
        model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=compute_type)
        print(f"\n完了: {MODEL_SIZE} モデルのダウンロードが完了しました。")
        # Quick smoke test
        import tempfile, struct
        silence = b'\x00' * (16000 * 2)  # 1 second of silence
        wav_header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + len(silence), b'WAVE',
            b'fmt ', 16, 1, 1, 16000, 32000, 2, 16,
            b'data', len(silence)
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_header + silence)
            tmp = f.name
        list(model.transcribe(tmp, language="ja")[0])
        os.unlink(tmp)
        print("動作確認: OK")
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
