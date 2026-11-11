# Zabbix → WhatsApp (Evolution API)

> **Comece por aqui:** `APRESENTACAO.pdf` explica o projeto e `TUTORIAL.pdf` traz o passo a passo completo de instalação e de cadastro de clientes. Este README é a referência técnica resumida.

Alertas em tempo real e relatórios periódicos (texto + PDF) do Zabbix enviados por WhatsApp, para números individuais ou grupos de clientes. Compatível com **Zabbix 6.0, 6.2, 6.4, 7.0 e 7.2+**.

```
Zabbix (ação) ──webhook JS──▶ Evolution API ──▶ WhatsApp (grupo do cliente / plantonista)
cron ──▶ zabbix_whatsapp_report.py ──API──▶ Zabbix(s) dos clientes
                         └──texto + PDF──▶ Evolution API ──▶ WhatsApp
```

| Pasta | Conteúdo |
|---|---|
| `evolution/` | `docker-compose.yml` da Evolution API v2 (Postgres + Redis) |
| `mediatype/` | Tipo de mídia webhook para importar no Zabbix + script JS, teste e gerador do YAML |
| `report/` | Gerador de relatórios em Python, config de exemplo |

> ⚠️ A Evolution API usa o WhatsApp Web (não é a API oficial da Meta). Use um **chip dedicado** para o monitoramento, evite enviar para quem não salvou o número e não dispare volumes enormes — números podem ser bloqueados pelo WhatsApp.

---

## 1. Subir a Evolution API

Num servidor Linux com Docker:

```bash
cd evolution
cp .env.example .env
```

Edite `.env`: troque `AUTHENTICATION_API_KEY` e `POSTGRES_PASSWORD` (a senha aparece em dois lugares). Depois:

```bash
docker compose up -d
```

Crie a instância e conecte o número:

```bash
curl -X POST http://127.0.0.1:8080/instance/create -H "apikey: SUA_APIKEY" -H "Content-Type: application/json" -d '{"instanceName":"zabbix","integration":"WHATSAPP-BAILEYS","qrcode":true}'
```

Abra `http://IP:8080/manager`, entre com a apikey e leia o QR code da instância `zabbix` com o WhatsApp do chip (Aparelhos conectados → Conectar aparelho).

Se o Zabbix estiver em outra máquina, publique a Evolution atrás de um proxy reverso com HTTPS (nginx/Caddy) e restrinja por IP — a apikey dá controle total do número.

## 2. Alertas: tipo de mídia no Zabbix

1. **Alertas → Tipos de mídia → Importar** → `mediatype/whatsapp_evolution_mediatype.yaml`.
2. Abra o tipo de mídia **WhatsApp (Evolution API)** e preencha os parâmetros:
   - `evolution_url` – ex. `https://evolution.suaempresa.com.br`
   - `evolution_instance` – `zabbix`
   - `evolution_apikey` – a `AUTHENTICATION_API_KEY`
   - `zabbix_url` – URL do frontend, usada no link do evento (deixe vazio para não mandar link)
   - `http_proxy` – opcional
3. Use o botão **Testar** do tipo de mídia: coloque seu número em `send_to` e valores de exemplo nos demais.
4. Crie um usuário (ex. `whatsapp-acme`) e em **Mídia** adicione o tipo WhatsApp com **Enviar para**:
   - número: `5511999998888` (DDI + DDD + número; `+55 (11) 99999-8888` também funciona)
   - grupo: `120363025555555555@g.us` (descubra com `--list-groups`, seção 3)
   - vários destinos separados por vírgula
5. Crie a **ação de trigger** com operações de problema, recuperação e atualização enviando para esse usuário/grupo de usuários. Filtre por grupo de hosts ou tag para que cada cliente só receba o que é dele.

**Tag `cliente`:** se os hosts (ou templates/triggers) tiverem a tag `cliente=Acme Ltda`, o nome aparece no alerta. Útil no grupo interno de plantão que recebe de todos os clientes.

Exemplo de mensagem:

```
🔴 *PROBLEMA* | Alta

*Cliente:* Acme Ltda
*Host:* web01 (10.0.0.10)
*Problema:* Uso de CPU acima de 90% por 5m
*Dados:* CPU: 97.3 %
*Início:* 2026.11.11 10:15:00
*Evento:* 12345
🔗 https://zabbix.exemplo.com.br/tr_events.php?triggerid=678&eventid=12345
```

Recuperações saem como `✅ *RESOLVIDO*` com fim e duração; reconhecimentos/comentários como `🔄 *ATUALIZAÇÃO*`. Para usar os templates de mensagem do próprio Zabbix em vez desse formato, coloque `use_default_format = false`. Eventos de discovery, autoregistro e internos sempre usam os templates.

Se o envio falhar para qualquer destino, o alerta fica como falho no Zabbix (com o erro da Evolution) e o Zabbix tenta de novo conforme as tentativas configuradas no tipo de mídia.

### Alterando o script

Edite `mediatype/whatsapp_evolution.js`, depois:

```bash
node mediatype/test_webhook.js
```

```bash
node mediatype/build_mediatype.js
```

O segundo comando regenera o YAML de importação com o script novo.

## 3. Relatórios periódicos

Requisitos: Python 3.9+ no servidor que vai gerar os relatórios (pode ser o mesmo da Evolution).

**Jeito rápido:** `cd report && sudo ./install.sh`. Ele instala tudo em `/opt/zabbix-whatsapp`, cria o comando `zbxrep` e o cron desativado; veja o TUTORIAL. A instalação manual equivalente está abaixo.

```bash
sudo mkdir -p /opt/zabbix-whatsapp /var/lib/zabbix-whatsapp/relatorios
sudo cp report/* /opt/zabbix-whatsapp/
cd /opt/zabbix-whatsapp
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml
chmod 600 config.yaml
```

Edite `config.yaml` com a Evolution e um bloco por cliente. Cada cliente pode ter seu próprio Zabbix ou compartilhar o de vocês filtrando por `host_groups`. No Zabbix de cada cliente, crie um **API token** (Usuários → API tokens) para um usuário com leitura nos grupos desejados. Em Zabbix 6.0 sem token, use `zabbix_user`/`zabbix_password`.

Descobrir os JIDs dos grupos do WhatsApp (o número do chip precisa estar no grupo):

```bash
venv/bin/python zabbix_whatsapp_report.py -c config.yaml --list-groups
```

Ver um PDF de exemplo sem Zabbix nenhum:

```bash
venv/bin/python zabbix_whatsapp_report.py --demo --period monthly --output-dir /tmp
```

Testar um cliente real sem enviar nada:

```bash
venv/bin/python zabbix_whatsapp_report.py -c config.yaml --period weekly --client "Acme Ltda" --dry-run
```

Relatório de um intervalo específico (enviado de verdade, ignora `reports`):

```bash
venv/bin/python zabbix_whatsapp_report.py -c config.yaml --client "Acme Ltda" --start 2026-10-01 --end 2026-10-31
```

### O que vai no relatório

**Mensagem de texto:** hosts monitorados, disponibilidade média, problemas por severidade, tempo médio de resolução, problemas em aberto, hosts indisponíveis e os 3 problemas mais recorrentes.

**PDF anexo:** indicadores, problemas por severidade, gráfico de problemas por dia, top 10 problemas recorrentes (com tempo total), top 10 hosts com mais problemas, disponibilidade por host, problemas em aberto (com status de reconhecimento) e hosts com interface indisponível.

**Como a disponibilidade é calculada:** tempo em que o host teve pelo menos um problema com severidade ≥ `availability_severity` (padrão: Alta), com sobreposições somadas uma vez só, dividido pela duração do período. Problemas que começaram antes do período e ainda estão abertos entram no cálculo; problemas que começaram antes e foram resolvidos dentro do período não entram. Para SLA contratual, prefira o módulo de **Serviços/SLA** do Zabbix.

### Agendamento (cron)

`crontab -e` do usuário que roda o script:

```cron
# Diário às 07:00, semanal na segunda 07:10, mensal no dia 1 às 07:20
0 7 * * *  cd /opt/zabbix-whatsapp && venv/bin/python zabbix_whatsapp_report.py -c config.yaml --period daily   >> /var/log/zabbix-whatsapp.log 2>&1
10 7 * * 1 cd /opt/zabbix-whatsapp && venv/bin/python zabbix_whatsapp_report.py -c config.yaml --period weekly  >> /var/log/zabbix-whatsapp.log 2>&1
20 7 1 * * cd /opt/zabbix-whatsapp && venv/bin/python zabbix_whatsapp_report.py -c config.yaml --period monthly >> /var/log/zabbix-whatsapp.log 2>&1
```

Cada execução manda só para os clientes que têm aquele período em `reports`. Se um cliente falhar (Zabbix fora, token vencido), os outros continuam e o script sai com código 1 — dá para monitorar isso pelo próprio Zabbix.

## Solução de problemas

| Sintoma | Causa provável |
|---|---|
| `HTTP 401` | apikey errada no tipo de mídia/config |
| `HTTP 404` no envio | nome da instância errado ou instância apagada |
| `HTTP 400 ... exists: false` | número sem WhatsApp ou formato errado (falta DDI 55?) |
| Mensagem não chega no grupo | o chip saiu do grupo ou o JID mudou; rode `--list-groups` |
| Instância `close`/desconectada | ler o QR code de novo no `/manager` |
| `Not authorised` no relatório | token sem permissão de leitura nos grupos de hosts |
| Relatório vazio | `host_groups` com nome diferente do Zabbix (o script avisa no log) |
