// Zabbix webhook: alertas via WhatsApp usando o Hermes Agent (Nous Research).
// Compatível com Zabbix 6.0+ (motor JavaScript Duktape, ES5 — sem let/const/arrow).
//
// O script monta a mensagem e faz um POST assinado (HMAC-SHA256, esquema "V2" do Hermes)
// para uma rota de webhook do Hermes configurada com deliver_only: true. Nesse modo o Hermes
// entrega o texto direto no WhatsApp, sem chamar a IA: instantâneo e sem custo de LLM.
//
// Este é o mesmo script embutido em whatsapp_hermes_mediatype.yaml (gerado por build_mediatype.js).

var SEVERITY = {
    '0': { name: 'Não classificada', icon: '⚪' },
    '1': { name: 'Informação',       icon: '🔵' },
    '2': { name: 'Atenção',          icon: '🟡' },
    '3': { name: 'Média',            icon: '🟠' },
    '4': { name: 'Alta',             icon: '🔴' },
    '5': { name: 'Desastre',         icon: '🚨' }
};

// Retorna '' quando o valor está vazio ou é uma macro que o Zabbix não resolveu (ex: "{EVENT.OPDATA}").
function clean(value) {
    if (typeof value !== 'string') {
        return '';
    }
    value = value.trim();
    if (value === '' || /^\{[$#]?[A-Z][^{}]*\}$/.test(value) || /^\*UNKNOWN\*$/.test(value)) {
        return '';
    }
    return value;
}

function isTrue(value) {
    return /^(1|true|yes|sim)$/i.test(clean(value));
}

// Converte o destino em JID do WhatsApp, que é o chat_id usado pelo Hermes:
//   grupo:  120363025555555555@g.us        (mantido como está)
//   número: +55 (11) 99999-8888  ->  5511999998888@s.whatsapp.net
function toChatId(dest, dmSuffix) {
    dest = dest.trim();
    if (dest.indexOf('@') !== -1) {
        return dest;
    }
    var digits = dest.replace(/\D/g, '');
    return digits ? digits + dmSuffix : '';
}

function line(label, value) {
    value = clean(value);
    return value ? '*' + label + ':* ' + value + '\n' : '';
}

function eventLink(p) {
    var base = clean(p.zabbix_url);
    if (!base || !clean(p.trigger_id) || !clean(p.event_id)) {
        return '';
    }
    return '\n🔗 ' + base.replace(/\/+$/, '') + '/tr_events.php?triggerid=' +
        encodeURIComponent(p.trigger_id) + '&eventid=' + encodeURIComponent(p.event_id);
}

function buildMessage(p) {
    // Eventos que não são de trigger (discovery, autoregistro, internos) ou formato
    // padrão desligado: usa o assunto/mensagem do template de mensagem do Zabbix.
    if (!isTrue(p.use_default_format) || clean(p.event_source) !== '0') {
        var subject = clean(p.alert_subject);
        var body = clean(p.alert_message);
        return (subject ? '*' + subject + '*\n' : '') + body;
    }

    var sev = SEVERITY[clean(p.event_nseverity)] || SEVERITY['0'];
    var isUpdate = clean(p.event_update_status) === '1';
    var isRecovery = !isUpdate && clean(p.event_value) === '0';
    var header, details = '';

    if (isUpdate) {
        header = '🔄 *ATUALIZAÇÃO* | ' + sev.name;
    } else if (isRecovery) {
        header = '✅ *RESOLVIDO* | ' + sev.name;
    } else {
        header = sev.icon + ' *PROBLEMA* | ' + sev.name;
    }

    var host = clean(p.host_name);
    var ip = clean(p.host_ip);
    if (host && ip && ip !== host) {
        host += ' (' + ip + ')';
    }

    details += line('Cliente', p.client_name);
    details += line('Host', host);
    details += line('Problema', p.event_name);
    details += line('Dados', p.event_opdata);

    var start = (clean(p.event_date) + ' ' + clean(p.event_time)).trim();
    details += line('Início', start);

    if (isRecovery) {
        var end = (clean(p.event_recovery_date) + ' ' + clean(p.event_recovery_time)).trim();
        details += line('Fim', end);
        details += line('Duração', p.event_duration);
    }

    if (isUpdate) {
        details += line('Por', p.event_update_user);
        details += line('Ação', p.event_update_action);
        details += line('Mensagem', p.event_update_message);
    }

    details += line('Evento', p.event_id);

    return header + '\n\n' + details.replace(/\n$/, '') + eventLink(p);
}

// Identificador estável por (evento, tipo de notificação, destino). O Hermes guarda esse ID por
// 1 hora e descarta repetições: se o Zabbix tentar de novo um envio que na verdade chegou,
// o WhatsApp não recebe a mensagem duplicada.
function requestId(p, chatId) {
    var parts = [
        clean(p.event_id) || 'test',
        clean(p.event_value),
        clean(p.event_update_status),
        clean(p.event_update_date) + clean(p.event_update_time),
        chatId
    ];
    return 'zbx-' + sha256(parts.join('|')).substring(0, 32);
}

function deliver(p, chatId, text) {
    var url = clean(p.hermes_url).replace(/\/+$/, '') +
        '/webhooks/' + encodeURIComponent(clean(p.hermes_route));

    var body = JSON.stringify({
        chat_id: chatId,
        text: text,
        event_id: clean(p.event_id),
        severity: clean(p.event_nseverity),
        host: clean(p.host_name),
        client: clean(p.client_name)
    });

    // Esquema V2 do Hermes: HMAC-SHA256 em hex de "<timestamp>.<corpo>", com o timestamp em
    // segundos. O relógio do servidor Zabbix precisa estar sincronizado (±300 s do Hermes).
    var timestamp = String(Math.floor(Date.now() / 1000));
    var signature = hmac('sha256', clean(p.hermes_secret), timestamp + '.' + body);

    var req = new HttpRequest();
    req.addHeader('Content-Type: application/json');
    req.addHeader('X-Webhook-Timestamp: ' + timestamp);
    req.addHeader('X-Webhook-Signature-V2: ' + signature);
    req.addHeader('X-Request-ID: ' + requestId(p, chatId));
    if (clean(p.http_proxy)) {
        req.setProxy(clean(p.http_proxy));
    }

    Zabbix.log(4, '[WhatsApp Hermes] POST ' + url + ' para ' + chatId);
    var response = req.post(url, body);
    var status = req.getStatus();

    if (status < 200 || status >= 300) {
        var hint = {
            401: 'assinatura recusada: confira hermes_secret e o relógio (NTP) do servidor Zabbix',
            404: 'rota inexistente: confira hermes_route e o config.yaml do Hermes',
            413: 'mensagem grande demais',
            429: 'limite de envios por minuto da rota atingido (aumente rate_limit no Hermes)',
            502: 'o Hermes não conseguiu entregar no WhatsApp: confira o gateway e o chat_id'
        }[status] || '';
        throw 'HTTP ' + status + ' para ' + chatId + (hint ? ' (' + hint + ')' : '') + ': ' +
            String(response).substring(0, 300);
    }

    var result = {};
    try {
        result = JSON.parse(response);
    } catch (e) { /* resposta não-JSON */ }
    Zabbix.log(4, '[WhatsApp Hermes] ' + chatId + ': ' + (result.status || 'ok'));
}

try {
    var params = JSON.parse(value);

    ['hermes_url', 'hermes_route', 'hermes_secret'].forEach(function (key) {
        if (!clean(params[key])) {
            throw 'Parâmetro obrigatório "' + key + '" não configurado no tipo de mídia.';
        }
    });

    var dmSuffix = clean(params.dm_suffix) || '@s.whatsapp.net';

    // Separa só por vírgula, ponto e vírgula ou quebra de linha: "+55 (11) 99999-8888" é UM destino.
    var destinations = clean(params.send_to).split(/[,;\n]+/)
        .map(function (d) { return toChatId(d, dmSuffix); })
        .filter(function (d) { return d.length > 0; });

    if (destinations.length === 0) {
        throw 'Nenhum destino informado. Preencha "Enviar para" na mídia do usuário (número ou JID do grupo).';
    }

    var text = buildMessage(params);
    var errors = [];

    destinations.forEach(function (chatId) {
        try {
            deliver(params, chatId, text);
        } catch (e) {
            errors.push(String(e));
        }
    });

    if (errors.length > 0) {
        throw errors.join(' | ');
    }

    return 'OK';
} catch (error) {
    Zabbix.log(3, '[WhatsApp Hermes] Falha: ' + error);
    throw 'Falha no envio WhatsApp: ' + error;
}
