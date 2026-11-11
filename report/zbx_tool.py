#!/usr/bin/env python3
"""
Ferramenta de linha de comando que o Hermes Agent usa (via skill "zabbix") para responder
perguntas no WhatsApp. Lê o mesmo config.yaml do gerador de relatórios.

Comandos:
  clientes                                  lista os clientes configurados
  problemas [--cliente X] [--min-sev N]     problemas em aberto (todos os clientes se omitido)
  host --cliente X NOME                     situação de um host (interfaces e problemas)
  relatorio --cliente X [--periodo P]       gera o relatório e imprime o texto + caminho do PDF
  reconhecer --cliente X EVENTID --mensagem "texto"
                                            reconhece um problema (só se allow_ack: true no cliente)

Exemplos:
  zbx_tool.py -c /opt/zabbix-whatsapp/config.yaml problemas --cliente "Acme Ltda"
  zbx_tool.py -c /opt/zabbix-whatsapp/config.yaml relatorio --cliente acme --periodo weekly
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zabbix_whatsapp_report as rep  # noqa: E402

SEV_NAME = {k: v[0] for k, v in rep.SEVERITIES.items()}


def age(clock: int) -> str:
    return rep.fmt_duration(dt.datetime.now(dt.timezone.utc).timestamp() - clock)


def open_problems(client: dict, min_sev: int) -> list[dict]:
    api = rep.open_zabbix(client)
    try:
        params = {
            "output": ["eventid", "clock", "name", "severity", "acknowledged"],
            "severities": list(range(min_sev, 6)),
            "sortfield": ["eventid"], "sortorder": "DESC",
        }
        if client.get("host_groups"):
            groups = api.call("hostgroup.get", {"output": ["groupid"], "filter": {"name": client["host_groups"]}})
            params["groupids"] = [g["groupid"] for g in groups] or ["0"]
        problems = api.call("problem.get", params)
        hosts = {}
        ids = [p["eventid"] for p in problems]
        for i in range(0, len(ids), 500):
            for e in api.call("event.get", {"output": ["eventid"], "eventids": ids[i:i + 500],
                                            "selectHosts": ["name"]}):
                hosts[e["eventid"]] = ", ".join(h["name"] for h in e.get("hosts", []))
    finally:
        api.close()
    rows = [{
        "cliente": client["name"], "eventid": p["eventid"], "host": hosts.get(p["eventid"], "?"),
        "problema": p["name"], "severidade": SEV_NAME.get(int(p["severity"]), p["severity"]),
        "sev": int(p["severity"]), "ha": age(int(p["clock"])), "reconhecido": p.get("acknowledged") == "1",
    } for p in problems]
    return sorted(rows, key=lambda r: (-r["sev"], r["eventid"]))


def cmd_clientes(cfg, args):
    out = [{"cliente": c["name"], "zabbix": c.get("zabbix_url"), "grupos": c.get("host_groups") or "todos"}
           for c in cfg["clients"]]
    if args.json:
        return out
    return "\n".join(f"- {c['cliente']} ({c['zabbix']})" for c in out)


def cmd_problemas(cfg, args):
    clients = [rep.find_client(cfg, args.cliente)] if args.cliente else \
        [{**cfg.get("defaults", {}), **c} for c in cfg["clients"]]
    rows, errors = [], []
    for c in clients:
        try:
            rows += open_problems(c, args.min_sev if args.min_sev is not None else int(c.get("min_severity", 2)))
        except Exception as exc:  # noqa: BLE001 - um Zabbix fora do ar não esconde os outros
            errors.append(f"{c['name']}: erro ao consultar o Zabbix ({exc})")
    if args.json:
        return {"problemas": rows, "erros": errors}
    if not rows and not errors:
        return "Nenhum problema em aberto."
    lines = [f"[{r['severidade']}] {r['cliente']} / {r['host']}: {r['problema']} "
             f"(há {r['ha']}, evento {r['eventid']}{', reconhecido' if r['reconhecido'] else ''})" for r in rows]
    return "\n".join(lines + errors)


def cmd_host(cfg, args):
    client = rep.find_client(cfg, args.cliente)
    api = rep.open_zabbix(client)
    try:
        hosts = api.call("host.get", {"output": ["hostid", "host", "name", "status"],
                                      "selectInterfaces": ["ip", "dns", "type", "available"],
                                      "search": {"name": args.nome}, "searchWildcardsEnabled": True,
                                      "limit": 5})
        if not hosts:
            return f"Nenhum host com nome parecido com {args.nome!r} em {client['name']}."
        result = []
        for h in hosts:
            probs = api.call("problem.get", {"output": ["eventid", "clock", "name", "severity", "acknowledged"],
                                             "hostids": [h["hostid"]], "sortfield": ["eventid"], "sortorder": "DESC"})
            avail = {"0": "desconhecida", "1": "disponível", "2": "INDISPONÍVEL"}
            result.append({
                "host": h["name"], "monitorado": h["status"] == "0",
                "interfaces": [f"{i.get('ip') or i.get('dns')}: {avail.get(str(i.get('available')), '?')}"
                               for i in h.get("interfaces", [])],
                "problemas": [f"[{SEV_NAME.get(int(p['severity']))}] {p['name']} (há {age(int(p['clock']))}, "
                              f"evento {p['eventid']})" for p in probs],
            })
    finally:
        api.close()
    if args.json:
        return result
    out = []
    for r in result:
        out.append(f"{r['host']} ({'monitorado' if r['monitorado'] else 'NÃO monitorado'})")
        out += [f"  interface {i}" for i in r["interfaces"]]
        out += [f"  {p}" for p in r["problemas"]] or ["  sem problemas em aberto"]
    return "\n".join(out)


def cmd_relatorio(cfg, args):
    client = rep.find_client(cfg, args.cliente)
    text, pdf = rep.generate(client, cfg, args.periodo, args.inicio, args.fim, args.output_dir, args.demo)
    if args.json:
        return {"texto": text, "pdf": str(pdf)}
    # O caminho absoluto sozinho na última linha faz o gateway do Hermes anexar o PDF na conversa.
    return f"{text}\n\n{pdf}"


def cmd_reconhecer(cfg, args):
    client = rep.find_client(cfg, args.cliente)
    if not client.get("allow_ack", False):
        raise SystemExit(f"Reconhecer pelo WhatsApp está desativado para {client['name']} "
                         f"(allow_ack: false no config).")
    api = rep.open_zabbix(client)
    try:
        # action 6 = 2 (reconhecer) + 4 (adicionar mensagem). Válido do Zabbix 6.0 ao 7.x.
        api.call("event.acknowledge", {"eventids": [args.eventid], "action": 6,
                                       "message": f"[WhatsApp] {args.mensagem}"})
    finally:
        api.close()
    return f"Evento {args.eventid} reconhecido em {client['name']} com a mensagem: {args.mensagem}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Consultas ao Zabbix para o Hermes Agent")
    p.add_argument("-c", "--config", default="/opt/zabbix-whatsapp/config.yaml")
    p.add_argument("--json", action="store_true", help="Saída em JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("clientes")

    s = sub.add_parser("problemas")
    s.add_argument("--cliente")
    s.add_argument("--min-sev", type=int, choices=range(0, 6))

    s = sub.add_parser("host")
    s.add_argument("--cliente", required=True)
    s.add_argument("nome")

    s = sub.add_parser("relatorio")
    s.add_argument("--cliente", required=True)
    s.add_argument("--periodo", choices=["daily", "weekly", "monthly"], default="weekly")
    s.add_argument("--inicio", help="YYYY-MM-DD (com --fim, período personalizado)")
    s.add_argument("--fim")
    s.add_argument("--output-dir")
    s.add_argument("--demo", action="store_true")

    s = sub.add_parser("reconhecer")
    s.add_argument("--cliente", required=True)
    s.add_argument("eventid")
    s.add_argument("--mensagem", required=True)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    if args.cmd == "relatorio":
        if bool(args.inicio) != bool(args.fim):
            p.error("--inicio e --fim devem ser usados juntos")
        if args.inicio:
            args.periodo = "custom"

    if args.cmd == "relatorio" and args.demo and not Path(args.config).exists():
        cfg = {"company_name": "Demo", "clients": [{"name": args.cliente}]}
    else:
        cfg = rep.load_config(args.config)

    handler = {"clientes": cmd_clientes, "problemas": cmd_problemas, "host": cmd_host,
               "relatorio": cmd_relatorio, "reconhecer": cmd_reconhecer}[args.cmd]
    out = handler(cfg, args)
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
