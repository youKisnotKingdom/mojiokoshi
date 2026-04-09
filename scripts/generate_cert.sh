#!/bin/bash
# 自己署名SSL証明書を生成するスクリプト
# 使い方: bash scripts/generate_cert.sh [サーバーのIPまたはドメイン]
#
# 例:
#   bash scripts/generate_cert.sh 192.168.1.100
#   bash scripts/generate_cert.sh mojiokoshi.local

set -e

SERVER_IP="${1:-$(hostname -I | awk '{print $1}')}"
CERT_DIR="nginx/certs"
DAYS=3650  # 10年

echo "証明書を生成します"
echo "  対象: ${SERVER_IP}"
echo "  保存先: ${CERT_DIR}/"
echo ""

mkdir -p "$CERT_DIR"

# SAN（Subject Alternative Name）付きで証明書を生成
# IPアドレスとローカルホスト名の両方を含める
cat > /tmp/mojiokoshi_cert.conf <<EOF
[req]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
x509_extensions    = v3_req

[dn]
C  = JP
ST = Local
L  = Local
O  = Mojiokoshi
CN = ${SERVER_IP}

[v3_req]
subjectAltName = @alt_names

[alt_names]
IP.1  = ${SERVER_IP}
IP.2  = 127.0.0.1
DNS.1 = localhost
EOF

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "${CERT_DIR}/server.key" \
  -out    "${CERT_DIR}/server.crt" \
  -days   ${DAYS} \
  -config /tmp/mojiokoshi_cert.conf

rm -f /tmp/mojiokoshi_cert.conf

echo ""
echo "完了: ${CERT_DIR}/server.crt, server.key"
echo ""
echo "次のステップ:"
echo "  docker compose -f docker-compose.yml -f docker-compose.https.yml up -d"
echo ""
echo "ブラウザからのアクセス:"
echo "  https://${SERVER_IP}"
echo ""
echo "※ 初回アクセス時にブラウザの警告が表示されます。"
echo "  「詳細設定」→「${SERVER_IP} にアクセスする（安全ではありません）」をクリックしてください。"
