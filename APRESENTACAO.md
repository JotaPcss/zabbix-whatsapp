# Zabbix no WhatsApp com o Hermes Agent

## O que é

Uma integração que leva o monitoramento do Zabbix direto para o WhatsApp, o canal que equipes técnicas e gestores realmente olham, e coloca um assistente de IA no plantão. Ela tem três partes:

**1. Alertas em tempo real.** Quando o Zabbix detecta um problema (servidor fora do ar, disco cheio, serviço parado, CPU alta), uma mensagem chega em segundos no grupo de WhatsApp do cliente ou no celular do plantonista. Quando o problema é resolvido, chega outra mensagem informando a duração. Reconhecimentos e comentários da equipe também são avisados, então todos sabem que alguém já está cuidando.

**2. Relatórios periódicos.** Todo dia, toda semana ou todo mês, cada cliente recebe automaticamente um resumo em texto no WhatsApp e um relatório em PDF com:

- disponibilidade de cada servidor no período;
- quantidade de problemas por severidade e por dia;
- problemas mais recorrentes e hosts que mais deram trabalho;
- tempo médio de resolução;
- o que está em aberto no momento.

**3. Assistente de plantão.** No grupo interno da equipe, qualquer técnico pode perguntar ao agente: "tem algum problema aberto?", "como está o web01 da Acme?", "me manda o relatório do mês passado da Beta", "reconhece o evento 12345 dizendo que estou verificando". O agente consulta o Zabbix do cliente e responde ali mesmo, com o PDF quando for o caso.

## Por que usar

- **Resposta mais rápida.** E-mail de alerta se perde na caixa de entrada; WhatsApp é visto na hora.
- **Transparência com o cliente.** O cliente acompanha o ambiente dele no próprio grupo e recebe todo mês a prova do trabalho feito: disponibilidade alcançada, problemas tratados, tempo de resposta.
- **Plantão mais ágil.** O técnico consulta e reconhece problemas pelo celular, sem abrir VPN e frontend do Zabbix.
- **Menos trabalho manual.** Ninguém precisa mais montar relatório de fim de mês na mão.
- **Um padrão para todos os clientes.** Funciona tanto com o Zabbix próprio de cada cliente quanto com um Zabbix central atendendo vários clientes, nas versões 6.0, 6.2, 6.4, 7.0 e 7.2.

## Exemplo de alerta

```
🔴 *PROBLEMA* | Alta

*Cliente:* Acme Ltda
*Host:* web01 (10.0.0.10)
*Problema:* Uso de CPU acima de 90% por 5m
*Dados:* CPU: 97.3 %
*Início:* 2026.11.11 10:15:00
*Evento:* 12345
🔗 https://zabbix.acme.com.br/tr_events.php?triggerid=678&eventid=12345
```

## Exemplo de resumo semanal

```
📊 *Relatório Semanal — Acme Ltda*
🗓️ 02/11/2026 a 08/11/2026

🖥️ *Hosts monitorados:* 13
📈 *Disponibilidade média:* 99,81%
⚠️ *Problemas no período:* 42
   Desastre: 1 · Alta: 9 · Média: 14 · Atenção: 18
⏱️ *Tempo médio de resolução:* 29min
🔴 *Em aberto agora:* 2

_Detalhes no PDF em anexo._
```

## Como funciona

```
Zabbix (alerta) -------------> Hermes Agent --> WhatsApp do cliente (sem IA)
Relatórios agendados --------> Hermes Agent --> WhatsApp do cliente (sem IA)
Técnico no grupo de plantão -> Hermes Agent <-> Zabbix (com IA)
```

- **Hermes Agent**: agente de IA de código aberto (licença MIT) da Nous Research, instalado num servidor da empresa. Ele conecta um número de WhatsApp (via QR code, como o WhatsApp Web), recebe os alertas do Zabbix, roda os relatórios agendados e conversa com a equipe.
- **Tipo de mídia do Zabbix**: um webhook que o Zabbix chama a cada alerta. Ele formata a mensagem e a envia ao Hermes com assinatura digital (HMAC), para ninguém mais conseguir disparar mensagens.
- **Gerador de relatórios**: um script Python que consulta a API do Zabbix de cada cliente, calcula os indicadores e gera o PDF.
- **Skill do Zabbix**: instruções que ensinam o agente a consultar o Zabbix com segurança, sempre pedindo confirmação antes de alterar algo.
- **Monitor da própria integração**: um template do Zabbix que avisa (por outro canal) se o Hermes ou o WhatsApp pararem.

**Alertas e relatórios não passam pela IA**: o Hermes só entrega o texto pronto. Isso os deixa instantâneos, previsíveis e sem custo de modelo. A IA é usada apenas quando alguém conversa com o agente.

## Custos e limitações

- **Software: zero.** Hermes Agent, Zabbix e a integração são de código aberto. O custo fixo é um chip de celular dedicado e um servidor pequeno (2 vCPU, 4 GB de RAM).
- **IA: só na conversa.** O assistente usa um modelo pago por uso (OpenRouter, Anthropic, OpenAI) ou um modelo local com Ollama, sem custo por mensagem, mas exigindo GPU. Alertas e relatórios funcionam mesmo sem modelo configurado.
- **Não é a API oficial do WhatsApp.** O Hermes conecta como o WhatsApp Web. O WhatsApp pode bloquear números que enviam spam. Por isso: chip dedicado, enviar só para grupos e pessoas que conhecem o número, e não usar o número para mais nada.
- **Precisa de um celular de vez em quando.** Se a sessão cair, alguém lê o QR code de novo; o template de monitoramento avisa quando isso acontece.
- **Acesso do agente.** O agente roda comandos no servidor da integração. A conversa fica restrita aos números da equipe e ao grupo interno; os grupos dos clientes só recebem mensagens.
- **Disponibilidade calculada pelos problemas.** O cálculo considera o tempo com problemas de severidade Alta ou maior (configurável). Para SLA contratual formal, o módulo de Serviços/SLA do próprio Zabbix é a referência.

## O que vem no pacote

| Arquivo | Para quê |
|---|---|
| `TUTORIAL.pdf` / `TUTORIAL.md` | Passo a passo completo de instalação e de cadastro de clientes |
| `install.sh` | Instala relatórios, skill e tarefas agendadas no servidor do Hermes |
| `hermes/` | Configuração do Hermes, skill do Zabbix e scripts |
| `mediatype/whatsapp_hermes_mediatype.yaml` | Importar no Zabbix para os alertas |
| `mediatype/template_hermes_monitor.yaml` | Importar no Zabbix para vigiar o Hermes e o WhatsApp |
| `report/` | Gerador de relatórios e ferramenta de consulta do agente |
| `exemplo/` | PDFs de exemplo gerados com dados fictícios |
