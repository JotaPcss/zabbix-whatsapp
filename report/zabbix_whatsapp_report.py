#!/usr/bin/env python3
"""
Relatórios periódicos do Zabbix enviados por WhatsApp (Evolution API v2).

Para cada cliente do arquivo de configuração:
  1. consulta a API do Zabbix (6.0+) do período (diário, semanal, mensal ou datas livres);
  2. monta um resumo em texto + um PDF com problemas, disponibilidade e top hosts/triggers;
  3. envia texto e PDF para os destinos (números ou grupos) via Evolution API.

Exemplos:
  ./zabbix_whatsapp_report.py -c config.yaml --period weekly
  ./zabbix_whatsapp_report.py -c config.yaml --period monthly --client "Acme Ltda" --dry-run
  ./zabbix_whatsapp_report.py -c config.yaml --start 2026-10-01 --end 2026-10-15
  ./zabbix_whatsapp_report.py -c config.yaml --list-groups
  ./zabbix_whatsapp_report.py --demo --dry-run          # PDF de exemplo, sem Zabbix
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import logging
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
import yaml

log = logging.getLogger("zbx-report")

SEVERITIES = {
    0: ("Não classificada", "#97AAB3"),
    1: ("Informação", "#7499FF"),
    2: ("Atenção", "#FFC859"),
    3: ("Média", "#FFA059"),
    4: ("Alta", "#E97659"),
    5: ("Desastre", "#E45959"),
}
PERIOD_LABEL = {"daily": "Diário", "weekly": "Semanal", "monthly": "Mensal", "custom": "Personalizado"}


# --------------------------------------------------------------------------- Zabbix API

class ZabbixError(RuntimeError):
    pass


class ZabbixAPI:
    """Cliente JSON-RPC mínimo, compatível com Zabbix 6.0 até 7.x.

    - 6.0/6.2: autenticação no campo "auth" do corpo.
    - 6.4+:    cabeçalho "Authorization: Bearer" (o campo "auth" foi removido no 7.2).
    """

    def __init__(self, url: str, token: str | None = None, user: str | None = None,
                 password: str | None = None, verify_ssl: bool = True, timeout: int = 60):
        url = url.rstrip("/")
        self.url = url if url.endswith("api_jsonrpc.php") else url + "/api_jsonrpc.php"
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.timeout = timeout
        self.auth: str | None = None
        self._logged_in = False
        self._id = 0

        raw = self.call("apiinfo.version", {}, auth=False)
        self.version_str = raw
        self.version = tuple(int(x) for x in raw.split(".")[:2])

        if token:
            self.auth = token
        elif user and password:
            key = "username" if self.version >= (5, 4) else "user"
            self.auth = self.call("user.login", {key: user, "password": password}, auth=False)
            self._logged_in = True
        else:
            raise ZabbixError("Informe zabbix_token ou zabbix_user/zabbix_password")

    def call(self, method: str, params, auth: bool = True):
        self._id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self._id}
        headers = {"Content-Type": "application/json-rpc"}
        if auth and self.auth:
            if self.version >= (6, 4):
                headers["Authorization"] = f"Bearer {self.auth}"
            else:
                payload["auth"] = self.auth
        resp = self.session.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise ZabbixError(f"{method}: {err.get('message')} {err.get('data', '')}".strip())
        return data["result"]

    def close(self):
        if self._logged_in:
            try:
                self.call("user.logout", [])
            except Exception:  # noqa: BLE001 - logout é melhor esforço
                pass


# --------------------------------------------------------------------------- Evolution API

def normalize_destination(dest: str) -> str:
    dest = dest.strip()
    return dest if "@" in dest else re.sub(r"\D", "", dest)


class Evolution:
    def __init__(self, url: str, instance: str, apikey: str, verify_ssl: bool = True, timeout: int = 120):
        self.base = url.rstrip("/")
        self.instance = quote(instance, safe="")
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update({"apikey": apikey, "Content-Type": "application/json"})
        self.timeout = timeout

    def _post(self, path: str, body: dict):
        resp = self.session.post(f"{self.base}{path}/{self.instance}", json=body, timeout=self.timeout)
        if resp.status_code >= 300:
            raise RuntimeError(f"Evolution {path} HTTP {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    def send_text(self, to: str, text: str):
        return self._post("/message/sendText", {"number": to, "text": text, "linkPreview": False})

    def send_document(self, to: str, file_path: Path, caption: str = ""):
        media = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return self._post("/message/sendMedia", {
            "number": to,
            "mediatype": "document",
            "mimetype": "application/pdf",
            "caption": caption,
            "media": media,
            "fileName": file_path.name,
        })

    def list_groups(self):
        resp = self.session.get(f"{self.base}/group/fetchAllGroups/{self.instance}",
                                params={"getParticipants": "false"}, timeout=self.timeout)
        if resp.status_code >= 300:
            raise RuntimeError(f"Evolution fetchAllGroups HTTP {resp.status_code}: {resp.text[:500]}")
        return resp.json()


# --------------------------------------------------------------------------- Período

def period_window(period: str, tz: ZoneInfo, start: str | None = None, end: str | None = None,
                  now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    """Retorna (início, fim) do período fechado anterior. Fim é exclusivo."""
    if period == "custom":
        s = dt.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=tz)
        e = dt.datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=tz) + dt.timedelta(days=1)
        if e <= s:
            raise ValueError("--end deve ser igual ou posterior a --start")
        return s, e

    now = now or dt.datetime.now(tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "daily":
        return today - dt.timedelta(days=1), today
    if period == "weekly":  # segunda a domingo da semana passada
        s = today - dt.timedelta(days=today.weekday() + 7)
        return s, s + dt.timedelta(days=7)
    if period == "monthly":
        first = today.replace(day=1)
        return (first - dt.timedelta(days=1)).replace(day=1), first
    raise ValueError(f"Período desconhecido: {period}")


# --------------------------------------------------------------------------- Coleta

def chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def merged_length(intervals: list[tuple[int, int]]) -> int:
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def collect(api: ZabbixAPI, client: dict, start: dt.datetime, end: dt.datetime) -> dict:
    ts_from, ts_till = int(start.timestamp()), int(end.timestamp())
    now_ts = int(dt.datetime.now(dt.timezone.utc).timestamp())
    min_sev = int(client.get("min_severity", 2))
    avail_sev = int(client.get("availability_severity", 4))
    severities = list(range(min_sev, 6))

    groupids = None
    if client.get("host_groups"):
        groups = api.call("hostgroup.get", {"output": ["groupid", "name"],
                                            "filter": {"name": client["host_groups"]}})
        found = {g["name"] for g in groups}
        missing = set(client["host_groups"]) - found
        if missing:
            log.warning("[%s] grupos não encontrados no Zabbix: %s", client["name"], ", ".join(sorted(missing)))
        groupids = [g["groupid"] for g in groups]
        if not groupids:
            raise ZabbixError("Nenhum dos host_groups configurados existe no Zabbix")

    def scoped(params: dict) -> dict:
        if groupids:
            params["groupids"] = groupids
        return params

    hosts = api.call("host.get", scoped({
        "output": ["hostid", "name"],
        "selectInterfaces": ["available", "type"],
        "monitored_hosts": True,
    }))
    hosts_down = sorted(h["name"] for h in hosts
                        if any(str(i.get("available")) == "2" for i in h.get("interfaces", [])))

    events = api.call("event.get", scoped({
        "output": ["eventid", "clock", "name", "severity", "r_eventid", "objectid"],
        "source": 0, "object": 0, "value": 1,
        "time_from": ts_from, "time_till": ts_till - 1,
        "severities": severities,
        "selectHosts": ["hostid", "name"],
        "sortfield": ["clock"], "sortorder": "ASC",
    }))

    r_ids = [e["r_eventid"] for e in events if e.get("r_eventid", "0") != "0"]
    recovery_clock: dict[str, int] = {}
    for part in chunks(r_ids, 500):
        for r in api.call("event.get", {"output": ["eventid", "clock"], "eventids": part}):
            recovery_clock[r["eventid"]] = int(r["clock"])

    # Problemas em aberto agora (inclui os que começaram antes do período).
    open_problems = api.call("problem.get", scoped({
        "output": ["eventid", "clock", "name", "severity", "acknowledged"],
        "severities": severities,
        "sortfield": ["eventid"], "sortorder": "DESC",
    }))
    open_hosts: dict[str, list[str]] = {}
    for part in chunks([p["eventid"] for p in open_problems], 500):
        for e in api.call("event.get", {"output": ["eventid"], "eventids": part,
                                        "selectHosts": ["name"]}):
            open_hosts[e["eventid"]] = [h["name"] for h in e.get("hosts", [])]

    rows = []
    seen = set()
    for e in events:
        seen.add(e["eventid"])
        rid = e.get("r_eventid", "0")
        rows.append({
            "eventid": e["eventid"],
            "clock": int(e["clock"]),
            "end": recovery_clock.get(rid) if rid != "0" else None,
            "name": e["name"],
            "severity": int(e["severity"]),
            "hosts": [h["name"] for h in e.get("hosts", [])],
            "in_period": True,
        })
    for p in open_problems:
        if p["eventid"] not in seen and int(p["clock"]) < ts_from:
            rows.append({
                "eventid": p["eventid"], "clock": int(p["clock"]), "end": None, "name": p["name"],
                "severity": int(p["severity"]), "hosts": open_hosts.get(p["eventid"], []), "in_period": False,
            })

    open_rows = [{
        "clock": int(p["clock"]), "name": p["name"], "severity": int(p["severity"]),
        "hosts": open_hosts.get(p["eventid"], []), "acknowledged": p.get("acknowledged") == "1",
    } for p in open_problems]

    return {
        "hosts": [h["name"] for h in hosts],
        "hosts_down": hosts_down,
        "rows": rows,
        "open": open_rows,
        "ts_from": ts_from,
        "ts_till": ts_till,
        "now": now_ts,
        "avail_severity": avail_sev,
        "min_severity": min_sev,
        "zabbix_version": api.version_str,
    }


def demo_data(start: dt.datetime, end: dt.datetime) -> dict:
    """Dados fictícios para testar o layout sem acesso a um Zabbix."""
    rnd = random.Random(42)
    ts_from, ts_till = int(start.timestamp()), int(end.timestamp())
    hosts = [f"srv-{n}" for n in ("web01", "web02", "db01", "db02", "app01", "app02", "proxy01",
                                   "backup01", "mail01", "dns01", "nfs01", "k8s-node1", "k8s-node2")]
    triggers = [
        ("Uso de CPU acima de 90% por 5m", 3), ("Pouco espaço em disco em /var (< 10%)", 4),
        ("Memória disponível abaixo de 10%", 3), ("Serviço nginx parado", 4),
        ("Load average alto", 2), ("Zabbix agent indisponível", 4), ("Replicação MySQL atrasada", 3),
        ("Host não responde a ICMP", 5), ("Certificado SSL expira em menos de 15 dias", 2),
        ("Muitos processos zumbis", 2),
    ]
    rows = []
    for i in range(rnd.randint(60, 110)):
        name, sev = rnd.choice(triggers)
        clock = rnd.randint(ts_from, ts_till - 60)
        dur = int(rnd.expovariate(1 / 1800)) + 60
        end_c = clock + dur
        rows.append({"eventid": str(1000 + i), "clock": clock,
                     "end": end_c if end_c < ts_till or rnd.random() < .5 else None,
                     "name": name, "severity": sev, "hosts": [rnd.choice(hosts)], "in_period": True})
    for r in sorted(rows, key=lambda r: -r["clock"])[:4]:  # garante alguns problemas em aberto
        r["end"] = None
    opens = [{"clock": r["clock"], "name": r["name"], "severity": r["severity"], "hosts": r["hosts"],
              "acknowledged": rnd.random() < .5} for r in rows if r["end"] is None][:8]
    return {"hosts": hosts, "hosts_down": ["srv-backup01"], "rows": rows, "open": opens,
            "ts_from": ts_from, "ts_till": ts_till, "now": ts_till, "avail_severity": 4,
            "min_severity": 2, "zabbix_version": "demo"}


# --------------------------------------------------------------------------- Métricas

def pct(value: float, decimals: int = 2) -> str:
    """Percentual no formato brasileiro: 99,81%."""
    return f"{value:.{decimals}f}".replace(".", ",") + "%"


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}min")
    return " ".join(parts) or "0min"


def analyze(data: dict, tz: ZoneInfo) -> dict:
    ts_from, ts_till = data["ts_from"], data["ts_till"]
    horizon = min(data["now"], ts_till)
    period_len = max(ts_till - ts_from, 1)

    in_period = [r for r in data["rows"] if r["in_period"]]
    sev_count = Counter(r["severity"] for r in in_period)

    resolved = [r["end"] - r["clock"] for r in in_period if r["end"] is not None]
    mttr = sum(resolved) / len(resolved) if resolved else 0

    by_trigger: dict[str, dict] = defaultdict(lambda: {"count": 0, "severity": 0, "duration": 0})
    by_host = Counter()
    per_day = Counter()
    down_intervals: dict[str, list] = defaultdict(list)

    for r in data["rows"]:
        s = max(r["clock"], ts_from)
        e = min(r["end"] if r["end"] is not None else horizon, horizon)
        dur = max(e - s, 0)
        if r["in_period"]:
            t = by_trigger[r["name"]]
            t["count"] += 1
            t["severity"] = max(t["severity"], r["severity"])
            t["duration"] += dur
            for h in r["hosts"]:
                by_host[h] += 1
            per_day[dt.datetime.fromtimestamp(r["clock"], tz).date()] += 1
        if r["severity"] >= data["avail_severity"] and dur > 0:
            for h in r["hosts"]:
                down_intervals[h].append((s, e))

    availability = {}
    for h in data["hosts"]:
        down = merged_length(down_intervals.get(h, []))
        availability[h] = (100.0 * (1 - down / period_len), down)
    avg_avail = sum(a for a, _ in availability.values()) / len(availability) if availability else 100.0

    days = []
    d = dt.datetime.fromtimestamp(ts_from, tz).date()
    last = dt.datetime.fromtimestamp(ts_till - 1, tz).date()
    while d <= last:
        days.append((d, per_day.get(d, 0)))
        d += dt.timedelta(days=1)

    return {
        "total": len(in_period),
        "sev_count": sev_count,
        "resolved": len(resolved),
        "mttr": mttr,
        "top_triggers": sorted(by_trigger.items(), key=lambda kv: (-kv[1]["count"], -kv[1]["duration"]))[:10],
        "top_hosts": by_host.most_common(10),
        "availability": sorted(availability.items(), key=lambda kv: kv[1][0]),
        "avg_availability": avg_avail,
        "days": days,
        "hosts_total": len(data["hosts"]),
        "hosts_down": data["hosts_down"],
        "open": sorted(data["open"], key=lambda o: (-o["severity"], o["clock"])),
    }


# --------------------------------------------------------------------------- Saídas

def build_text(client: dict, period: str, start: dt.datetime, end: dt.datetime, m: dict) -> str:
    last_day = end - dt.timedelta(seconds=1)
    rng = (start.strftime("%d/%m/%Y") if start.date() == last_day.date()
           else f"{start:%d/%m/%Y} a {last_day:%d/%m/%Y}")
    lines = [
        f"📊 *Relatório {PERIOD_LABEL[period]} — {client['name']}*",
        f"🗓️ {rng}",
        "",
        f"🖥️ *Hosts monitorados:* {m['hosts_total']}",
        f"📈 *Disponibilidade média:* {pct(m['avg_availability'])}",
        f"⚠️ *Problemas no período:* {m['total']}",
    ]
    sev_line = " · ".join(f"{SEVERITIES[s][0]}: {m['sev_count'][s]}" for s in range(5, -1, -1) if m["sev_count"][s])
    if sev_line:
        lines.append(f"   {sev_line}")
    if m["resolved"]:
        lines.append(f"⏱️ *Tempo médio de resolução:* {fmt_duration(m['mttr'])}")
    lines.append(f"🔴 *Em aberto agora:* {len(m['open'])}")
    if m["hosts_down"]:
        lines.append(f"🚫 *Hosts indisponíveis:* {', '.join(m['hosts_down'][:5])}"
                     + (f" (+{len(m['hosts_down']) - 5})" if len(m["hosts_down"]) > 5 else ""))
    if m["top_triggers"]:
        lines += ["", "*Mais recorrentes:*"]
        for name, t in m["top_triggers"][:3]:
            lines.append(f"• {name} — {t['count']}x")
    lines += ["", "_Detalhes no PDF em anexo._"]
    return "\n".join(lines)


def build_pdf(path: Path, client: dict, period: str, start: dt.datetime, end: dt.datetime,
              m: dict, tz: ZoneInfo, company: str):
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    ink, muted, line_c, accent = (colors.HexColor(c) for c in ("#1F2937", "#6B7280", "#E5E7EB", "#2563EB"))
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, textColor=ink, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=ink, spaceBefore=14, spaceAfter=6)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.5, textColor=muted)
    cell = ParagraphStyle("cell", parent=ss["Normal"], fontSize=8.5, leading=10.5, textColor=ink)

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def table(data, widths, header=True):
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
        style = [
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("TEXTCOLOR", (0, 0), (-1, -1), ink),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, line_c),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if header:
            style += [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                      ("TEXTCOLOR", (0, 0), (-1, 0), muted),
                      ("LINEBELOW", (0, 0), (-1, 0), 0.8, ink)]
        t.setStyle(TableStyle(style))
        return t

    def sev_badge(sev: int):
        # "•" existe na codificação WinAnsi da Helvetica embutida; "■"/"●" não.
        return Paragraph(f'<font color="{SEVERITIES[sev][1]}"><b>•</b></font> {SEVERITIES[sev][0]}', cell)

    last_day = end - dt.timedelta(seconds=1)
    story = [
        Paragraph(f"Relatório {PERIOD_LABEL[period]} de Monitoramento", h1),
        Paragraph(f"<b>{esc(client['name'])}</b> · {start:%d/%m/%Y} a {last_day:%d/%m/%Y}", ss["Normal"]),
        Paragraph(f"Gerado em {dt.datetime.now(tz):%d/%m/%Y %H:%M} por {esc(company)}", small),
        Spacer(1, 12),
    ]

    # Indicadores
    kpis = [
        ("Hosts monitorados", str(m["hosts_total"])),
        ("Disponibilidade média", pct(m["avg_availability"])),
        ("Problemas no período", str(m["total"])),
        ("Tempo médio de resolução", fmt_duration(m["mttr"]) if m["resolved"] else "—"),
        ("Em aberto agora", str(len(m["open"]))),
    ]
    big = ParagraphStyle("big", parent=ss["Normal"], fontSize=16, leading=19, textColor=ink, fontName="Helvetica-Bold")
    kt = Table([[Paragraph(v, big) for _, v in kpis], [Paragraph(k, small) for k, _ in kpis]],
               colWidths=[3.4 * cm] * 5)
    kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, line_c), ("INNERGRID", (0, 0), (-1, -1), 0, colors.white),
                            ("LINEAFTER", (0, 0), (-2, -1), 0.6, line_c), ("VALIGN", (0, 1), (-1, 1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(kt)

    # Severidade + gráfico por dia
    story.append(Paragraph("Problemas por severidade", h2))
    sev_rows = [["Severidade", "Ocorrências"]] + [
        [sev_badge(s), str(m["sev_count"][s])] for s in range(5, -1, -1) if m["sev_count"][s]]
    if len(sev_rows) == 1:
        sev_rows.append(["Nenhum problema no período", ""])
    story.append(table(sev_rows, [8 * cm, 3 * cm]))

    if len(m["days"]) > 1:
        story.append(Paragraph("Problemas por dia", h2))
        values = [c for _, c in m["days"]]
        dr = Drawing(17.5 * cm, 5.2 * cm)
        bc = VerticalBarChart()
        bc.x, bc.y, bc.width, bc.height = 30, 28, 17.5 * cm - 40, 5.2 * cm - 40
        bc.data = [values]
        bc.bars[0].fillColor = accent
        bc.bars[0].strokeColor = None
        bc.valueAxis.valueMin = 0
        bc.valueAxis.valueStep = max(1, -(-max(values) // 5))  # só inteiros no eixo
        bc.valueAxis.valueMax = max(max(values), 1) * 1.15
        bc.valueAxis.labels.fontSize = 7
        bc.valueAxis.strokeColor = line_c
        bc.valueAxis.gridStrokeColor = line_c
        bc.valueAxis.visibleGrid = True
        step = max(1, len(values) // 15)
        bc.categoryAxis.categoryNames = [d.strftime("%d/%m") if i % step == 0 else "" for i, (d, _) in enumerate(m["days"])]
        bc.categoryAxis.labels.fontSize = 7
        bc.categoryAxis.strokeColor = line_c
        dr.add(bc)
        story.append(dr)

    # Top triggers
    if m["top_triggers"]:
        rows = [["Problema", "Severidade", "Ocorr.", "Tempo total"]]
        for name, t in m["top_triggers"]:
            rows.append([Paragraph(esc(name), cell), sev_badge(t["severity"]), str(t["count"]), fmt_duration(t["duration"])])
        story += [Paragraph("Problemas mais recorrentes", h2), table(rows, [8.6 * cm, 3.4 * cm, 1.6 * cm, 3.0 * cm])]

    # Top hosts
    if m["top_hosts"]:
        rows = [["Host", "Problemas"]] + [[Paragraph(esc(h), cell), str(c)] for h, c in m["top_hosts"]]
        story += [Paragraph("Hosts com mais problemas", h2), table(rows, [11 * cm, 3 * cm])]

    # Disponibilidade
    sev_name = SEVERITIES[min(5, max(0, int(client.get("availability_severity", 4))))][0]
    rows = [["Host", "Disponibilidade", "Tempo indisponível"]]
    for h, (avail, down) in m["availability"][:25]:
        color = "#16A34A" if avail >= 99.9 else "#D97706" if avail >= 99 else "#DC2626"
        rows.append([Paragraph(esc(h), cell), Paragraph(f'<font color="{color}"><b>{pct(avail, 3)}</b></font>', cell),
                     fmt_duration(down) if down else "—"])
    story.append(KeepTogether([
        Paragraph("Disponibilidade por host", h2),
        Paragraph(f"Considera como indisponibilidade problemas de severidade {sev_name} ou superior. "
                  f"Exibindo os {min(25, len(m['availability']))} hosts com menor disponibilidade.", small),
        Spacer(1, 4),
        table(rows, [9 * cm, 3.5 * cm, 4 * cm]),
    ]))

    # Em aberto
    story.append(Paragraph("Problemas em aberto no momento da geração", h2))
    if m["open"]:
        rows = [["Início", "Host", "Problema", "Severidade", "Reconh."]]
        for o in m["open"][:30]:
            rows.append([dt.datetime.fromtimestamp(o["clock"], tz).strftime("%d/%m %H:%M"),
                         Paragraph(esc(", ".join(o["hosts"])), cell), Paragraph(esc(o["name"]), cell),
                         sev_badge(o["severity"]), "Sim" if o["acknowledged"] else "Não"])
        story.append(table(rows, [2.2 * cm, 3.4 * cm, 6.6 * cm, 3.0 * cm, 1.5 * cm]))
    else:
        story.append(Paragraph("Nenhum problema em aberto.", cell))

    if m["hosts_down"]:
        story += [Paragraph("Hosts com interface indisponível", h2),
                  Paragraph(esc(", ".join(m["hosts_down"])), cell)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(2 * cm, 1.2 * cm, f"{company} · {client['name']}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.8 * cm, bottomMargin=2 * cm,
                            title=f"Relatório {PERIOD_LABEL[period]} - {client['name']}", author=company)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


# --------------------------------------------------------------------------- Main

def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")  # "Demonstração" → "Demonstracao"
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower() or "cliente"


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if not cfg.get("clients"):
        raise SystemExit("Config sem 'clients'.")
    return cfg


def run_client(client: dict, cfg: dict, args, period: str, evo: Evolution | None) -> None:
    defaults = cfg.get("defaults", {})
    client = {**defaults, **client}
    tz = ZoneInfo(client.get("timezone", "America/Sao_Paulo"))
    start, end = period_window(period, tz, args.start, args.end)
    log.info("[%s] período %s → %s", client["name"], start.isoformat(), end.isoformat())

    if args.demo:
        data = demo_data(start, end)
    else:
        api = ZabbixAPI(client["zabbix_url"], token=client.get("zabbix_token"), user=client.get("zabbix_user"),
                        password=client.get("zabbix_password"), verify_ssl=client.get("verify_ssl", True))
        try:
            log.info("[%s] Zabbix %s", client["name"], api.version_str)
            data = collect(api, client, start, end)
        finally:
            api.close()

    metrics = analyze(data, tz)
    text = build_text(client, period, start, end, metrics)

    out_dir = Path(args.output_dir or cfg.get("output_dir", "./relatorios"))
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"relatorio-{slug(client['name'])}-{period}-{start:%Y%m%d}.pdf"
    company = cfg.get("company_name", "Suporte Linux")
    build_pdf(pdf_path, client, period, start, end, metrics, tz, company)
    log.info("[%s] PDF gerado: %s", client["name"], pdf_path)

    if args.dry_run or evo is None:
        print(f"\n===== {client['name']} (dry-run, nada enviado) =====\n{text}\nPDF: {pdf_path}\n")
        return

    send_to = client.get("send_to") or []
    if isinstance(send_to, str):
        send_to = [send_to]
    if not send_to:
        raise RuntimeError("cliente sem 'send_to'")
    for dest in map(normalize_destination, send_to):
        evo.send_text(dest, text)
        if client.get("attach_pdf", True):
            evo.send_document(dest, pdf_path, caption=pdf_path.name)
        log.info("[%s] enviado para %s", client["name"], dest)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Relatórios do Zabbix por WhatsApp (Evolution API)")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("--period", choices=["daily", "weekly", "monthly"], default=None)
    p.add_argument("--start", help="Data inicial YYYY-MM-DD (período personalizado)")
    p.add_argument("--end", help="Data final YYYY-MM-DD, inclusiva (período personalizado)")
    p.add_argument("--client", action="append", help="Só este cliente (pode repetir)")
    p.add_argument("--dry-run", action="store_true", help="Gera texto e PDF mas não envia")
    p.add_argument("--demo", action="store_true", help="Usa dados fictícios em vez do Zabbix")
    p.add_argument("--output-dir")
    p.add_argument("--list-groups", action="store_true", help="Lista grupos do WhatsApp e seus JIDs")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if bool(args.start) != bool(args.end):
        p.error("--start e --end devem ser usados juntos")
    if args.start and args.period:
        p.error("use --period OU --start/--end")
    period = "custom" if args.start else (args.period or "daily")

    if args.demo:
        args.dry_run = True  # dados fictícios nunca são enviados a clientes
    if args.demo and not Path(args.config).exists():
        cfg = {"company_name": "Suporte Linux (demo)", "clients": [{"name": "Cliente Demonstração"}]}
    else:
        cfg = load_config(args.config)

    evo = None
    if not args.dry_run:
        e = cfg.get("evolution") or {}
        if not all(e.get(k) for k in ("url", "instance", "apikey")):
            raise SystemExit("Config 'evolution' precisa de url, instance e apikey.")
        evo = Evolution(e["url"], e["instance"], e["apikey"], verify_ssl=e.get("verify_ssl", True))

    if args.list_groups:
        if evo is None:
            raise SystemExit("--list-groups precisa da seção 'evolution' (e sem --dry-run).")
        for g in sorted(evo.list_groups(), key=lambda g: g.get("subject", "")):
            print(f"{g.get('id')}\t{g.get('subject')}")
        return 0

    clients = cfg["clients"]
    if args.client:
        wanted = {c.lower() for c in args.client}
        clients = [c for c in clients if c["name"].lower() in wanted]
        if not clients:
            raise SystemExit("Nenhum cliente com esse nome no config.")
    elif period != "custom":
        clients = [c for c in clients
                   if period in (c.get("reports") or cfg.get("defaults", {}).get("reports") or ["daily", "weekly", "monthly"])]

    failures = 0
    for client in clients:
        try:
            run_client(client, cfg, args, period, evo)
        except Exception as exc:  # noqa: BLE001 - um cliente com erro não pode parar os outros
            failures += 1
            log.error("[%s] falhou: %s", client.get("name"), exc, exc_info=args.verbose)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
