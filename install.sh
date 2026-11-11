#!/usr/bin/env bash
# Instala a integração Zabbix -> WhatsApp (Hermes Agent) no servidor onde o Hermes já roda.
#
# Uso (como root, na raiz do projeto):
#   sudo ./install.sh                      # usa o usuário que chamou o sudo como dono do Hermes
#   sudo HERMES_USER=hermes ./install.sh   # ou informe o usuário que roda o Hermes
#
# Instala:
#   /opt/zabbix-whatsapp/            gerador de relatórios, ferramenta do agente (zbx_tool.py), venv
#   ~HERMES_USER/.hermes/skills/devops/zabbix/       skill que ensina o agente a consultar o Zabbix
#   ~HERMES_USER/.hermes/scripts/zabbix-relatorio-*.sh  tarefas para o agendador do Hermes
#   /usr/local/bin/zbxrep            atalho para rodar o gerador
#
# Pode ser executado de novo para atualizar: config.yaml existente é preservado.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/zabbix-whatsapp
DATA=/var/lib/zabbix-whatsapp
LOGDIR=/var/log/zabbix-whatsapp

if [[ $EUID -ne 0 ]]; then
    echo "Execute como root: sudo $0" >&2
    exit 1
fi

HERMES_USER="${HERMES_USER:-${SUDO_USER:-}}"
if [[ -z "$HERMES_USER" ]] || ! id "$HERMES_USER" >/dev/null 2>&1; then
    echo "Informe o usuário que roda o Hermes: sudo HERMES_USER=<usuario> $0" >&2
    exit 1
fi
HERMES_GROUP="$(id -gn "$HERMES_USER")"
USER_HOME="$(getent passwd "$HERMES_USER" | cut -d: -f6)"
HH="${HERMES_HOME:-$USER_HOME/.hermes}"
[[ "$HERMES_USER" == "root" ]] && echo "AVISO: o Hermes vai rodar como root. Prefira um usuário comum dedicado."

if [[ ! -d "$HH" ]]; then
    echo "Não encontrei $HH. Instale e configure o Hermes para $HERMES_USER primeiro (TUTORIAL, etapa 2)." >&2
    exit 1
fi

HERMES_BIN="$(sudo -u "$HERMES_USER" -i bash -lc 'command -v hermes' 2>/dev/null || true)"
if [[ -z "$HERMES_BIN" ]]; then
    echo "AVISO: comando 'hermes' não encontrado no PATH de $HERMES_USER; ajuste hermes.command no config.yaml."
    HERMES_BIN=hermes
fi

PYTHON=${PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null; then
    echo "python3 não encontrado. Instale: apt install python3 python3-venv  |  dnf install python3" >&2
    exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Python 3.9+ necessário (encontrado: $("$PYTHON" -V))." >&2
    exit 1
fi
if ! "$PYTHON" -c 'import ensurepip' 2>/dev/null; then
    echo "Módulo venv ausente. Debian/Ubuntu: apt install python3-venv" >&2
    exit 1
fi

echo "==> Usuário do Hermes: $HERMES_USER ($HH) | hermes: $HERMES_BIN"

echo "==> Diretórios"
install -d -m 755 "$DEST"
install -d -m 750 -o "$HERMES_USER" -g "$HERMES_GROUP" "$DATA" "$DATA/relatorios" "$LOGDIR"

echo "==> Programas em $DEST"
install -m 755 "$SRC/report/zabbix_whatsapp_report.py" "$SRC/report/zbx_tool.py" \
    "$SRC/hermes/scripts/testar-webhook.sh" "$DEST/"
install -m 644 "$SRC/report/requirements.txt" "$SRC/report/config.example.yaml" "$DEST/"

if [[ ! -f "$DEST/config.yaml" ]]; then
    sed -e "s#^output_dir:.*#output_dir: $DATA/relatorios#" \
        -e "s#^  command: hermes .*#  command: $HERMES_BIN#" \
        "$SRC/report/config.example.yaml" > "$DEST/config.yaml"
    echo "    config.yaml criado a partir do exemplo: EDITE antes de usar."
else
    echo "    config.yaml existente preservado."
fi
chown root:"$HERMES_GROUP" "$DEST/config.yaml"
chmod 640 "$DEST/config.yaml"

echo "==> Ambiente Python (venv)"
"$PYTHON" -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --quiet --upgrade pip
"$DEST/venv/bin/pip" install --quiet -r "$DEST/requirements.txt"

echo "==> Skill 'zabbix' do agente"
install -d -m 755 -o "$HERMES_USER" -g "$HERMES_GROUP" "$HH/skills" "$HH/skills/devops" "$HH/skills/devops/zabbix"
install -m 644 -o "$HERMES_USER" -g "$HERMES_GROUP" "$SRC/hermes/skills/zabbix/SKILL.md" "$HH/skills/devops/zabbix/"

echo "==> Tarefas do agendador do Hermes ($HH/scripts)"
install -d -m 755 -o "$HERMES_USER" -g "$HERMES_GROUP" "$HH/scripts"
for p in daily weekly monthly; do
    install -m 755 -o "$HERMES_USER" -g "$HERMES_GROUP" \
        "$SRC/hermes/scripts/zabbix-relatorio.sh" "$HH/scripts/zabbix-relatorio-$p.sh"
done

echo "==> Atalho /usr/local/bin/zbxrep"
cat > /usr/local/bin/zbxrep <<EOF
#!/bin/sh
# Atalho: roda o gerador de relatórios como $HERMES_USER. Ex.: zbxrep --period weekly --dry-run
exec sudo -u $HERMES_USER $DEST/venv/bin/python $DEST/zabbix_whatsapp_report.py -c $DEST/config.yaml "\$@"
EOF
chmod 755 /usr/local/bin/zbxrep

echo "==> Teste com dados fictícios"
if sudo -u "$HERMES_USER" "$DEST/venv/bin/python" "$DEST/zabbix_whatsapp_report.py" --demo --period weekly \
    -c /nao-existe --output-dir "$DATA/relatorios" >/dev/null 2>&1; then
    echo "    OK: PDF de exemplo em $DATA/relatorios/"
else
    echo "    AVISO: o teste demo falhou; rode 'zbxrep --demo --period weekly -v' para ver o erro."
fi

cat <<EOF

Instalação concluída. Próximos passos (detalhes no TUTORIAL):
  1. Edite os clientes:            sudo nano $DEST/config.yaml
  2. Teste sem enviar:             zbxrep --period weekly --dry-run
  3. Agende os relatórios no Hermes (como $HERMES_USER):
       hermes cron create "0 7 * * *" --no-agent --script zabbix-relatorio-daily.sh   --deliver whatsapp --name zabbix-relatorio-diario
       hermes cron create "10 7 * * 1" --no-agent --script zabbix-relatorio-weekly.sh  --deliver whatsapp --name zabbix-relatorio-semanal
       hermes cron create "20 7 1 * *" --no-agent --script zabbix-relatorio-monthly.sh --deliver whatsapp --name zabbix-relatorio-mensal
  4. Recarregue o agente para ele ver a skill nova: hermes gateway restart
EOF
