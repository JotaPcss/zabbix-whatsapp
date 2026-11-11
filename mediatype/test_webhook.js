// Teste local do webhook sem Zabbix: simula HttpRequest/Zabbix e imprime as mensagens geradas.
// Uso: node test_webhook.js
// Para enviar de verdade a uma Evolution API, use o botão "Testar" do tipo de mídia no Zabbix.

var fs = require('fs');
var path = require('path');
var assert = require('assert');

var code = fs.readFileSync(path.join(__dirname, 'whatsapp_evolution.js'), 'utf8');
var webhook = new Function('value', 'HttpRequest', 'Zabbix', code);

function run(params, statusCode) {
    var sent = [];
    function HttpRequest() { this.headers = []; }
    HttpRequest.prototype.addHeader = function (h) { this.headers.push(h); };
    HttpRequest.prototype.setProxy = function () {};
    HttpRequest.prototype.post = function (url, body) {
        sent.push({ url: url, headers: this.headers, body: JSON.parse(body) });
        return statusCode && statusCode >= 300 ? '{"response":{"message":["número inválido"]}}' : '{"key":{}}';
    };
    HttpRequest.prototype.getStatus = function () { return statusCode || 201; };
    var Zabbix = { log: function () {} };
    var result = webhook(JSON.stringify(params), HttpRequest, Zabbix);
    return { result: result, sent: sent };
}

var base = {
    evolution_url: 'http://evo:8080/',
    evolution_instance: 'zabbix',
    evolution_apikey: 'segredo',
    send_to: '120363025555555555@g.us, +55 (11) 99999-8888',
    use_default_format: 'true',
    zabbix_url: 'https://zabbix.exemplo.com.br',
    event_source: '0',
    event_id: '12345',
    trigger_id: '678',
    event_name: 'Uso de CPU acima de 90% por 5m',
    event_nseverity: '4',
    host_name: 'web01',
    host_ip: '10.0.0.10',
    event_opdata: 'CPU: 97.3 %',
    event_date: '2026.11.11',
    event_time: '10:15:00',
    client_name: 'Acme Ltda',
    event_value: '1',
    event_update_status: '0',
    event_recovery_date: '{EVENT.RECOVERY.DATE}',
    event_recovery_time: '{EVENT.RECOVERY.TIME}',
    event_duration: '{EVENT.DURATION}',
    alert_subject: 'Problema: Uso de CPU',
    alert_message: 'mensagem do template'
};

function merge(a, b) {
    var o = {}, k;
    for (k in a) { o[k] = a[k]; }
    for (k in b) { o[k] = b[k]; }
    return o;
}

// 1. Problema, dois destinos
var r = run(base);
assert.strictEqual(r.result, 'OK');
assert.strictEqual(r.sent.length, 2);
assert.strictEqual(r.sent[0].url, 'http://evo:8080/message/sendText/zabbix');
assert.strictEqual(r.sent[0].body.number, '120363025555555555@g.us');
assert.strictEqual(r.sent[1].body.number, '5511999998888');
assert.ok(r.sent[0].headers.indexOf('apikey: segredo') !== -1);
assert.ok(r.sent[0].body.text.indexOf('*PROBLEMA* | Alta') !== -1);
assert.ok(r.sent[0].body.text.indexOf('{EVENT') === -1, 'macro não resolvida vazou');
console.log('--- PROBLEMA ---\n' + r.sent[0].body.text + '\n');

// 2. Recuperação
r = run(merge(base, {
    event_value: '0', event_recovery_date: '2026.11.11', event_recovery_time: '10:27:40', event_duration: '12m 40s'
}));
assert.ok(r.sent[0].body.text.indexOf('✅ *RESOLVIDO*') === 0);
assert.ok(r.sent[0].body.text.indexOf('*Duração:* 12m 40s') !== -1);
console.log('--- RESOLVIDO ---\n' + r.sent[0].body.text + '\n');

// 3. Atualização (reconhecimento)
r = run(merge(base, {
    event_update_status: '1', event_update_user: 'João Pedro', event_update_action: 'reconheceu',
    event_update_message: 'Verificando processo java'
}));
assert.ok(r.sent[0].body.text.indexOf('🔄 *ATUALIZAÇÃO*') === 0);
console.log('--- ATUALIZAÇÃO ---\n' + r.sent[0].body.text + '\n');

// 4. Sem tag de cliente: linha omitida
r = run(merge(base, { client_name: '{EVENT.TAGS.cliente}' }));
assert.ok(r.sent[0].body.text.indexOf('Cliente') === -1);

// 5. Evento de discovery usa o template do Zabbix
r = run(merge(base, { event_source: '1' }));
assert.strictEqual(r.sent[0].body.text, '*Problema: Uso de CPU*\nmensagem do template');

// 6. Erro HTTP vira exceção (Zabbix marca o alerta como falho e tenta de novo)
assert.throws(function () { run(base, 400); }, /HTTP 400/);

// 7. Sem destino
assert.throws(function () { run(merge(base, { send_to: '  ' })); }, /Nenhum destino/);

// 8. Sem apikey
assert.throws(function () { run(merge(base, { evolution_apikey: '' })); }, /evolution_apikey/);

console.log('Todos os testes passaram.');
