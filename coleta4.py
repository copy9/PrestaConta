#!/usr/bin/env python3
"""
Votacoes nominais do plenario da Camara, 57a legislatura.

Camara  /votacoes?dataInicio&dataFim        -> todas as votacoes do periodo
        /votacoes/{id}/votos                -> o voto de cada deputado, quando
                                               a votacao foi NOMINAL

A maioria das votacoes do plenario e simbolica e nao tem voto individual: essas
voltam com lista vazia e sao descartadas. So o que tem nome e voto entra aqui.

Para cada deputado:
  nominais   quantas votacoes nominais aconteceram enquanto ele estava em exercicio
  presente   em quantas ele registrou voto (Sim, Nao, Abstencao ou Obstrucao)
  sim/nao    como votou
  c_partido  em quantas votou igual a maioria do proprio partido
  c_maioria  em quantas votou igual ao lado que venceu

Saida: dados/votacoes.json  (resumo + as votacoes recentes, voto a voto)
"""
import calendar, json, os, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

API = "https://dadosabertos.camara.leg.br/api/v2"
ANO0, ANO1 = 2023, 2026
ORGAO = "PLEN"
RECENTES = 40          # votacoes guardadas voto a voto, para a ficha
WORKERS = 10

ses = requests.Session()
ses.headers.update({"Accept": "application/json", "User-Agent": "PrestaConta/prototipo"})


def get(url):
    for t in range(4):
        try:
            r = ses.get(url, timeout=50)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (t + 1)); continue
            return None
        except requests.RequestException:
            time.sleep(1.5 * (t + 1))
    return None


def paginado(url):
    itens = []
    while url:
        j = get(url)
        if not j:
            break
        itens += j.get("dados", [])
        url = next((l["href"] for l in j.get("links", []) if l.get("rel") == "next"), None)
    return itens


def votacoes_do_mes(am):
    a, m = am
    fim = calendar.monthrange(a, m)[1]
    v = paginado(f"{API}/votacoes?dataInicio={a}-{m:02d}-01&dataFim={a}-{m:02d}-{fim}&itens=100")
    return [x for x in v if x.get("siglaOrgao") == ORGAO]


def votos_da_votacao(v):
    """/votos NAO aceita o parametro itens — manda 400 e some com tudo. Ele
       devolve a votacao inteira de uma vez, sem paginar."""
    j = get(f"{API}/votacoes/{v['id']}/votos")
    itens = (j or {}).get("dados", [])
    if not itens:
        return v, [], []
    o = get(f"{API}/votacoes/{v['id']}/orientacoes")
    return v, itens, (o or {}).get("dados", [])


def main():
    hoje = time.gmtime()
    meses = [(a, m) for a in range(ANO0, ANO1 + 1) for m in range(1, 13)
             if not (a == hoje.tm_year and m > hoje.tm_mon)]
    print(f"listando votacoes do plenario de {ANO0} a {ANO1}...", flush=True)
    t0 = time.time()
    todas = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for lote in pool.map(votacoes_do_mes, meses):
            todas += lote
    todas.sort(key=lambda x: x.get("dataHoraRegistro") or "")
    print(f"  {len(todas)} votacoes de plenario ({time.time()-t0:.0f}s)", flush=True)

    print("buscando o voto a voto (so as nominais devolvem lista)...", flush=True)
    nominais = []
    feitos = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for v, itens, orient in pool.map(votos_da_votacao, todas):
            feitos += 1
            if itens:
                nominais.append((v, itens, orient))
            if feitos % 500 == 0:
                print(f"  {feitos}/{len(todas)}  nominais ate aqui: {len(nominais)}"
                      f"  ({time.time()-t0:.0f}s)", flush=True)
    nominais.sort(key=lambda x: x[0].get("dataHoraRegistro") or "")
    print(f"  {len(nominais)} votacoes nominais ({time.time()-t0:.0f}s)", flush=True)

    resumo = defaultdict(lambda: {"nominais": 0, "presente": 0, "sim": 0, "nao": 0,
                                  "outros": 0, "c_partido": 0, "n_partido": 0, "c_maioria": 0})
    janela = {}      # id -> [primeira votacao em que aparece, ultima]
    recentes = []

    for idx, (v, itens, orient) in enumerate(nominais):
        votos = {}
        for x in itens:
            dep = x.get("deputado_") or {}
            did = dep.get("id")
            tipo = (x.get("tipoVoto") or "").strip()
            if did and tipo:
                votos[did] = {"voto": tipo, "partido": dep.get("siglaPartido") or ""}

        # orientacao oficial de cada bancada; quando nao ha, cai na maioria do partido
        orientacao = {}
        for o in orient:
            sg = (o.get("siglaPartidoBloco") or "").strip()
            ori = (o.get("orientacaoVoto") or "").strip()
            if sg and ori in ("Sim", "Não"):
                orientacao[sg] = ori
        por_partido = defaultdict(lambda: defaultdict(int))
        geral = defaultdict(int)
        for did, d in votos.items():
            if d["voto"] in ("Sim", "Não"):
                por_partido[d["partido"]][d["voto"]] += 1
                geral[d["voto"]] += 1
        maioria_partido = {p: max(c.items(), key=lambda kv: kv[1])[0] for p, c in por_partido.items()}
        maioria_geral = max(geral.items(), key=lambda kv: kv[1])[0] if geral else None

        for did, d in votos.items():
            r = resumo[did]
            j = janela.get(did)
            janela[did] = [idx, idx] if j is None else [j[0], idx]
            r["presente"] += 1
            if d["voto"] == "Sim":
                r["sim"] += 1
            elif d["voto"] == "Não":
                r["nao"] += 1
            else:
                r["outros"] += 1
            if d["voto"] in ("Sim", "Não"):
                ref = orientacao.get(d["partido"], maioria_partido.get(d["partido"]))
                if ref:
                    r["n_partido"] += 1
                    if ref == d["voto"]:
                        r["c_partido"] += 1
                if maioria_geral == d["voto"]:
                    r["c_maioria"] += 1

    # "nominais" = votacoes que aconteceram entre a primeira e a ultima vez que a
    # pessoa votou. Quem assumiu no meio da legislatura nao e punido por ausencia
    # em votacao anterior a posse, e quem saiu nao e punido pelo que veio depois.
    for did, (a, b) in janela.items():
        resumo[did]["nominais"] = b - a + 1
        resumo[did]["estreia"] = nominais[a][0].get("data") or ""
        resumo[did]["ultima"] = nominais[b][0].get("data") or ""

    for v, itens, orient in nominais[-RECENTES:]:
        votos = {}
        for x in itens:
            dep = x.get("deputado_") or {}
            if dep.get("id") and (x.get("tipoVoto") or "").strip():
                votos[str(dep["id"])] = x["tipoVoto"].strip()
        sim = sum(1 for t in votos.values() if t == "Sim")
        nao = sum(1 for t in votos.values() if t == "Não")
        recentes.append({
            "id": v["id"],
            "data": v.get("data") or "",
            "descricao": (v.get("descricao") or "").strip(),
            "aprovacao": v.get("aprovacao"),
            "sim": sim, "nao": nao, "outros": len(votos) - sim - nao,
            "votos": votos,
        })
    recentes.reverse()   # mais recente primeiro

    saida = {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "orgao": ORGAO,
        "periodo": [ANO0, ANO1],
        "total_plenario": len(todas),
        "total_nominais": len(nominais),
        "resumo": {str(k): v for k, v in resumo.items()},
        "recentes": recentes,
    }
    os.makedirs("dados", exist_ok=True)
    json.dump(saida, open("dados/votacoes.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"\npronto em {time.time()-t0:.0f}s")
    print(f"  deputados com voto registrado: {len(resumo)}")
    print(f"  votacoes guardadas voto a voto: {len(recentes)}")
    print(f"  json: {os.path.getsize('dados/votacoes.json')/1024:.0f} KB")


if __name__ == "__main__":
    main()
