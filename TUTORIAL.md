# Tutorial: Zabbix no WhatsApp com o Hermes Agent

Este guia leva você do zero até o primeiro cliente recebendo alertas e relatórios no WhatsApp, e a equipe conversando com um agente de IA que consulta o Zabbix. Faça uma vez as etapas 1 a 3 (infraestrutura da empresa). Depois, repita a etapa 4 para cada cliente novo.

| Etapa | O que é | Quando |
|---|---|---|
| 1. Preparar o número | Chip e celular dedicados | Uma vez |
| 2. Instalar o Hermes Agent | Agente + WhatsApp + webhook | Uma vez |
| 3. Instalar a integração | Relatórios, skill do agente, agendamentos | Uma vez |
| 4. Cadastrar um cliente | Alertas + relatórios do cliente | Por cliente |
| 5. Conversar com o agente | Modelo de IA e grupo de plantão | Quando quiser |
| 6. Operação do dia a dia | Monitoramento, backup, atualização | Contínuo |

## Como as peças se encaixam

- **Alertas:** o Zabbix chama um webhook do Hermes. A rota é `deliver_only`: o texto vai direto para o WhatsApp, **sem passar pela IA**. É instantâneo e não tem custo de modelo.
- **Relatórios:** o agendador do Hermes roda o gerador de relatórios, que envia texto + PDF com `hermes send`. Também **sem IA**.
- **Conversa:** no grupo interno de plantão, a equipe pergunta ao agente ("@Monitoramento como está a Acme?"). O agente usa a skill `zabbix` para consultar o Zabbix e responder. Só esta parte usa um modelo de IA.

Os grupos dos clientes **só recebem** alertas e relatórios. O agente não lê nem responde mensagens neles.

## Antes de começar

Você vai precisar de:

- **Um servidor Linux da empresa** (VM ou VPS) com 2 vCPU, 4 GB de RAM e 20 GB de disco, Debian 12, Ubuntu 22.04/24.04 ou Rocky/Alma 9.
- **Um chip de celular exclusivo** e um aparelho para ler o QR code (pode ser um celular antigo).
- **Acesso de administrador (Super admin)** ao Zabbix de cada cliente.
- **Um nome DNS com HTTPS** para o webhook do Hermes (ex.: `hermes.suaempresa.com.br`), se algum Zabbix de cliente estiver fora da rede desse servidor.
- **Relógio sincronizado (NTP)** no servidor do Hermes e nos servidores Zabbix: os alertas são assinados com horário e o Hermes recusa diferenças acima de 5 minutos.

Os caminhos de menu do Zabbix aparecem assim: **7.x** primeiro, *(6.0 entre parênteses)*.

## Etapa 1 — Preparar o número de WhatsApp

1. Ative o chip num celular e instale o **WhatsApp Business** (recomendado) ou o WhatsApp comum.
2. Configure o perfil: nome "Monitoramento - Sua Empresa", foto com o logo e uma descrição como "Número automático de alertas.".
3. Use o número por alguns dias antes de colocar em produção: entre nos grupos, troque algumas mensagens. Números novos que disparam muitas mensagens logo de cara têm mais risco de bloqueio.
4. **Não use esse número para mais nada.**

O Hermes conecta ao WhatsApp como o WhatsApp Web (ponte Baileys), não pela API oficial da Meta. Para não ter o número bloqueado:

- Envie só para grupos onde o número foi adicionado e para pessoas que salvaram o contato.
- Peça aos clientes para salvar o número e não marcá-lo como spam.
- Não mande alertas de severidade baixa (Informação/Não classificada) para o WhatsApp.

## Etapa 2 — Instalar o Hermes Agent

### 2.1 Usuário, Node.js e Hermes

Crie um usuário dedicado (como root):

```bash
useradd -m -s /bin/bash hermes
timedatectl set-timezone America/Sao_Paulo
timedatectl set-ntp true
```

A ponte do WhatsApp precisa do Node.js 20 ou mais novo. No Debian/Ubuntu:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs git python3 python3-venv openssl
```

No Rocky/Alma: `dnf module install -y nodejs:22` e `dnf install -y git python3 openssl`.

Instale o Hermes **como o usuário hermes**:

```bash
su - hermes
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.bashrc
hermes setup
```

O `hermes setup` pede um provedor de modelo de IA. Alertas e relatórios não usam IA; o modelo só é necessário para a conversa (etapa 5). Se ainda não decidiu, veja a etapa 5 antes de responder. Ao final, rode `hermes doctor` para conferir a instalação.

### 2.2 Conectar o WhatsApp

Ainda como `hermes`, pareie o número:

```bash
hermes whatsapp
```

No celular do chip: **WhatsApp › Aparelhos conectados › Conectar um aparelho** e leia o QR code do terminal.

Depois, acrescente ao `~/.hermes/.env` o conteúdo de `hermes/env.example` do pacote e ajuste:

- `WHATSAPP_ALLOWED_USERS`: números da equipe técnica que podem conversar com o agente no privado.
- `WHATSAPP_GROUP_ALLOWED_USERS`: o JID do grupo interno de plantão (você descobre o JID no passo 4.3; deixe para preencher depois).

### 2.3 Criar a rota de webhook dos alertas

Gere o segredo da rota e guarde num cofre de senhas. Ele vai no Hermes e no Zabbix:

```bash
openssl rand -hex 32
```

Abra `~/.hermes/config.yaml` e acrescente o bloco de `hermes/config.example.yaml` do pacote, trocando `TROQUE_POR_UM_SEGREDO_FORTE` pelo segredo. Se o arquivo já tiver uma seção `platforms:`, coloque só o bloco `webhook:` dentro dela. O trecho importante é:

```yaml
routes:
  zabbix-alert:
    secret: "SEU_SEGREDO"
    deliver: whatsapp
    deliver_only: true
    prompt: "{text}"
    deliver_extra:
      chat_id: "{chat_id}"
```

### 2.4 Rodar como serviço

```bash
hermes gateway install
hermes gateway status
```

O gateway mantém o WhatsApp conectado, recebe os webhooks e roda as tarefas agendadas. Confira o webhook:

```bash
curl -s http://127.0.0.1:8644/health
```

A resposta deve ser `{"status": "ok", "platform": "webhook"}`.

### 2.5 Enviar uma mensagem de teste

Do pacote, rode o teste assinado (troque pelo segredo e pelo seu número com 55 + DDD):

```bash
bash hermes/scripts/testar-webhook.sh "SEU_SEGREDO" 5511999998888
```

A resposta esperada termina com `HTTP 200` e `"status": "delivered"`, e a mensagem "Teste | Zabbix → Hermes → WhatsApp funcionando" chega no seu WhatsApp.

### 2.6 Publicar com HTTPS (quando o Zabbix do cliente está em outra rede)

Para que o Zabbix de um cliente alcance o webhook, publique a porta 8644 com HTTPS e **libere apenas os IPs dos Zabbix dos clientes**. Mesmo com a assinatura HMAC, não deixe o webhook aberto para a internet inteira.

Exemplo com nginx + Let's Encrypt (Debian/Ubuntu, como root):

```bash
apt install -y nginx certbot python3-certbot-nginx
```

Crie `/etc/nginx/sites-available/hermes`:

```nginx
server {
    listen 80;
    server_name hermes.suaempresa.com.br;

    # Só o caminho dos webhooks fica exposto
    location /webhooks/ {
        allow 203.0.113.10;   # Zabbix da Acme Ltda
        allow 198.51.100.20;  # Zabbix da Beta Transportes
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://127.0.0.1:8644;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        return 404;
    }
}
```

Ative o site e emita o certificado:

```bash
ln -s /etc/nginx/sites-available/hermes /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d hermes.suaempresa.com.br
```

A cada cliente novo, inclua o IP do Zabbix dele com um `allow` e rode `systemctl reload nginx`.

## Etapa 3 — Instalar a integração

Como root, baixe o projeto e rode o instalador, informando o usuário do Hermes:

```bash
git clone https://github.com/JotaPcss/zabbix-whatsapp.git /root/zabbix-whatsapp
cd /root/zabbix-whatsapp
HERMES_USER=hermes ./install.sh
```

O instalador:

- instala o gerador de relatórios e a ferramenta do agente em `/opt/zabbix-whatsapp`, com um ambiente Python isolado;
- cria `/opt/zabbix-whatsapp/config.yaml` a partir do exemplo, já apontando para o `hermes`;
- instala a skill `zabbix` em `~hermes/.hermes/skills/devops/zabbix/`;
- instala as tarefas `zabbix-relatorio-{daily,weekly,monthly}.sh` em `~hermes/.hermes/scripts/`;
- cria o comando `zbxrep`, um atalho para rodar o gerador (usado no resto deste tutorial);
- gera um PDF de demonstração em `/var/lib/zabbix-whatsapp/relatorios/` para provar que tudo funciona.

Em `/opt/zabbix-whatsapp/config.yaml`, coloque o nome da sua empresa em `company_name` (aparece no rodapé do PDF). Os clientes você cadastra na etapa 4.

Depois, recarregue o gateway para o agente enxergar a skill nova:

```bash
su - hermes -c "hermes gateway restart"
```

### Agendar os relatórios no Hermes

Como `hermes`, crie as três tarefas. Elas rodam o gerador sem IA; se der tudo certo, não mandam nada além dos relatórios; se falhar, o Hermes avisa o erro no WhatsApp (canal padrão):

```bash
hermes cron create "0 7 * * *" --no-agent --deliver whatsapp \
  --script zabbix-relatorio-daily.sh --name zabbix-relatorio-diario
hermes cron create "10 7 * * 1" --no-agent --deliver whatsapp \
  --script zabbix-relatorio-weekly.sh --name zabbix-relatorio-semanal
hermes cron create "20 7 1 * *" --no-agent --deliver whatsapp \
  --script zabbix-relatorio-monthly.sh --name zabbix-relatorio-mensal
hermes cron list
```

Com esses horários, o diário sai todo dia às 07:00 (dia anterior), o semanal na segunda às 07:10 (segunda a domingo anteriores) e o mensal no dia 1 às 07:20 (mês anterior). Cada execução só envia para os clientes que têm aquele período em `reports`.

## Etapa 4 — Cadastrar um cliente

Faça esta etapa uma vez em cada Zabbix. Se vários clientes ficam no mesmo Zabbix central, importe o tipo de mídia só uma vez e repita a partir do passo 4.3 para cada cliente.

### 4.1 Importar o tipo de mídia

1. **Alerts › Media types** *(Administration › Media types)* › botão **Import**.
2. Escolha `mediatype/whatsapp_hermes_mediatype.yaml` e confirme.
3. Abra o tipo **WhatsApp (Hermes Agent)** e preencha os parâmetros:

| Parâmetro | Valor |
|---|---|
| `hermes_url` | `https://hermes.suaempresa.com.br`, ou `http://127.0.0.1:8644` se o Zabbix estiver no mesmo servidor |
| `hermes_route` | `zabbix-alert` |
| `hermes_secret` | o segredo da rota (passo 2.3) |
| `zabbix_url` | URL do frontend deste Zabbix, ex. `https://zabbix.acme.com.br` (vai no link de cada alerta; deixe vazio se o cliente não acessa o Zabbix) |

Não altere os parâmetros que têm macros entre chaves `{...}`.

### 4.2 Testar o tipo de mídia

Ainda no tipo de mídia, clique em **Test**. Preencha `send_to` com o seu número (`5511999998888`), `event_source` = `0`, `event_value` = `1`, `event_nseverity` = `4`, `event_name` = `Teste`, `host_name` = `teste`, e clique em **Test**. Deve aparecer `OK` e chegar um alerta "PROBLEMA | Alta" no seu WhatsApp.

Se aparecer erro, a mensagem já traz uma dica (assinatura, rota, limite). Veja também "Solução de problemas" no fim deste guia.

### 4.3 Criar o grupo de WhatsApp do cliente e descobrir o JID

1. No celular do chip, crie um grupo "Monitoramento - Acme Ltda" com a equipe de vocês e os contatos do cliente. Ou peça para o cliente adicionar o número a um grupo existente.
2. Descubra o identificador (JID) do grupo, que termina em `@g.us`. Primeiro tente:

```bash
zbxrep --list-targets
```

Se o grupo não aparecer, ligue o modo de depuração da ponte, mande uma mensagem qualquer no grupo e procure o JID no log:

```bash
su - hermes
echo "WHATSAPP_DEBUG=true" >> ~/.hermes/.env && hermes gateway restart
grep -ho '[0-9]*@g\.us' $(find ~/.hermes -name bridge.log) | sort -u
```

Depois de anotar o JID, remova a linha `WHATSAPP_DEBUG=true` e rode `hermes gateway restart`.

### 4.4 Criar o usuário que recebe os alertas

O Zabbix só envia alerta para usuários que têm **permissão de leitura** nos hosts do problema. Este é o erro mais comum.

1. **Users › User groups** *(Administration › User groups)* › **Create user group**:
   - Nome: `WhatsApp - Acme`
   - Aba **Host permissions** *(Permissions)*: adicione os grupos de hosts do cliente com **Read**.
2. **Users › Users** *(Administration › Users)* › **Create user**:
   - Username: `whatsapp-acme`, Groups: `WhatsApp - Acme`, senha forte qualquer (ninguém vai logar com ele).
   - Aba **Media** › **Add**: Type `WhatsApp (Hermes Agent)`, Send to `120363025555555555@g.us`. Para mandar também para um técnico, acrescente o número separado por vírgula. Em *Use if severity*, marque Média, Alta e Desastre (sugestão).
   - Aba **Permissions**: Role `User role`.

Para o plantão da sua empresa, crie também um usuário `whatsapp-plantao` com leitura em **todos** os grupos e o JID do grupo interno. Coloque a tag `cliente` nos hosts (ex.: `cliente` = `Acme Ltda`) para que cada alerta mostre de qual cliente ele é.

### 4.5 Criar a ação

**Alerts › Actions › Trigger actions** *(Configuration › Actions › Trigger actions)* › **Create action**:

- **Action**: Name `WhatsApp - Acme`. Conditions: `Host group equals <grupos do cliente>` e, se quiser, `Trigger severity is greater than or equals Average`.
- **Operations**:
  - Operations › Add: *Send to users* `whatsapp-acme`, *Send only to* `WhatsApp (Hermes Agent)`.
  - Recovery operations › Add: *Notify all involved*.
  - Update operations › Add: *Notify all involved* (avisa quando alguém reconhece ou comenta o problema).

Salve. Para testar de verdade, provoque um problema controlado num host do cliente e confirme que chegam o "PROBLEMA" e depois o "RESOLVIDO".

### 4.6 Liberar o acesso do relatório e do agente à API do Zabbix

1. Crie um user group `Relatórios` com **Read** nos grupos de hosts do cliente e um usuário `relatorios` nele, com Role `User role`. A role padrão já permite reconhecer problemas, o que o agente usa na etapa 5.
2. **Users › API tokens** *(Administration › General › API tokens)* › **Create API token**: User `relatorios`, Name `whatsapp-hermes`, desmarque *Set expiration date*. Copie o token; ele aparece uma única vez.
3. Garanta que o servidor do Hermes alcança o frontend do Zabbix do cliente (HTTPS 443). Se o Zabbix do cliente não é público, use VPN ou libere o IP do seu servidor no firewall do cliente.

No Zabbix 6.0 sem API tokens disponíveis, use `zabbix_user` e `zabbix_password` no lugar do token.

### 4.7 Adicionar o cliente no config.yaml

```bash
nano /opt/zabbix-whatsapp/config.yaml
```

Na lista `clients:`, adicione o bloco abaixo e apague os clientes de exemplo:

```yaml
  - name: "Acme Ltda"
    zabbix_url: https://zabbix.acme.com.br
    zabbix_token: "COLE_O_TOKEN_AQUI"
    send_to:
      - "120363025555555555@g.us"
    reports: [weekly, monthly]
```

Opções por cliente:

| Opção | Para quê | Padrão |
|---|---|---|
| `host_groups` | Só considerar estes grupos (obrigatório num Zabbix central com vários clientes) | todos |
| `reports` | Quais relatórios o cliente recebe: `daily`, `weekly`, `monthly` | o de `defaults` |
| `min_severity` | Severidade mínima contada no relatório (2 = Atenção) | 2 |
| `availability_severity` | A partir de qual severidade conta como indisponível (4 = Alta) | 4 |
| `allow_ack` | O agente pode reconhecer problemas deste cliente (com confirmação) | false |
| `attach_pdf` | Enviar o PDF além do texto | true |
| `verify_ssl` | `false` para certificado autoassinado | true |
| `timezone` | Fuso do cliente | America/Sao_Paulo |

O YAML é sensível à indentação: use espaços, nunca TAB, e mantenha o alinhamento dos exemplos.

### 4.8 Testar o relatório

Primeiro, gere sem enviar e confira o texto e o PDF:

```bash
zbxrep --period weekly --client "Acme Ltda" --dry-run
```

Quando estiver bom, envie de verdade uma vez:

```bash
zbxrep --period weekly --client "Acme Ltda"
```

Para um relatório avulso (por exemplo, pedido de um cliente sobre um incidente), indique o intervalo:

```bash
zbxrep --client "Acme Ltda" --start 2026-10-01 --end 2026-10-31
```

### Checklist de cliente novo

- [ ] Número do monitoramento adicionado ao grupo do cliente e JID anotado
- [ ] IP do Zabbix do cliente liberado no nginx (`allow`)
- [ ] Relógio do Zabbix do cliente sincronizado (NTP)
- [ ] Tipo de mídia importado, parâmetros preenchidos, botão Test OK
- [ ] User group com Read nos hosts + usuário `whatsapp-<cliente>` com a mídia
- [ ] Ação criada com operações de problema, recuperação e atualização
- [ ] Usuário `relatorios` + API token criados
- [ ] Bloco do cliente no `config.yaml`
- [ ] `--dry-run` conferido e um envio real feito
- [ ] Cliente orientado a salvar o número do monitoramento

## Etapa 5 — Conversar com o agente

### Modelo de IA

A conversa precisa de um modelo. Escolha um com `hermes model` (como `hermes`) e coloque a chave no `~/.hermes/.env`:

| Opção | Chave no .env | Observação |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | Uma chave para vários modelos, paga por uso. Mais simples para começar |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | Paga por uso |
| OpenAI | `OPENAI_API_KEY` | Paga por uso |
| Ollama (local) | nenhuma | Sem custo por mensagem e sem dados saindo da empresa; precisa de GPU e de 64k de contexto |

Para Ollama, rode `OLLAMA_CONTEXT_LENGTH=64000 ollama serve` e configure no `~/.hermes/config.yaml`:

```yaml
model:
  default: qwen2.5-coder:32b
  provider: custom
  base_url: http://localhost:11434/v1
  context_length: 64000
```

### Grupo interno de plantão

1. Crie um grupo "Plantão - Sua Empresa" só com a equipe técnica e o número do monitoramento.
2. Descubra o JID (passo 4.3) e coloque em `WHATSAPP_GROUP_ALLOWED_USERS` no `~/.hermes/.env`.
3. `hermes gateway restart`.

No grupo, mencione o número para falar com o agente. Exemplos:

- "@Monitoramento tem algum problema aberto?"
- "@Monitoramento como está o web01 da Acme?"
- "@Monitoramento me manda o relatório do mês passado da Beta"
- "@Monitoramento reconhece o evento 12345 da Acme dizendo que estou verificando"

O agente sempre pede confirmação antes de reconhecer um problema, e só consegue fazer isso nos clientes com `allow_ack: true` no `config.yaml`.

### Segurança da conversa

O agente do Hermes pode executar comandos no servidor onde roda. Por isso:

- **Libere a conversa só para a equipe técnica:** `WHATSAPP_ALLOWED_USERS` com os números dos técnicos e `WHATSAPP_GROUP_POLICY=allowlist` com apenas o grupo interno. Nunca coloque grupos de clientes na allowlist.
- **Mantenha `WHATSAPP_REQUIRE_MENTION=true`** para o agente só responder quando chamado.
- **Não rode o Hermes como root** e não use o modo `--yolo`: comandos perigosos pedem aprovação (`/approve`) no chat.
- O `config.yaml` tem os tokens do Zabbix de todos os clientes. A skill orienta o agente a nunca exibi-lo, mas a proteção real é o acesso restrito acima.

## Etapa 6 — Operação do dia a dia

### Vigiar a própria integração

Se o WhatsApp desconectar, os alertas param de sair sem ninguém perceber. Para evitar isso:

1. No Zabbix da empresa: **Data collection › Templates** *(Configuration › Templates)* › **Import** › `mediatype/template_hermes_monitor.yaml`.
2. Vincule o template **Hermes Agent WhatsApp gateway** ao host do servidor do Hermes (precisa do Zabbix agent nele).
3. Ajuste as macros `{$HERMES.WEBHOOK.URL}`, `{$HERMES.BRIDGE.HOST}` e `{$HERMES.BRIDGE.PORT}` se não usar os padrões.
4. Crie uma ação que envie os alertas desse host por **e-mail, Telegram ou SMS**, nunca pelo WhatsApp.

Falhas nas tarefas de relatório já chegam sozinhas: o agendador do Hermes avisa no WhatsApp quando um script sai com erro. O log completo fica em `/var/log/zabbix-whatsapp/relatorios.log`.

### Quando o WhatsApp desconecta

Como `hermes`, rode `hermes whatsapp`, leia o QR code com o celular do chip e depois `hermes gateway restart`. Mantenha esse celular ligado e com internet de vez em quando: se ficar mais de 14 dias desconectado, o WhatsApp encerra as sessões de aparelhos conectados.

### Atualizar

O Hermes (como `hermes`):

```bash
hermes update
hermes gateway restart
```

A integração (como root, na pasta do projeto). O instalador preserva o `config.yaml`:

```bash
git pull
HERMES_USER=hermes ./install.sh
```

### Backup

O que precisa de backup:

- `~hermes/.hermes/` inteiro (configuração, segredo da rota, sessão do WhatsApp, tarefas agendadas)
- `/opt/zabbix-whatsapp/config.yaml`

### Rotação de log

Crie `/etc/logrotate.d/zabbix-whatsapp`:

```text
/var/log/zabbix-whatsapp/*.log {
    monthly
    rotate 12
    compress
    missingok
    notifempty
    su hermes hermes
}
```

## Personalização

- **Texto dos alertas:** edite `mediatype/whatsapp_hermes.js`. Rode `node mediatype/test_webhook.js` para testar e `node mediatype/build_mediatype.js` para gerar o YAML novo; depois, importe de novo no Zabbix, marcando para atualizar o existente. Para usar os templates de mensagem do próprio Zabbix, mude o parâmetro `use_default_format` para `false`.
- **Comportamento do agente:** edite `~hermes/.hermes/skills/devops/zabbix/SKILL.md` (o original está em `hermes/skills/zabbix/`).
- **Rodapé e nome no PDF:** `company_name` no `config.yaml`.
- **Conteúdo do PDF:** função `build_pdf` em `zabbix_whatsapp_report.py`.

## Solução de problemas

Para mais detalhes de um erro no relatório, repita o comando com `-v`.

| Sintoma | Causa e solução |
|---|---|
| Test do tipo de mídia: `HTTP 401` | segredo diferente entre Zabbix e Hermes, ou relógio do Zabbix com mais de 5 min de diferença (NTP) |
| `HTTP 404` | `hermes_route` diferente do nome da rota no `config.yaml` do Hermes, ou gateway sem a rota carregada (`hermes gateway restart`) |
| `HTTP 429` | tempestade de alertas: aumente `rate_limit` da plataforma webhook no `config.yaml` do Hermes |
| `HTTP 502` | o Hermes não conseguiu entregar: WhatsApp desconectado ou JID errado |
| `Couldn't connect` / timeout | o Zabbix não alcança o Hermes: DNS, firewall, `allow` do nginx |
| Test OK, mas alertas reais não chegam | usuário sem permissão Read nos hosts, mídia com severidade desmarcada, ou ação com condição errada. Veja em **Reports › Action log** |
| Mensagem chega no número, mas não no grupo | o número saiu do grupo ou o JID está errado; confira o passo 4.3 |
| Relatório: `hermes send: falha na entrega` | gateway parado (`hermes gateway status`) ou WhatsApp desconectado |
| Relatório: `comando do Hermes não encontrado` | ajuste `hermes.command` no `config.yaml` com o caminho completo (`su - hermes -c "command -v hermes"`) |
| Relatório: `Not authorised` | token errado, expirado, ou usuário sem Read nos grupos |
| Agente não responde no grupo | grupo fora de `WHATSAPP_GROUP_ALLOWED_USERS`, faltou mencionar o número, ou nenhum modelo de IA configurado |
| Agente não conhece os comandos do Zabbix | skill não carregada: confira `~hermes/.hermes/skills/devops/zabbix/SKILL.md` e rode `hermes gateway restart` |
