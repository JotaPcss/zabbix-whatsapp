// Zabbix webhook: alertas via WhatsApp usando Evolution API (v2)
// Compatível com Zabbix 6.0+ (motor JavaScript Duktape, ES5 — sem let/const/arrow).
//
// Este é o mesmo script embutido em whatsapp_evolution_mediatype.yaml.
// Mantido separado para facilitar leitura, versionamento e testes.

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

// Aceita número (5511999998888, +55 (11) 99999-8888) ou JID de grupo (120363...@g.us).
function normalizeDestination(dest) {
    dest = dest.trim();
    if (dest.indexOf('@') !== -1) {
        return dest;
    }
    return dest.replace(/\D/g, '');
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

function sendText(p, destination, text) {
    var url = clean(p.evolution_url).replace(/\/+$/, '') +
        '/message/sendText/' + encodeURIComponent(clean(p.evolution_instance));

    var req = new HttpRequest();
    req.addHeader('Content-Type: application/json');
    req.addHeader('apikey: ' + clean(p.evolution_apikey));
    if (clean(p.http_proxy)) {
        req.setProxy(clean(p.http_proxy));
    }

    var payload = JSON.stringify({ number: destination, text: text, linkPreview: false });
    Zabbix.log(4, '[WhatsApp Evolution] POST ' + url + ' para ' + destination);

    var response = req.post(url, payload);
    var status = req.getStatus();

    if (status < 200 || status >= 300) {
        var detail = response;
        try {
            var parsed = JSON.parse(response);
            detail = JSON.stringify(parsed.response || parsed.message || parsed);
        } catch (e) { /* resposta não-JSON */ }
        throw 'HTTP ' + status + ' ao enviar para ' + destination + ': ' + detail;
    }
}

try {
    var params = JSON.parse(value);

    ['evolution_url', 'evolution_instance', 'evolution_apikey'].forEach(function (key) {
        if (!clean(params[key])) {
            throw 'Parâmetro obrigatório "' + key + '" não configurado no tipo de mídia.';
        }
    });

    // Separa só por vírgula, ponto e vírgula ou quebra de linha: "+55 (11) 99999-8888" é UM destino.
    var destinations = clean(params.send_to).split(/[,;\n]+/)
        .map(normalizeDestination)
        .filter(function (d) { return d.length > 0; });

    if (destinations.length === 0) {
        throw 'Nenhum destino informado. Preencha "Enviar para" na mídia do usuário (número ou JID do grupo).';
    }

    var text = buildMessage(params);
    var errors = [];

    destinations.forEach(function (dest) {
        try {
            sendText(params, dest, text);
        } catch (e) {
            errors.push(String(e));
        }
    });

    if (errors.length > 0) {
        throw errors.join(' | ');
    }

    return 'OK';
} catch (error) {
    Zabbix.log(3, '[WhatsApp Evolution] Falha: ' + error);
    throw 'Falha no envio WhatsApp: ' + error;
}
