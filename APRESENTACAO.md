# Alertas e Relatórios do Zabbix pelo WhatsApp

## O que é

Uma integração que leva o monitoramento do Zabbix direto para o WhatsApp — o canal que equipes técnicas e gestores realmente olham. Ela tem duas partes independentes:

**1. Alertas em tempo real.** Quando o Zabbix detecta um problema (servidor fora do ar, disco cheio, serviço parado, CPU alta), uma mensagem chega em segundos no grupo de WhatsApp do cliente ou no celular do plantonista. Quando o problema é resolvido, chega outra mensagem informando a duração. Reconhecimentos e comentários da equipe também são avisados, então todos sabem que alguém já está cuidando.

**2. Relatórios periódicos.** Todo dia, toda semana ou todo mês, cada cliente recebe automaticamente um resumo em texto no WhatsApp e um relatório em PDF com:

- disponibilidade de cada servidor no período;
- quantidade de problemas por severidade e por dia;
- problemas mais recorrentes e hosts que mais deram trabalho;
- tempo médio de resolução;
- o que está em aberto no momento.

## Por que usar

- **Resposta mais rápida.** E-mail de alerta se perde na caixa de entrada; WhatsApp é visto na hora.
- **Transparência com o cliente.** O cliente acompanha o ambiente dele no próprio grupo e recebe todo mês a prova do trabalho feito: disponibilidade alcançada, problemas tratados, tempo de resposta.
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

*Mais recorrentes:*
• Pouco espaço em disco em /var — 9x
• Serviço nginx parado — 6x
• Load average alto — 5x

_Detalhes no PDF em anexo._
```

## Como funciona

```
Zabbix (alerta em tempo real) ---+
                                 +--> Evolution API --> WhatsApp (grupo do cliente / plantonista)
Relatórios (diário/semanal/mês) -+    (servidor da empresa, Docker)
```

- **Evolution API**: software livre, instalado num servidor da empresa com Docker, que conecta um número de WhatsApp (via QR code, como o WhatsApp Web) e expõe uma API para enviar mensagens.
- **Tipo de mídia do Zabbix**: um webhook que o Zabbix chama a cada alerta; ele formata a mensagem e envia pela Evolution.
- **Gerador de relatórios**: um script Python agendado no cron que consulta a API do Zabbix de cada cliente, calcula os indicadores, gera o PDF e envia.
- **Monitor da própria integração**: um template do Zabbix que avisa (por outro canal) se o WhatsApp desconectar.

## Custos e limitações

- **Custo de software: zero.** Tudo é código aberto. O custo é um chip de celular dedicado e um servidor pequeno (1 vCPU, 2 GB de RAM bastam).
- **Não é a API oficial do WhatsApp.** A Evolution funciona como o WhatsApp Web. É a solução mais usada no Brasil para esse tipo de integração, mas o WhatsApp pode bloquear números que enviam spam. Por isso: chip dedicado, enviar só para grupos e pessoas que conhecem o número, e não usar o número para mais nada.
- **Precisa de um celular de vez em quando.** Se a sessão cair, alguém lê o QR code de novo; o template de monitoramento avisa quando isso acontece.
- **Disponibilidade calculada pelos problemas.** O cálculo considera o tempo com problemas de severidade Alta ou maior (configurável). Para SLA contratual formal, o módulo de Serviços/SLA do próprio Zabbix é a referência.

## O que vem no pacote

| Arquivo | Para quê |
|---|---|
| `TUTORIAL.pdf` / `TUTORIAL.md` | Passo a passo completo de instalação e de cadastro de clientes |
| `evolution/` | Instalação da Evolution API com Docker |
| `mediatype/whatsapp_evolution_mediatype.yaml` | Importar no Zabbix para os alertas |
| `mediatype/template_evolution_monitor.yaml` | Importar no Zabbix para vigiar a conexão do WhatsApp |
| `report/` | Gerador de relatórios + instalador |
| `exemplo/` | PDFs de exemplo gerados com dados fictícios |
