#!/usr/bin/env bash
# Instala o gerador de relatórios Zabbix -> WhatsApp em /opt/zabbix-whatsapp.
# Uso (como root, de dentro da pasta report/):  sudo ./install.sh
# Pode ser executado de novo para atualizar o script: config.yaml existente é preservado.
set -euo pipefail

DEST=/opt/zabbix-whatsapp
DATA=/var/lib/zabbix-whatsapp
LOGDIR=/var/log/zabbix-whatsapp
SVC_USER=zbxreport
SRC="$(cd "$(dirname "$0")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Execute como root: sudo $0" >&2
    exit 1
fi

if ! command -v python3 >/dev/null; then
    echo "python3 não encontrado. Instale: apt install python3 python3-venv  |  dnf install python3" >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Python 3.9+ necessário (encontrado: $(python3 -V)). No RHEL/Rocky 8: dnf install python39 e ajuste PYTHON abaixo." >&2
    exit 1
fi
PYTHON=${PYTHON:-python3}

if ! "$PYTHON" -m venv --help >/dev/null 2>&1 || ! "$PYTHON" -c 'import ensurepip' 2>/dev/null; then
    echo "Módulo venv ausente. Debian/Ubuntu: apt install python3-venv" >&2
    exit 1
fi

echo "==> Usuário de serviço $SVC_USER"
if ! id "$SVC_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$SVC_USER"
fi

echo "==> Diretórios"
install -d -m 755 "$DEST"
install -d -m 750 -o "$SVC_USER" -g "$SVC_USER" "$DATA" "$DATA/relatorios" "$LOGDIR"

echo "==> Arquivos"
install -m 755 "$SRC/zabbix_whatsapp_report.py" "$DEST/"
install -m 644 "$SRC/requirements.txt" "$SRC/config.example.yaml" "$DEST/"

if [[ ! -f "$DEST/config.yaml" ]]; then
    sed "s#^output_dir:.*#output_dir: $DATA/relatorios#" "$SRC/config.example.yaml" > "$DEST/config.yaml"
    echo "    config.yaml criado a partir do exemplo — EDITE antes de usar."
else
    echo "    config.yaml existente preservado."
fi
chown root:"$SVC_USER" "$DEST/config.yaml"
chmod 640 "$DEST/config.yaml"

echo "==> Ambiente Python (venv)"
"$PYTHON" -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --quiet --upgrade pip
"$DEST/venv/bin/pip" install --quiet -r "$DEST/requirements.txt"

echo "==> Atalho /usr/local/bin/zbxrep"
cat > /usr/local/bin/zbxrep <<EOF
#!/bin/sh
# Atalho: roda o gerador de relatórios como $SVC_USER com o config padrão. Ex.: zbxrep --period weekly --dry-run
exec sudo -u $SVC_USER $DEST/venv/bin/python $DEST/zabbix_whatsapp_report.py -c $DEST/config.yaml "\$@"
EOF
chmod 755 /usr/local/bin/zbxrep

echo "==> Agendamento (/etc/cron.d/zabbix-whatsapp)"
if [[ ! -f /etc/cron.d/zabbix-whatsapp ]]; then
    cat > /etc/cron.d/zabbix-whatsapp <<EOF
# Relatórios Zabbix -> WhatsApp. Cada cliente só recebe os períodos listados em "reports" no config.yaml.
# Linhas começando com # estão desativadas. Remova o # depois de testar com --dry-run.
# Os horários seguem o fuso do servidor (confira com: timedatectl).
SHELL=/bin/bash
#0  7 * * * $SVC_USER $DEST/venv/bin/python $DEST/zabbix_whatsapp_report.py -c $DEST/config.yaml --period daily   >> $LOGDIR/relatorios.log 2>&1
#10 7 * * 1 $SVC_USER $DEST/venv/bin/python $DEST/zabbix_whatsapp_report.py -c $DEST/config.yaml --period weekly  >> $LOGDIR/relatorios.log 2>&1
#20 7 1 * * $SVC_USER $DEST/venv/bin/python $DEST/zabbix_whatsapp_report.py -c $DEST/config.yaml --period monthly >> $LOGDIR/relatorios.log 2>&1
EOF
    chmod 644 /etc/cron.d/zabbix-whatsapp
    echo "    criado com as linhas DESATIVADAS (comentadas)."
else
    echo "    já existe, mantido."
fi

echo "==> Teste com dados fictícios"
sudo -u "$SVC_USER" "$DEST/venv/bin/python" "$DEST/zabbix_whatsapp_report.py" --demo --period weekly \
    -c /nao-existe --output-dir "$DATA/relatorios" >/dev/null 2>&1 \
    && echo "    OK: PDF de exemplo em $DATA/relatorios/" \
    || echo "    AVISO: o teste demo falhou; rode manualmente para ver o erro."

cat <<EOF

Instalação concluída.
Próximos passos:
  1. sudo nano $DEST/config.yaml
  2. zbxrep --list-groups
  3. zbxrep --period weekly --dry-run
  4. Ative as linhas em /etc/cron.d/zabbix-whatsapp
EOF
