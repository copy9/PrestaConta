#!/usr/bin/env python3
"""
Emendas parlamentares de autoria, do Portal da Transparencia (CGU).

  /api-de-dados/emendas?ano=&pagina=   -> 15 por pagina, com autor, valor
                                          empenhado/liquidado/pago, localidade,
                                          funcao e subfuncao

A chave e PESSOAL e e lida de /tmp/.chave_cgu ou da variavel CHAVE_CGU. Ela nunca
entra no json de saida nem no repositorio.

O casamento com o parlamentar e pelo nome do autor, normalizado (sem acento, sem
pontuacao, caixa alta). Quando o autor aparece como "FULANO (EX-PARLAMENTAR
BELTRANO, NOS TERMOS...)", so a parte antes do parenteses e usada.

Saida: dados/emendas.json
"""
import json, os, re, sys, time, unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import requests

API = "https://api.portaldatransparencia.gov.br/api-de-dados/emendas"
ANOS = [2023, 2024, 2025, 2026]
WORKERS = 5            # a chave tem limite por minuto; nao vale a pena correr mais
TOP_EMENDA = 15

chave = os.environ.get("CHAVE_CGU") or (
    open("/tmp/.chave_cgu").read().strip() if os.path.exists("/tmp/.chave_cgu") else "")
if not chave:
    sys.exit("sem chave: exporte CHAVE_CGU ou grave /tmp/.chave_cgu")

ses = requests.Session()
ses.headers.update({"chave-api-dados": chave, "Accept": "application/json",
                    "User-Agent": "PrestaConta/prototipo"})
trava = Lock()
feitos = [0]


def chavenome(nome):
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip().upper()


def valor(txt):
    txt = (txt or "0").strip().replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return 0.0


def pagina(args):
    ano, p = args
    for t in range(5):
        try:
            r = ses.get(f"{API}?ano={ano}&pagina={p}", timeout=60)
            if r.status_code == 200:
                with trava:
                    feitos[0] += 1
                    if feitos[0] % 200 == 0:
                        print(f"  {feitos[0]} paginas", flush=True)
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 * (t + 1)); continue
            return []
        except requests.RequestException:
            time.sleep(3 * (t + 1))
    return []


def ultima_pagina(ano):
    lo, hi = 1, 1200
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if pagina((ano, mid)):
            lo = mid
        else:
            hi = mid - 1
    return lo


def main():
    dados = json.load(open("dados/parlamentares.json", encoding="utf-8"))
    regs = dados["parlamentares"]
    por_nome = defaultdict(list)
    for r in regs:
        for n in {chavenome(r.get("nome")), chavenome(r.get("nome_civil"))}:
            if n:
                por_nome[n].append(r["id"])

    t0 = time.time()
    tarefas = []
    for ano in ANOS:
        ult = ultima_pagina(ano)
        print(f"{ano}: {ult} paginas", flush=True)
        tarefas += [(ano, p) for p in range(1, ult + 1)]
    print(f"baixando {len(tarefas)} paginas...", flush=True)

    bruto = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for lote in pool.map(pagina, tarefas):
            bruto += lote
    print(f"  {len(bruto)} emendas ({time.time()-t0:.0f}s)", flush=True)

    por_parl = defaultdict(lambda: {"total_empenhado": 0.0, "total_pago": 0.0, "n": 0,
                                    "anos": defaultdict(lambda: {"empenhado": 0.0, "pago": 0.0, "n": 0}),
                                    "locais": defaultdict(float),
                                    "funcoes": defaultdict(float),
                                    "lista": []})
    sem_dono = 0
    for e in bruto:
        autor = (e.get("nomeAutor") or e.get("autor") or "")
        base = autor.split("(")[0]
        ids = por_nome.get(chavenome(base)) or []
        if len(ids) != 1:
            sem_dono += 1
            continue
        pid = ids[0]
        emp, pago = valor(e.get("valorEmpenhado")), valor(e.get("valorPago"))
        d = por_parl[pid]
        d["total_empenhado"] += emp; d["total_pago"] += pago; d["n"] += 1
        a = d["anos"][str(e.get("ano") or "")]
        a["empenhado"] += emp; a["pago"] += pago; a["n"] += 1
        d["locais"][(e.get("localidadeDoGasto") or "—").strip()] += pago or emp
        d["funcoes"][(e.get("funcao") or "—").strip()] += pago or emp
        d["lista"].append({
            "cod": e.get("codigoEmenda") or "", "ano": e.get("ano"),
            "tipo": (e.get("tipoEmenda") or "").replace("Emenda ", ""),
            "local": (e.get("localidadeDoGasto") or "").strip(),
            "funcao": (e.get("funcao") or "").strip(),
            "subfuncao": (e.get("subfuncao") or "").strip(),
            "empenhado": round(emp), "pago": round(pago),
        })

    saida = {}
    for pid, d in por_parl.items():
        d["lista"].sort(key=lambda x: -(x["pago"] or x["empenhado"]))
        saida[pid] = {
            "total_empenhado": round(d["total_empenhado"]),
            "total_pago": round(d["total_pago"]),
            "n": d["n"],
            "anos": {a: {"empenhado": round(v["empenhado"]), "pago": round(v["pago"]), "n": v["n"]}
                     for a, v in sorted(d["anos"].items())},
            "locais": [{"local": k, "valor": round(v)}
                       for k, v in sorted(d["locais"].items(), key=lambda kv: -kv[1])[:10]],
            "funcoes": [{"funcao": k, "valor": round(v)}
                        for k, v in sorted(d["funcoes"].items(), key=lambda kv: -kv[1])[:8]],
            "lista": d["lista"][:TOP_EMENDA],
        }

    json.dump({"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "anos": ANOS,
               "total_coletado": len(bruto), "sem_dono": sem_dono,
               "por_parlamentar": saida},
              open("dados/emendas.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"\npronto em {time.time()-t0:.0f}s")
    print(f"  emendas coletadas: {len(bruto)}")
    print(f"  casadas com parlamentar em exercicio: {len(bruto)-sem_dono}")
    print(f"  autores fora da lista (ex-parlamentares, bancadas, comissoes): {sem_dono}")
    print(f"  parlamentares com emenda: {len(saida)}")
    print(f"  json: {os.path.getsize('dados/emendas.json')/1024:.0f} KB")
    bruto_txt = open("dados/emendas.json", encoding="utf-8").read()
    print(f"  a chave vazou para o json: {'SIM' if chave in bruto_txt else 'nao'}")


if __name__ == "__main__":
    main()
