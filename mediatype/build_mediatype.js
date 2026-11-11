// Gera whatsapp_hermes_mediatype.yaml a partir de whatsapp_hermes.js.
// Uso: node build_mediatype.js
// Rode sempre que alterar o script, para manter o YAML de importação sincronizado.

var fs = require('fs');
var path = require('path');

var script = fs.readFileSync(path.join(__dirname, 'whatsapp_hermes.js'), 'utf8')
    .replace(/\r\n/g, '\n')
    .replace(/\s+$/, '');

var params = [
    ['alert_message', '{ALERT.MESSAGE}'],
    ['alert_subject', '{ALERT.SUBJECT}'],
    ['client_name', '{EVENT.TAGS.cliente}'],
    ['dm_suffix', '@s.whatsapp.net'],
    ['event_date', '{EVENT.DATE}'],
    ['event_duration', '{EVENT.DURATION}'],
    ['event_id', '{EVENT.ID}'],
    ['event_name', '{EVENT.NAME}'],
    ['event_nseverity', '{EVENT.NSEVERITY}'],
    ['event_opdata', '{EVENT.OPDATA}'],
    ['event_recovery_date', '{EVENT.RECOVERY.DATE}'],
    ['event_recovery_time', '{EVENT.RECOVERY.TIME}'],
    ['event_source', '{EVENT.SOURCE}'],
    ['event_time', '{EVENT.TIME}'],
    ['event_update_action', '{EVENT.UPDATE.ACTION}'],
    ['event_update_date', '{EVENT.UPDATE.DATE}'],
    ['event_update_message', '{EVENT.UPDATE.MESSAGE}'],
    ['event_update_status', '{EVENT.UPDATE.STATUS}'],
    ['event_update_time', '{EVENT.UPDATE.TIME}'],
    ['event_update_user', '{USER.FULLNAME}'],
    ['event_value', '{EVENT.VALUE}'],
    ['hermes_route', 'zabbix-alert'],
    ['hermes_secret', '<SEGREDO_DA_ROTA>'],
    ['hermes_url', 'https://hermes.suaempresa.com.br'],
    ['host_ip', '{HOST.IP}'],
    ['host_name', '{HOST.NAME}'],
    ['http_proxy', ''],
    ['send_to', '{ALERT.SENDTO}'],
    ['trigger_id', '{TRIGGER.ID}'],
    ['use_default_format', 'true'],
    ['zabbix_url', 'https://zabbix.suaempresa.com.br']
];

var templates = [
    ['TRIGGERS', 'PROBLEM', 'Problema: {EVENT.NAME}',
        'Problema iniciado às {EVENT.TIME} de {EVENT.DATE}\nHost: {HOST.NAME}\nSeveridade: {EVENT.SEVERITY}\nDados: {EVENT.OPDATA}\nEvento: {EVENT.ID}'],
    ['TRIGGERS', 'RECOVERY', 'Resolvido em {EVENT.DURATION}: {EVENT.NAME}',
        'Problema resolvido às {EVENT.RECOVERY.TIME} de {EVENT.RECOVERY.DATE}\nHost: {HOST.NAME}\nSeveridade: {EVENT.SEVERITY}\nDuração: {EVENT.DURATION}\nEvento: {EVENT.ID}'],
    ['TRIGGERS', 'UPDATE', 'Atualizado: {EVENT.NAME}',
        '{USER.FULLNAME} {EVENT.UPDATE.ACTION} o problema às {EVENT.UPDATE.TIME} de {EVENT.UPDATE.DATE}.\n{EVENT.UPDATE.MESSAGE}\n\nStatus atual: {EVENT.STATUS}'],
    ['DISCOVERY', '', 'Descoberta: {DISCOVERY.DEVICE.STATUS} {DISCOVERY.DEVICE.IPADDRESS}',
        'Regra: {DISCOVERY.RULE.NAME}\nIP: {DISCOVERY.DEVICE.IPADDRESS}\nDNS: {DISCOVERY.DEVICE.DNS}\nStatus: {DISCOVERY.DEVICE.STATUS}'],
    ['AUTOREGISTRATION', '', 'Autoregistro: {HOST.HOST}',
        'Host: {HOST.HOST}\nIP: {HOST.IP}\nPorta: {HOST.PORT}'],
    ['INTERNAL', 'PROBLEM', 'Evento interno: {EVENT.NAME}',
        '{EVENT.NAME}\nHost: {HOST.NAME}\nInício: {EVENT.DATE} {EVENT.TIME}']
];

function q(s) {
    return "'" + String(s).replace(/'/g, "''") + "'";
}

function block(text, indent) {
    var pad = new Array(indent + 1).join(' ');
    return text.split('\n').map(function (l) { return l ? pad + l : ''; }).join('\n');
}

var out = [];
out.push('zabbix_export:');
out.push("  version: '6.0'");
out.push("  date: '2026-11-11T00:00:00Z'");
out.push('  media_types:');
out.push("    - name: 'WhatsApp (Hermes Agent)'");
out.push('      type: WEBHOOK');
out.push('      parameters:');
params.forEach(function (p) {
    out.push('        - name: ' + p[0]);
    out.push('          value: ' + q(p[1]));
});
out.push('      script: |');
out.push(block(script, 8));
out.push('      timeout: 30s');
out.push("      description: 'Envia alertas do Zabbix para WhatsApp (números ou grupos) via webhook do Hermes Agent (rota deliver_only). Assinado com HMAC-SHA256: o relógio do servidor Zabbix precisa estar sincronizado. Em \"Enviar para\" use o número com DDI+DDD (5511999998888) ou o JID do grupo (120363...@g.us). Vários destinos separados por vírgula.'");
out.push('      message_templates:');
templates.forEach(function (t) {
    out.push('        - event_source: ' + t[0]);
    if (t[1]) {
        out.push('          operation_mode: ' + t[1]);
    }
    out.push('          subject: ' + q(t[2]));
    out.push('          message: |');
    out.push(block(t[3], 12));
});

fs.writeFileSync(path.join(__dirname, 'whatsapp_hermes_mediatype.yaml'), out.join('\n') + '\n', 'utf8');
console.log('whatsapp_hermes_mediatype.yaml gerado.');
