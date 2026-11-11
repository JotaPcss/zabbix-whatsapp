# Zabbix → WhatsApp com Hermes Agent

> **Comece por aqui:** `APRESENTACAO.pdf` explica o projeto e `TUTORIAL.pdf` traz o passo a passo completo de instalação e de cadastro de clientes. Este README é a referência técnica resumida.

Alertas em tempo real, relatórios periódicos (texto + PDF) e um assistente de IA que consulta o Zabbix, tudo no WhatsApp, usando o [Hermes Agent](https://hermes-agent.nousresearch.com/) da Nous Research. Compatível com **Zabbix 6.0, 6.2, 6.4, 7.0 e 7.2+**.

```
Zabbix (ação) --webhook assinado (HMAC)--> Hermes: rota deliver_only --> WhatsApp (sem IA)
Hermes cron --> zabbix_whatsapp_report.py --API--> Zabbix dos clientes
                         +--texto + PDF (hermes send)--> WhatsApp (sem IA)
Equipe no grupo de plantão --> agente Hermes --skill zabbix--> zbx_tool.py --API--> Zabbix
```

| Pasta | Conteúdo |
|---|---|
| `install.sh` | Instala relatórios, skill e tarefas agendadas no servidor do Hermes |
| `mediatype/` | Tipo de mídia webhook para o Zabbix (JS + YAML), teste, template de monitoramento do Hermes |
| `hermes/` | Trechos de `.env` e `config.yaml` do Hermes, skill `zabbix`, scripts de agendamento e de teste |
| `report/` | Gerador de relatórios, ferramenta do agente (`zbx_tool.py`), config de exemplo |
| `exemplo/` | PDFs de exemplo gerados com dados fictícios |

> A versão anterior, que usava a Evolution API em vez do Hermes, está na tag `v1-evolution`.

## Alertas

O tipo de mídia **WhatsApp (Hermes Agent)** monta a mensagem e faz `POST /webhooks/<rota>` no Hermes com:

- corpo JSON `{"chat_id": "...", "text": "...", "event_id": "...", ...}`;
- `X-Webhook-Timestamp` + `X-Webhook-Signature-V2` = HMAC-SHA256 hex de `"<timestamp>.<corpo>"` com o segredo da rota (relógios sincronizados, tolerância de ±300 s);
- `X-Request-ID` estável por evento/tipo de notificação/destino, para o Hermes descartar reenvios duplicados.

A rota do Hermes (`hermes/config.example.yaml`) usa `deliver: whatsapp`, `deliver_only: true`, `prompt: "{text}"` e `deliver_extra.chat_id: "{chat_id}"`: o texto vai direto para o chat, sem chamar o modelo.

Destinos em "Enviar para" (vários separados por vírgula): número com DDI (`5511999998888`, convertido para `5511999998888@s.whatsapp.net`) ou JID de grupo (`120363...@g.us`).

Mensagens: `PROBLEMA` com severidade, `RESOLVIDO` com duração, `ATUALIZAÇÃO` para reconhecimentos/comentários, link para o evento e a tag `cliente` do host. Discovery, autoregistro e eventos internos usam os templates de mensagem do Zabbix.

```bash
node mediatype/test_webhook.js
```

```bash
node mediatype/build_mediatype.js
```

O primeiro testa o script (inclusive a assinatura, verificada como o Hermes faz); o segundo regenera o YAML de importação.

## Relatórios

`report/zabbix_whatsapp_report.py` consulta a API de cada Zabbix (token ou usuário/senha; `auth` no corpo até 6.2 e `Authorization: Bearer` a partir de 6.4), gera o resumo e o PDF e entrega com:

```
hermes send --to whatsapp:<chat_id> --quiet            (texto pelo stdin)
hermes send --to whatsapp:<chat_id> --quiet "MEDIA:<pdf> [[as_document]]"
```

Conteúdo: hosts monitorados, disponibilidade (tempo com problema de severidade ≥ `availability_severity`, sobreposições somadas uma vez), problemas por severidade e por dia, top problemas e hosts, tempo médio de resolução, problemas em aberto e interfaces indisponíveis.

```bash
zbxrep --period weekly --client "Acme Ltda" --dry-run
```

```bash
zbxrep --demo --period monthly --output-dir /tmp
```

O agendamento é feito no próprio Hermes (`hermes cron create ... --no-agent --script zabbix-relatorio-weekly.sh`): sucesso não gera mensagem; falha (código ≠ 0) é avisada pelo Hermes no WhatsApp.

## Conversa com o agente

A skill `hermes/skills/zabbix/SKILL.md` ensina o agente a usar `report/zbx_tool.py`:

| Comando | Faz |
|---|---|
| `clientes` | lista os clientes do `config.yaml` |
| `problemas [--cliente X] [--min-sev N]` | problemas em aberto |
| `host --cliente X NOME` | interfaces e problemas de um host |
| `relatorio --cliente X [--periodo P]` | gera o relatório; o caminho do PDF na última linha é anexado pelo gateway |
| `reconhecer --cliente X EVENTID --mensagem M` | reconhece no Zabbix (só com `allow_ack: true`; o agente pede confirmação) |

A conversa usa um modelo de IA (OpenRouter, Anthropic, OpenAI ou Ollama local). Restrinja quem fala com o agente (`WHATSAPP_ALLOWED_USERS`, `WHATSAPP_GROUP_POLICY=allowlist` só com o grupo interno), porque ele tem acesso ao terminal do servidor.

## Estado dos testes

| Parte | Como foi testado |
|---|---|
| Script do webhook (mensagens, assinatura HMAC V2, deduplicação, erros) | Testes automatizados com Node simulando o Zabbix e a verificação do Hermes |
| Gerador de relatórios e `zbx_tool.py` | Ponta a ponta contra Zabbix 6.0 e 7.2 simulados e um `hermes send` simulado |
| Hermes real, importação no Zabbix real, `install.sh` em Linux | **Ainda não testados.** Valide num ambiente de teste antes de produção |

Pontos da documentação do Hermes que ainda precisam ser confirmados no primeiro uso real: o formato `whatsapp:<numero>@s.whatsapp.net` para conversas privadas (ajustável em `dm_suffix`), o envio de PDF por `hermes send` com a ponte Baileys, e `--list whatsapp` mostrando os grupos.
