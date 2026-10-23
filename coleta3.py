#!/usr/bin/env python3
"""
Patrimonio declarado ao TSE, eleicao a eleicao.

Fontes (cdn.tse.jus.br, dados abertos):
  consulta_cand_<ano>_BRASIL.csv  -> cadastro da candidatura, com CPF e SQ_CANDIDATO
  bem_candidato_<ano>_BRASIL.csv  -> cada bem declarado, com VR_BEM_CANDIDATO

O casamento e por CPF quando ha CPF (deputados, lido da API da Camara e usado
SO em memoria, nunca gravado) e por nome completo + UF quando nao ha (senadores).

Saida: dados/parlamentares.json ganha "patrimonio".
"""
import csv, json, os, re, sys, time, unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

ANOS = [2014, 2018, 2022, 2026]
TSE = "tse/x"
CAMARA = "https://dadosabertos.camara.leg.br/api/v2"
csv.field_size_limit(10 ** 7)

ses = requests.Session()
ses.headers.update({"Accept": "application/json", "User-Agent": "PrestaConta/prototipo"})


def chave(nome):
    """Nome sem acento, sem pontuacao, em caixa alta — para casar grafias diferentes."""
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip().upper()


def so_digitos(s):
    return re.sub(r"\D", "", s or "")


def cpf_do_deputado(reg):
    """Lido para o cruzamento e descartado em seguida: nao entra no json."""
    try:
        r = ses.get(f"{CAMARA}/deputados/{reg['fonte_id']}", timeout=40)
        if r.status_code == 200:
            return reg["id"], so_digitos(r.json()["dados"].get("cpf"))
    except requests.RequestException:
        pass
    return reg["id"], ""


def le_csv(caminho):
    with open(caminho, encoding="latin-1", newline="") as fh:
        for linha in csv.DictReader(fh, delimiter=";"):
            yield linha


def valor(txt):
    txt = (txt or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return 0.0


def main():
    dados = json.load(open("dados/parlamentares.json", encoding="utf-8"))
    regs = dados["parlamentares"]
    deps = [r for r in regs if r["id"].startswith("d")]

    print(f"lendo CPF de {len(deps)} deputados (so para o cruzamento)...", flush=True)
    cpfs = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for pid, cpf in pool.map(cpf_do_deputado, deps):
            if cpf:
                cpfs[pid] = cpf
    print(f"  {len(cpfs)} CPFs obtidos", flush=True)

    # indices de busca
    por_cpf = {c: r["id"] for r, c in ((r, cpfs.get(r["id"])) for r in deps) if c}
    por_nome = defaultdict(list)
    for r in regs:
        for n in {chave(r.get("nome_civil")), chave(r.get("nome"))}:
            if n:
                por_nome[(n, r["uf"])].append(r["id"])

    patr = defaultdict(dict)     # id -> ano -> {valor, bens, tipos}
    for ano in ANOS:
        cad = os.path.join(TSE, f"consulta_cand_{ano}_BRASIL.csv")
        bem = os.path.join(TSE, f"bem_candidato_{ano}_BRASIL.csv")
        if not (os.path.exists(cad) and os.path.exists(bem)):
            print(f"  {ano}: arquivo ausente, pulando"); continue
        t = time.time()

        sq_para_id, achados_cpf, achados_nome = {}, 0, 0
        for l in le_csv(cad):
            sq = l.get("SQ_CANDIDATO")
            if not sq:
                continue
            cpf = so_digitos(l.get("NR_CPF_CANDIDATO"))
            pid = por_cpf.get(cpf) if cpf else None
            if pid:
                achados_cpf += 1
            else:
                cands = por_nome.get((chave(l.get("NM_CANDIDATO")), l.get("SG_UF")))
                # so aceita por nome quando a dupla nome+UF e unica naquela eleicao
                if cands and len(cands) == 1 and cands[0].startswith("s"):
                    pid = cands[0]; achados_nome += 1
            if pid:
                sq_para_id[sq] = pid

        soma = defaultdict(float); qtd = defaultdict(int); tipos = defaultdict(lambda: defaultdict(float))
        for l in le_csv(bem):
            pid = sq_para_id.get(l.get("SQ_CANDIDATO"))
            if not pid:
                continue
            v = valor(l.get("VR_BEM_CANDIDATO"))
            soma[pid] += v; qtd[pid] += 1
            tipos[pid][(l.get("DS_TIPO_BEM_CANDIDATO") or "Outros").strip()] += v

        for pid, v in soma.items():
            patr[pid][ano] = {
                "valor": round(v),
                "bens": qtd[pid],
                "tipos": [{"tipo": t, "valor": round(x)}
                          for t, x in sorted(tipos[pid].items(), key=lambda kv: -kv[1])[:5]],
            }
        print(f"  {ano}: {len(sq_para_id)} candidaturas casadas "
              f"({achados_cpf} por CPF, {achados_nome} por nome), "
              f"{len(soma)} com bens — {time.time()-t:.0f}s", flush=True)

    com = 0
    for r in regs:
        anos = patr.get(r["id"]) or {}
        serie = [{"ano": a, "valor": anos[a]["valor"], "bens": anos[a]["bens"],
                  "tipos": anos[a]["tipos"]} for a in ANOS if a in anos]
        r["patrimonio"] = serie or None
        if serie:
            com += 1

    dados["patrimonio_anos"] = ANOS
    dados["gerado_patrimonio_em"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    json.dump(dados, open("dados/parlamentares.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"\npronto: {com}/{len(regs)} parlamentares com patrimonio declarado")
    cheios = [r for r in regs if r.get("patrimonio") and len(r["patrimonio"]) >= 2]
    print(f"  com 2+ eleicoes (da para ver evolucao): {len(cheios)}")
    print(f"  json: {os.path.getsize('dados/parlamentares.json')/1024:.0f} KB")
    # nenhum CPF foi gravado
    bruto = open("dados/parlamentares.json", encoding="utf-8").read()
    vazou = [c for c in list(cpfs.values())[:50] if c and c in bruto]
    print(f"  CPFs que vazaram para o json: {len(vazou)}")


if __name__ == "__main__":
    main()
