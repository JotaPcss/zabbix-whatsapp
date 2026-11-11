// Teste local do webhook sem Zabbix: simula as funções do Zabbix (HttpRequest, hmac, sha256)
// e valida a assinatura exatamente como o Hermes faz.
// Uso: node test_webhook.js
// Para testar de verdade contra o Hermes, use o botão "Test" do tipo de mídia no Zabbix.

var fs = require('fs');
var path = require('path');
var assert = require('assert');
var crypto = require('crypto');

var code = fs.readFileSync(path.join(__dirname, 'whatsapp_hermes.js'), 'utf8');
var webhook = new Function('value', 'HttpRequest', 'Zabbix', 'hmac', 'sha256', code);

// Mesmas assinaturas das funções globais do Zabbix 6.0+ (retornam hex minúsculo).
function zbxHmac(type, key, data) { return crypto.createHmac(type, key).update(data, 'utf8').digest('hex'); }
function zbxSha256(data) { return crypto.createHash('sha256').update(data, 'utf8').digest('hex'); }

var SECRET = 'segredo-da-rota';

function run(params, statusCode) {
    var sent = [];
    function HttpRequest() { this.headers = {}; }
    HttpRequest.prototype.addHeader = function (h) {
        var i = h.indexOf(':');
        this.headers[h.substring(0, i).trim()] = h.substring(i + 1).trim();
    };
    HttpRequest.prototype.setProxy = function () {};
    HttpRequest.prototype.post = function (url, body) {
        sent.push({ url: url, headers: this.headers, raw: body, body: JSON.parse(body) });
        return statusCode && statusCode >= 300 ? '{"error":"x"}' : '{"status":"delivered","route":"zabbix-alert"}';
    };
    HttpRequest.prototype.getStatus = function () { return statusCode || 200; };
    var result = webhook(JSON.stringify(params), HttpRequest, { log: function () {} }, zbxHmac, zbxSha256);
    return { result: result, sent: sent };
}

// Verificação do lado do Hermes (esquema V2): HMAC-SHA256 hex de "<timestamp>.<corpo>".
function hermesAccepts(req) {
    var ts = req.headers['X-Webhook-Timestamp'];
    var expected = crypto.createHmac('sha256', SECRET).update(ts + '.' + req.raw, 'utf8').digest('hex');
    var fresh = Math.abs(Date.now() / 1000 - Number(ts)) <= 300;
    return fresh && expected === req.headers['X-Webhook-Signature-V2'];
}

var base = {
    hermes_url: 'http://hermes.local:8644/',
    hermes_route: 'zabbix-alert',
    hermes_secret: SECRET,
    dm_suffix: '@s.whatsapp.net',
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
    event_update_date: '{EVENT.UPDATE.DATE}',
    event_update_time: '{EVENT.UPDATE.TIME}',
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

// 1. Problema, dois destinos, assinatura válida
var r = run(base);
assert.strictEqual(r.result, 'OK');
assert.strictEqual(r.sent.length, 2);
assert.strictEqual(r.sent[0].url, 'http://hermes.local:8644/webhooks/zabbix-alert');
assert.strictEqual(r.sent[0].body.chat_id, '120363025555555555@g.us');
assert.strictEqual(r.sent[1].body.chat_id, '5511999998888@s.whatsapp.net');
assert.ok(hermesAccepts(r.sent[0]) && hermesAccepts(r.sent[1]), 'assinatura V2 inválida');
assert.ok(r.sent[0].body.text.indexOf('*PROBLEMA* | Alta') !== -1);
assert.ok(r.sent[0].body.text.indexOf('{EVENT') === -1, 'macro não resolvida vazou');
console.log('--- PROBLEMA ---\n' + r.sent[0].body.text + '\n');

// 2. Assinatura com segredo errado é recusada pelo Hermes
var bad = run(merge(base, { hermes_secret: 'outro' }));
assert.ok(!hermesAccepts(bad.sent[0]), 'segredo errado foi aceito');

// 3. ID de requisição: estável num reenvio, diferente por destino e por tipo de notificação
var again = run(base);
assert.strictEqual(again.sent[0].headers['X-Request-ID'], r.sent[0].headers['X-Request-ID']);
assert.notStrictEqual(r.sent[0].headers['X-Request-ID'], r.sent[1].headers['X-Request-ID']);
var rec = run(merge(base, {
    event_value: '0', event_recovery_date: '2026.11.11', event_recovery_time: '10:27:40', event_duration: '12m 40s'
}));
assert.notStrictEqual(rec.sent[0].headers['X-Request-ID'], r.sent[0].headers['X-Request-ID']);
assert.ok(rec.sent[0].body.text.indexOf('✅ *RESOLVIDO*') === 0);
assert.ok(rec.sent[0].body.text.indexOf('*Duração:* 12m 40s') !== -1);
console.log('--- RESOLVIDO ---\n' + rec.sent[0].body.text + '\n');

// 4. Atualizações diferentes do mesmo evento não são tratadas como duplicadas
var up1 = run(merge(base, { event_update_status: '1', event_update_date: '2026.11.11', event_update_time: '10:20:00',
    event_update_user: 'João Pedro', event_update_action: 'reconheceu', event_update_message: 'Verificando processo java' }));
var up2 = run(merge(base, { event_update_status: '1', event_update_date: '2026.11.11', event_update_time: '10:25:00',
    event_update_user: 'João Pedro', event_update_action: 'comentou', event_update_message: 'Reiniciado' }));
assert.notStrictEqual(up1.sent[0].headers['X-Request-ID'], up2.sent[0].headers['X-Request-ID']);
assert.ok(up1.sent[0].body.text.indexOf('🔄 *ATUALIZAÇÃO*') === 0);
console.log('--- ATUALIZAÇÃO ---\n' + up1.sent[0].body.text + '\n');

// 5. Sem tag de cliente: linha omitida
r = run(merge(base, { client_name: '{EVENT.TAGS.cliente}' }));
assert.ok(r.sent[0].body.text.indexOf('Cliente') === -1);

// 6. Evento de discovery usa o template do Zabbix
r = run(merge(base, { event_source: '1' }));
assert.strictEqual(r.sent[0].body.text, '*Problema: Uso de CPU*\nmensagem do template');

// 7. Erros HTTP viram exceção com dica (Zabbix marca o alerta como falho e tenta de novo)
assert.throws(function () { run(base, 401); }, /HTTP 401.*hermes_secret/);
assert.throws(function () { run(base, 429); }, /rate_limit/);

// 8. Validações de configuração
assert.throws(function () { run(merge(base, { send_to: '  ' })); }, /Nenhum destino/);
assert.throws(function () { run(merge(base, { hermes_secret: '' })); }, /hermes_secret/);

console.log('Todos os testes passaram.');
