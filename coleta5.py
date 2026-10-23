#!/usr/bin/env python3
"""
Quem financiou a campanha, e para quem a campanha pagou.

Fonte: prestacao de contas eleitorais do TSE (cdn.tse.jus.br), um zip por eleicao.
  receitas_candidatos_<ano>_<UF>.csv            -> cada doacao recebida
  despesas_contratadas_candidatos_<ano>_<UF>.csv -> cada contrato da campanha

Os zips tem centenas de MB e sao lidos direto de dentro do arquivo compactado,
sem descompactar em disco.

PRIVACIDADE: o TSE publica o CPF inteiro do doador pessoa fisica. Aqui ele e
mascarado para ***.456.789-**, que e a forma com que o proprio TSE exibe CPF em
consulta publica. CNPJ de empresa vai inteiro: empresa nao tem essa protecao, e
o CNPJ e justamente o elo que permite cruzar com a cota parlamentar.

O casamento com o parlamentar e por SQ_CANDIDATO, obtido do cadastro da
candidatura (consulta_cand) por CPF (deputados) ou nome+UF (senadores), como em
coleta3.py. Nenhum CPF de parlamentar e gravado.

Saida: dados/campanha.json
"""
import csv, io, json, os, re, sys, time, unicodedata, zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

ANOS = [2022, 2026]
ZIP = "tse/contas/pc_{ano}.zip"
CAD = "tse/x/consulta_cand_{ano}_BRASIL.csv"
CAMARA = "https://dadosabertos.camara.leg.br/api/v2"
TOP_DOADOR = 12
TOP_FORN = 10
csv.field_size_limit(10 ** 7)

ses = requests.Session()
ses.headers.update({"Accept": "application/json", "User-Agent": "PrestaConta/prototipo"})


def chave(nome):
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip().upper()


def so_digitos(s):
    return re.sub(r"\D", "", s or "")


def valor(txt):
    txt = (txt or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return 0.0


def mascara(doc):
    """CNPJ inteiro; CPF so com os seis digitos do meio, como o TSE mostra."""
    d = so_digitos(doc)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}", "PJ"
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**", "PF"
    return "", "?"


def cpf_do_deputado(reg):
    try:
        r = ses.get(f"{CAMARA}/deputados/{reg['fonte_id']}", timeout=40)
        if r.status_code == 200:
            return reg["id"], so_digitos(r.json()["dados"].get("cpf"))
    except requests.RequestException:
        pass
    return reg["id"], ""


def le_csv_do_zip(z, nome):
    with z.open(nome) as fh:
        for linha in csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1", newline=""),
                                    delimiter=";"):
            yield linha


def nulo(s):
    s = (s or "").strip()
    return "" if s in ("#NULO", "#NULO#", "-1", "") else s


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
    por_cpf = {c: pid for pid, c in cpfs.items()}
    por_nome = defaultdict(list)
    for r in regs:
        for n in {chave(r.get("nome_civil")), chave(r.get("nome"))}:
            if n:
                por_nome[(n, r["uf"])].append(r["id"])
    print(f"  {len(cpfs)} CPFs obtidos", flush=True)

    campanha = {}        # pid -> ano -> bloco
    t0 = time.time()

    for ano in ANOS:
        zpath, cpath = ZIP.format(ano=ano), CAD.format(ano=ano)
        if not (os.path.exists(zpath) and os.path.exists(cpath)):
            print(f"  {ano}: arquivo ausente, pulando"); continue

        # SQ_CANDIDATO -> parlamentar
        sq = {}
        with open(cpath, encoding="latin-1", newline="") as fh:
            for l in csv.DictReader(fh, delimiter=";"):
                s = l.get("SQ_CANDIDATO")
                if not s:
                    continue
                pid = por_cpf.get(so_digitos(l.get("NR_CPF_CANDIDATO")))
                if not pid:
                    c = por_nome.get((chave(l.get("NM_CANDIDATO")), l.get("SG_UF")))
                    if c and len(c) == 1 and c[0].startswith("s"):
                        pid = c[0]
                if pid:
                    sq[s] = pid
        print(f"  {ano}: {len(sq)} candidaturas casadas", flush=True)

        rec = defaultdict(lambda: defaultdict(lambda: {"valor": 0.0, "n": 0, "nome": "",
                                                       "tipo": "", "fonte": "", "ult": ""}))
        fonte = defaultdict(lambda: defaultdict(float))
        tot = defaultdict(float); ndoa = defaultdict(int)
        gas = defaultdict(lambda: defaultdict(lambda: {"valor": 0.0, "n": 0, "nome": "", "tipo": ""}))
        totg = defaultdict(float); ngas = defaultdict(int)

        z = zipfile.ZipFile(zpath)
        receitas = sorted(n for n in z.namelist()
                          if n.startswith(f"receitas_candidatos_{ano}_") and "doador_originario" not in n)
        despesas = sorted(n for n in z.namelist()
                          if n.startswith(f"despesas_contratadas_candidatos_{ano}_"))

        for nome_arq in receitas:
            for l in le_csv_do_zip(z, nome_arq):
                pid = sq.get(l.get("SQ_CANDIDATO"))
                if not pid:
                    continue
                v = valor(l.get("VR_RECEITA"))
                if v <= 0:
                    continue
                doc, tipo = mascara(l.get("NR_CPF_CNPJ_DOADOR"))
                nome = nulo(l.get("NM_DOADOR_RFB")) or nulo(l.get("NM_DOADOR")) or "Não identificado"
                ch = doc or ("nome:" + nome)
                d = rec[pid][ch]
                d["valor"] += v; d["n"] += 1
                d["nome"] = d["nome"] or nome
                d["tipo"] = d["tipo"] or tipo
                d["fonte"] = d["fonte"] or nulo(l.get("DS_ORIGEM_RECEITA"))
                dt = nulo(l.get("DT_RECEITA"))
                if dt:
                    d["ult"] = max(d["ult"], dt[-4:] + dt[3:5] + dt[:2])
                fonte[pid][nulo(l.get("DS_ORIGEM_RECEITA")) or "Outras"] += v
                tot[pid] += v; ndoa[pid] += 1

        for nome_arq in despesas:
            for l in le_csv_do_zip(z, nome_arq):
                pid = sq.get(l.get("SQ_CANDIDATO"))
                if not pid:
                    continue
                v = valor(l.get("VR_DESPESA_CONTRATADA"))
                if v <= 0:
                    continue
                doc, tipo = mascara(l.get("NR_CPF_CNPJ_FORNECEDOR"))
                nome = nulo(l.get("NM_FORNECEDOR_RFB")) or nulo(l.get("NM_FORNECEDOR")) or "Não identificado"
                ch = doc or ("nome:" + nome)
                d = gas[pid][ch]
                d["valor"] += v; d["n"] += 1
                d["nome"] = d["nome"] or nome
                d["tipo"] = d["tipo"] or tipo
                totg[pid] += v; ngas[pid] += 1

        for pid in set(list(tot) + list(totg)):
            doadores = sorted(rec[pid].items(), key=lambda kv: -kv[1]["valor"])[:TOP_DOADOR]
            forns = sorted(gas[pid].items(), key=lambda kv: -kv[1]["valor"])[:TOP_FORN]
            campanha.setdefault(pid, {})[str(ano)] = {
                "total": round(tot[pid]),
                "n_doacoes": ndoa[pid],
                "n_doadores": len(rec[pid]),
                "fontes": [{"fonte": f, "valor": round(v)}
                           for f, v in sorted(fonte[pid].items(), key=lambda kv: -kv[1])],
                "doadores": [{"doc": k if not k.startswith("nome:") else "",
                              "nome": d["nome"], "tipo": d["tipo"], "fonte": d["fonte"],
                              "valor": round(d["valor"]), "n": d["n"]}
                             for k, d in doadores],
                "gasto": round(totg[pid]),
                "n_contratos": ngas[pid],
                "n_fornecedores": len(gas[pid]),
                "fornecedores": [{"doc": k if not k.startswith("nome:") else "",
                                  "nome": d["nome"], "tipo": d["tipo"],
                                  "valor": round(d["valor"]), "n": d["n"]}
                                 for k, d in forns],
            }
        print(f"     {len(tot)} com doacao, {len(totg)} com contrato "
              f"({time.time()-t0:.0f}s)", flush=True)

    saida = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "anos": ANOS,
             "por_parlamentar": campanha}
    json.dump(saida, open("dados/campanha.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"\npronto em {time.time()-t0:.0f}s")
    print(f"  parlamentares com prestacao de contas: {len(campanha)}")
    print(f"  json: {os.path.getsize('dados/campanha.json')/1024:.0f} KB")
    bruto = open("dados/campanha.json", encoding="utf-8").read()
    vazou = [c for c in list(cpfs.values())[:50] if c and c in bruto]
    print(f"  CPFs de parlamentar no json: {len(vazou)}")
    print(f"  CPFs inteiros de doador no json: "
          f"{len(re.findall(chr(34) + chr(100) + 'oc' + chr(34) + r':\"\d{11}\"', bruto))}")


if __name__ == "__main__":
    main()
