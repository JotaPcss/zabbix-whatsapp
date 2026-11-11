#!/usr/bin/env bash
# Envia uma mensagem de teste assinada para a rota de webhook do Hermes, igual ao Zabbix faz.
# Uso: ./testar-webhook.sh <segredo-da-rota> <destino> [url-base] [rota]
#   destino: 5511999998888  (número)  ou  120363025555555555@g.us  (grupo)
# Exemplo:
#   ./testar-webhook.sh "$SEGREDO" 5511999998888 http://127.0.0.1:8644 zabbix-alert
set -euo pipefail

SECRET="${1:?informe o segredo da rota}"
DEST="${2:?informe o número ou o JID do grupo}"
BASE="${3:-http://127.0.0.1:8644}"
ROUTE="${4:-zabbix-alert}"

if [[ "$DEST" != *@* ]]; then
    DEST="$(echo "$DEST" | tr -cd '0-9')@s.whatsapp.net"
fi

TS="$(date +%s)"
BODY="$(printf '{"chat_id":"%s","text":"%s","event_id":"teste"}' "$DEST" \
    "✅ *Teste* | Zabbix → Hermes → WhatsApp funcionando ($(date '+%d/%m/%Y %H:%M:%S'))")"
SIG="$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')"

echo "POST $BASE/webhooks/$ROUTE  (destino $DEST)"
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$BASE/webhooks/$ROUTE" \
    -H "Content-Type: application/json" \
    -H "X-Webhook-Timestamp: $TS" \
    -H "X-Webhook-Signature-V2: $SIG" \
    -H "X-Request-ID: teste-$TS" \
    -d "$BODY"
