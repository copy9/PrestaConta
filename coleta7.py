#!/usr/bin/env python3
"""
Quadro societario das empresas que ja aparecem no projeto.

Por que nao o dump da Receita: dadosabertos.rfb.gov.br derruba a conexao de
fora do Brasil, e o dump sao 70 milhoes de empresas para responder uma pergunta
sobre as ~9 mil que este site toca. Estas APIs servem o MESMO dado da Receita,
empresa a empresa:

  minhareceita.org/<cnpj>            espelho do dump oficial (Open Knowledge Brasil)
  brasilapi.com.br/api/cnpj/v1/<cnpj>  reserva, quando a primeira recusa

O CPF do socio ja vem mascarado na origem (***615007**): seis digitos do meio,
exatamente o mesmo formato com que o TSE publica o CPF do doador. E por isso que
o cruzamento e possivel sem ninguem precisar manipular CPF inteiro.

Saida: dados/socios.json
"""
import json, os, re, sys, time, unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import requests

PRIMARIA = "https://minhareceita.org/{cnpj}"
RESERVA = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
WORKERS = 8
MAX_SOCIOS = 8

ses = requests.Session()
ses.headers.update({"Accept": "application/json", "User-Agent": "PrestaConta/prototipo"})
trava = Lock()
contagem = {"ok": 0, "erro": 0, "reserva": 0}


def so_digitos(s):
    return re.sub(r"\D", "", s or "")


def chave(nome):
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip().upper()


def miolo(cpf_mascarado):
    """'***615007**' -> '615007'. Tambem aceita CPF inteiro e '***.615.007-**'."""
    d = so_digitos(cpf_mascarado)
    if len(d) == 11:
        return d[3:9]
    if len(d) == 6:
        return d
    return ""


def busca(cnpj):
    for url, conta in ((PRIMARIA, "ok"), (RESERVA, "reserva")):
        for t in range(3):
            try:
                r = ses.get(url.format(cnpj=cnpj), timeout=45)
                if r.status_code == 200:
                    with trava:
                        contagem[conta] += 1
                        n = contagem["ok"] + contagem["reserva"] + contagem["erro"]
                        if n % 500 == 0:
                            print(f"  {n} consultadas "
                                  f"(reserva: {contagem['reserva']}, erro: {contagem['erro']})",
                                  flush=True)
                    return cnpj, r.json()
                if r.status_code in (404, 400):
                    break                      # CNPJ nao existe na base; nao adianta a reserva
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 * (t + 1)); continue
                break
            except requests.RequestException:
                time.sleep(2 * (t + 1))
    with trava:
        contagem["erro"] += 1
    return cnpj, None


def compacta(j):
    if not j:
        return None
    socios = []
    for s in (j.get("qsa") or [])[:MAX_SOCIOS]:
        socios.append({
            "nome": (s.get("nome_socio") or "").strip(),
            "cpf6": miolo(s.get("cnpj_cpf_do_socio")),
            "qual": (s.get("qualificacao_socio") or "").strip(),
            "desde": (s.get("data_entrada_sociedade") or "")[:10],
        })
    return {
        "razao": (j.get("razao_social") or "").strip(),
        "fantasia": (j.get("nome_fantasia") or "").strip(),
        "situacao": (j.get("descricao_situacao_cadastral") or "").strip(),
        "desde": (j.get("data_situacao_cadastral") or "")[:10],
        "abertura": (j.get("data_inicio_atividade") or "")[:10],
        "cnae": (j.get("cnae_fiscal_descricao") or "").strip(),
        "municipio": (j.get("municipio") or "").strip(),
        "uf": (j.get("uf") or "").strip(),
        "porte": (j.get("porte") or j.get("descricao_porte") or "").strip(),
        "capital": j.get("capital_social") or 0,
        "n_socios": len(j.get("qsa") or []),
        "socios": socios,
    }


def main():
    dados = json.load(open("dados/parlamentares.json", encoding="utf-8"))
    regs = dados["parlamentares"]

    alvo = {}
    for p in regs:
        if p.get("cota"):
            for f in p["cota"]["fornecedores"]:
                alvo.setdefault(so_digitos(f["cnpj"]), set()).add("cota")
        for ano, b in (p.get("campanha") or {}).items():
            for f in b["fornecedores"]:
                if f["tipo"] == "PJ" and f["doc"]:
                    alvo.setdefault(so_digitos(f["doc"]), set()).add("campanha")
            for d in b["doadores"]:
                if d["tipo"] == "PJ" and d["doc"]:
                    alvo.setdefault(so_digitos(d["doc"]), set()).add("doador")
    cnpjs = [c for c in alvo if len(c) == 14]
    print(f"{len(cnpjs)} CNPJs a consultar", flush=True)

    t0 = time.time()
    empresas = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for cnpj, j in pool.map(busca, cnpjs):
            c = compacta(j)
            if c:
                c["papel"] = sorted(alvo[cnpj])
                empresas[cnpj] = c
    print(f"  {len(empresas)} respondidas em {time.time()-t0:.0f}s", flush=True)

    saida = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "consultados": len(cnpjs), "respondidos": len(empresas),
             "sem_resposta": contagem["erro"], "pela_reserva": contagem["reserva"],
             "empresas": empresas}
    json.dump(saida, open("dados/socios.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"\npronto em {time.time()-t0:.0f}s")
    print(f"  empresas com quadro societário: "
          f"{sum(1 for e in empresas.values() if e['socios'])}")
    print(f"  sócios no total: {sum(len(e['socios']) for e in empresas.values())}")
    print(f"  json: {os.path.getsize('dados/socios.json')/1024:.0f} KB")


if __name__ == "__main__":
    main()
