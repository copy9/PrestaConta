#!/usr/bin/env python3
"""
Junta o que as coletas produziram num unico dados/parlamentares.json:

  campanha.json  -> p["campanha"]  doacoes recebidas e contratos da campanha
  votacoes.json  -> p["votos"]     presenca e fidelidade; e a lista das votacoes
                                    recentes vai para a raiz, com o voto de cada um

Idempotente: pode rodar de novo depois de recoletar qualquer parte.
"""
import json, os, time

base = json.load(open("dados/parlamentares.json", encoding="utf-8"))
regs = base["parlamentares"]
por_id = {p["id"]: p for p in regs}
por_fonte = {str(p["fonte_id"]): p for p in regs if p["id"].startswith("d")}

n_camp = n_vot = 0

if os.path.exists("dados/campanha.json"):
    c = json.load(open("dados/campanha.json", encoding="utf-8"))
    base["campanha_anos"] = c["anos"]
    for pid, blocos in c["por_parlamentar"].items():
        if pid in por_id:
            por_id[pid]["campanha"] = blocos
            n_camp += 1
    for p in regs:
        p.setdefault("campanha", None)

n_em = 0
if os.path.exists("dados/emendas.json"):
    e = json.load(open("dados/emendas.json", encoding="utf-8"))
    base["emendas_anos"] = e["anos"]
    base["emendas_coletadas"] = e["total_coletado"]
    base["emendas_sem_dono"] = e["sem_dono"]
    for pid, bloco in e["por_parlamentar"].items():
        if pid in por_id:
            por_id[pid]["emendas"] = bloco
            n_em += 1
    for p in regs:
        p.setdefault("emendas", None)

if os.path.exists("dados/votacoes.json"):
    v = json.load(open("dados/votacoes.json", encoding="utf-8"))
    for fid, r in v["resumo"].items():
        p = por_fonte.get(fid)
        if p:
            p["votos"] = r
            n_vot += 1
    for p in regs:
        p.setdefault("votos", None)
    # as votacoes recentes ficam na raiz: o mesmo bloco serve a todas as fichas
    base["votacoes"] = {
        "total_plenario": v["total_plenario"],
        "total_nominais": v["total_nominais"],
        "periodo": v["periodo"],
        "recentes": v["recentes"],
    }

if os.path.exists("dados/socios.json"):
    s = json.load(open("dados/socios.json", encoding="utf-8"))
    # chaves curtas de proposito: sao 8,9 mil empresas dentro da pagina, e o nome
    # inteiro de cada campo repetido 8.893 vezes custa mais de 1 MB sozinho
    base["empresas"] = {
        k: {"r": v["razao"], "s": v["situacao"], "u": v["uf"], "m": v["municipio"],
            "c": v["cnae"], "a": v["abertura"], "n": v["n_socios"],
            "q": [[x["nome"], x["cpf6"], x["qual"]] for x in v["socios"][:6]]}
        for k, v in s["empresas"].items()}
    base["empresas_meta"] = {"consultados": s["consultados"], "respondidos": s["respondidos"]}

if os.path.exists("dados/vinculos.json"):
    base["vinculos"] = json.load(open("dados/vinculos.json", encoding="utf-8"))

base["juntado_em"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
json.dump(base, open("dados/parlamentares.json", "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))

print(f"parlamentares com campanha: {n_camp}")
print(f"parlamentares com emendas: {n_em}")
print(f"parlamentares com votacoes: {n_vot}")
print(f"votacoes guardadas voto a voto: {len(base.get('votacoes',{}).get('recentes',[]))}")
print(f"json: {os.path.getsize('dados/parlamentares.json')/1024:.0f} KB")
