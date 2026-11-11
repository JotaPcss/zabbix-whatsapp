#!/usr/bin/env bash
# Tarefa agendada do Hermes (cron sem IA) que dispara os relatórios do Zabbix.
# Instalado pelo install.sh em $HERMES_HOME/scripts/ como zabbix-relatorio-{daily,weekly,monthly}.sh.
#
# Comportamento combinado com o cron do Hermes:
#   - sucesso: não imprime nada  -> o Hermes não manda mensagem (os relatórios já foram enviados);
#   - falha:   sai com código != 0 -> o Hermes avisa o erro no canal padrão (home channel) do WhatsApp.
set -uo pipefail

PERIOD="${1:-${ZBX_PERIOD:-}}"
if [[ -z "$PERIOD" ]]; then
    # O nome do arquivo define o período: zabbix-relatorio-weekly.sh -> weekly
    PERIOD="$(basename "$0" .sh)"; PERIOD="${PERIOD##*-}"
fi

APP=/opt/zabbix-whatsapp
LOG=/var/log/zabbix-whatsapp/relatorios.log

if ! out="$("$APP/venv/bin/python" "$APP/zabbix_whatsapp_report.py" -c "$APP/config.yaml" --period "$PERIOD" 2>&1)"; then
    echo "$out" >> "$LOG" 2>/dev/null || true
    echo "Falha no relatório $PERIOD do Zabbix:"
    echo "$out" | grep -E "ERROR|Erro|erro" | tail -n 10
    exit 1
fi
echo "$out" >> "$LOG" 2>/dev/null || true
