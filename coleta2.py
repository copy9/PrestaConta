#!/usr/bin/env python3
"""
Segunda rodada: detalhe de cada parlamentar + cota parlamentar da 57a legislatura.

Camara  /deputados/{id}                       -> nome civil, nascimento, escolaridade, gabinete, redes
        /deputados/{id}/despesas?idLegislatura=57 -> cada nota fiscal, com fornecedor e CNPJ
Senado  /senador/{cod}.json                   -> nascimento, naturalidade, endereco, telefone

O CPF vem no detalhe do deputado e NAO e gravado: nao precisamos dele para exibir,
e publicar 513 CPFs inteiros seria exposicao desnecessaria.

Saida: dados/parlamentares.json enriquecido.
"""
import json, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

CAMARA = "https://dadosabertos.camara.leg.br/api/v2"
SENADO = "https://legis.senado.leg.br/dadosabertos"
LEG = 57
ANO0 = 2023          # primeiro ano da 57a legislatura
TOP_FORN = 10
TOP_TIPO = 6

ses = requests.Session()
ses.headers.update({"Accept": "application/json", "User-Agent": "PrestaConta/prototipo"})


def get(url):
    for t in range(4):
        try:
            r = ses.get(url, timeout=50)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (t + 1)); continue
            return None
        except requests.RequestException:
            time.sleep(1.5 * (t + 1))
    return None


def paginado(url):
    """Segue o link 'next' que a API devolve ate acabar."""
    itens = []
    while url:
        j = get(url)
        if not j:
            break
        itens += j.get("dados", [])
        url = next((l["href"] for l in j.get("links", []) if l.get("rel") == "next"), None)
    return itens


def detalhe_deputado(reg):
    j = get(f"{CAMARA}/deputados/{reg['fonte_id']}")
    if not j:
        return
    d = j["dados"]
    st = d.get("ultimoStatus") or {}
    gab = st.get("gabinete") or {}
    reg["nome_civil"] = d.get("nomeCivil") or ""
    reg["nascimento"] = d.get("dataNascimento") or ""
    reg["naturalidade"] = ", ".join(x for x in [d.get("municipioNascimento"), d.get("ufNascimento")] if x)
    reg["escolaridade"] = d.get("escolaridade") or ""
    reg["situacao"] = st.get("situacao") or ""
    reg["condicao"] = st.get("condicaoEleitoral") or ""
    reg["site"] = d.get("urlWebsite") or ""
    reg["redes"] = [u for u in (d.get("redeSocial") or []) if u]
    tel = gab.get("telefone") or ""
    sala = " ".join(x for x in [gab.get("predio") and f"Prédio {gab['predio']}",
                                gab.get("sala") and f"sala {gab['sala']}",
                                gab.get("andar") and f"{gab['andar']}º andar"] if x)
    reg["gabinete"] = sala
    reg["telefone"] = tel
    # d["cpf"] existe e e deliberadamente descartado aqui


def despesas_deputado(reg):
    itens = paginado(f"{CAMARA}/deputados/{reg['fonte_id']}/despesas"
                     f"?idLegislatura={LEG}&itens=100&ordem=ASC&ordenarPor=ano")
    if not itens:
        reg["cota"] = None
        return
    meses = defaultdict(float)
    forn = defaultdict(float)
    forn_ano = defaultdict(lambda: defaultdict(float))
    nomes = {}
    tipos = defaultdict(float)
    tipos_ano = defaultdict(lambda: defaultdict(float))
    por_ano = defaultdict(float)
    total = 0.0
    for x in itens:
        v = x.get("valorLiquido") or 0.0
        if v <= 0:
            continue
        total += v
        ano, mes = x.get("ano") or 0, x.get("mes") or 0
        if ano >= ANO0 and 1 <= mes <= 12:
            meses[(ano - ANO0) * 12 + (mes - 1)] += v
        if ano:
            por_ano[ano] += v
        cnpj = (x.get("cnpjCpfFornecedor") or "").strip()
        if cnpj:
            forn[cnpj] += v
            nomes.setdefault(cnpj, x.get("nomeFornecedor") or "")
            if ano:
                forn_ano[cnpj][ano] += v
        tp = x.get("tipoDespesa") or ""
        if tp:
            tipos[tp] += v
            if ano:
                tipos_ano[tp][ano] += v
    n = (max(meses) + 1) if meses else 0
    serie = [round(meses.get(i, 0.0)) for i in range(n)]
    top = sorted(forn.items(), key=lambda kv: -kv[1])[:TOP_FORN]
    reg["cota"] = {
        "total": round(total),
        "docs": len(itens),
        "ano0": ANO0,
        "serie": serie,
        "por_ano": {str(a): round(v) for a, v in sorted(por_ano.items())},
        "fornecedores": [{"cnpj": c, "nome": nomes.get(c, ""), "valor": round(v),
                          "anos": {str(a): round(x) for a, x in sorted(forn_ano[c].items()) if round(x)}}
                         for c, v in top],
        "n_fornecedores": len(forn),
        "tipos": [{"tipo": t, "valor": round(v),
                   "anos": {str(a): round(x) for a, x in sorted(tipos_ano[t].items()) if round(x)}}
                  for t, v in sorted(tipos.items(), key=lambda kv: -kv[1])[:TOP_TIPO]],
    }


def detalhe_senador(reg):
    j = get(f"{SENADO}/senador/{reg['fonte_id']}.json")
    if not j:
        return
    p = (j.get("DetalheParlamentar") or {}).get("Parlamentar") or {}
    db = p.get("DadosBasicosParlamentar") or {}
    ident = p.get("IdentificacaoParlamentar") or {}
    reg["nome_civil"] = ident.get("NomeCompletoParlamentar") or reg.get("nome_completo") or ""
    reg["nascimento"] = db.get("DataNascimento") or ""
    reg["naturalidade"] = ", ".join(x for x in [db.get("Naturalidade"), db.get("UfNaturalidade")] if x)
    reg["gabinete"] = db.get("EnderecoParlamentar") or ""
    tel = (p.get("Telefones") or {}).get("Telefone")
    if isinstance(tel, dict):
        tel = [tel]
    reg["telefone"] = (tel or [{}])[0].get("NumeroTelefone", "") if tel else ""
    reg["site"] = ident.get("UrlPaginaParticular") or ""
    reg["redes"] = []
    reg["cota"] = None          # a cota do Senado (CEAPS) esta noutra base, fora do ar aqui


def trabalha(reg):
    if reg["id"].startswith("d"):
        detalhe_deputado(reg)
        despesas_deputado(reg)
    else:
        detalhe_senador(reg)
    return reg["id"]


def main():
    dados = json.load(open("dados/parlamentares.json", encoding="utf-8"))
    regs = dados["parlamentares"]
    print(f"enriquecendo {len(regs)} parlamentares...", flush=True)
    t0 = time.time()
    feitos = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        for _ in pool.map(trabalha, regs):
            feitos += 1
            if feitos % 50 == 0:
                print(f"  {feitos}/{len(regs)}  ({time.time()-t0:.0f}s)", flush=True)

    com_cota = [r for r in regs if r.get("cota")]
    gasto = sum(r["cota"]["total"] for r in com_cota)
    dados["legislatura"] = LEG
    dados["cota_ano0"] = ANO0
    dados["gerado_detalhe_em"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    json.dump(dados, open("dados/parlamentares.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    import os
    print(f"\npronto em {time.time()-t0:.0f}s")
    print(f"  com dados de cota: {len(com_cota)}")
    print(f"  gasto somado: R$ {gasto:,.0f}".replace(",", "."))
    print(f"  json: {os.path.getsize('dados/parlamentares.json')/1024:.0f} KB")
    sem_nasc = sum(1 for r in regs if not r.get("nascimento"))
    print(f"  sem data de nascimento: {sem_nasc}")


if __name__ == "__main__":
    main()
