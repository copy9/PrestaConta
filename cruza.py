#!/usr/bin/env python3
"""
O cruzamento que o projeto existia para fazer.

Com o quadro societario em maos (dados/socios.json), procura tres coisas:

  1. SOCIO = PARLAMENTAR
     O nome do socio bate com o nome do parlamentar E os seis digitos do meio do
     CPF batem. Os dois precisam bater: so nome e homonimo, so CPF e coincidencia
     de 1 em um milhao mas acontece em base grande.

  2. SOCIO = DOADOR DA CAMPANHA
     Quem doou para a campanha e socio de uma empresa que depois recebeu dinheiro
     publico pela cota do mesmo parlamentar. Doador e socio sao casados por nome +
     CPF parcial, que o TSE e a Receita publicam no mesmo formato.

  3. EMPRESA SUSPEITA PELO PROPRIO CADASTRO
     Empresa que recebeu da cota estando BAIXADA, INAPTA ou SUSPENSA, ou aberta
     menos de 180 dias antes de comecar a receber.

O CPF dos parlamentares e lido da API da Camara, usado em memoria e descartado:
so os seis digitos do meio entram na comparacao, e nem esses sao gravados.

Saida: dados/vinculos.json
"""
import json, os, re, time, unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

CAMARA = "https://dadosabertos.camara.leg.br/api/v2"
NOVA = 180          # dias entre abertura da empresa e o primeiro dinheiro
IRRELEVANTES = {"SOCIEDADE ANONIMA", "LTDA", "ME", "EPP", "EIRELI"}

ses = requests.Session()
ses.headers.update({"Accept": "application/json", "User-Agent": "PrestaConta/prototipo"})


def so_digitos(s):
    return re.sub(r"\D", "", s or "")


def chave(nome):
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip().upper()


def miolo(doc):
    d = so_digitos(doc)
    if len(d) == 11:
        return d[3:9]
    return d if len(d) == 6 else ""


def nome_forte(n):
    """Nome serve para casar? Precisa de pelo menos dois pedacos de verdade."""
    partes = [p for p in chave(n).split() if len(p) > 2 and p not in IRRELEVANTES]
    return len(partes) >= 2


def cpf_do_deputado(reg):
    try:
        r = ses.get(f"{CAMARA}/deputados/{reg['fonte_id']}", timeout=40)
        if r.status_code == 200:
            return reg["id"], so_digitos(r.json()["dados"].get("cpf"))
    except requests.RequestException:
        pass
    return reg["id"], ""


def dias(a, b):
    try:
        ta = time.mktime(time.strptime(a[:10], "%Y-%m-%d"))
        tb = time.mktime(time.strptime(b[:10], "%Y-%m-%d"))
        return (tb - ta) / 86400.0
    except Exception:
        return None


def main():
    dados = json.load(open("dados/parlamentares.json", encoding="utf-8"))
    regs = dados["parlamentares"]
    emp = json.load(open("dados/socios.json", encoding="utf-8"))["empresas"]
    por_id = {p["id"]: p for p in regs}

    deps = [r for r in regs if r["id"].startswith("d")]
    print(f"lendo CPF de {len(deps)} deputados (so para o cruzamento)...", flush=True)
    cpf6 = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for pid, cpf in pool.map(cpf_do_deputado, deps):
            if cpf:
                cpf6[pid] = cpf[3:9]
    print(f"  {len(cpf6)} pela API da Camara", flush=True)

    # O Senado nao publica CPF, mas o TSE publica: quando o candidato poe dinheiro
    # proprio na campanha, ele aparece na lista de doadores com o proprio nome e o
    # proprio CPF mascarado. Mesmos seis digitos, mesma mascara — serve para conferir.
    por_tse = 0
    for p in regs:
        if cpf6.get(p["id"]):
            continue
        nomes = {chave(p.get("nome")), chave(p.get("nome_civil"))}
        for ano, b in (p.get("campanha") or {}).items():
            for d in b["doadores"]:
                if d["tipo"] != "PF":
                    continue
                proprio = "próprio" in (d.get("fonte") or "").lower()
                if (proprio or chave(d["nome"]) in nomes) and chave(d["nome"]) in nomes:
                    m = miolo(d["doc"])
                    if m:
                        cpf6[p["id"]] = m
                        por_tse += 1
                        break
            if cpf6.get(p["id"]):
                break
    print(f"  mais {por_tse} pelo recurso proprio declarado ao TSE "
          f"({len(cpf6)} no total)", flush=True)
    # quem e o proprio parlamentar, para nao chamar o candidato de "doador externo"
    eu_mesmo = {(chave(p.get("nome")), cpf6.get(p["id"], "")) for p in regs}
    eu_mesmo |= {(chave(p.get("nome_civil")), cpf6.get(p["id"], "")) for p in regs}

    # indice: nome do parlamentar -> ids
    parl_nome = defaultdict(set)
    for p in regs:
        for n in (p.get("nome"), p.get("nome_civil")):
            if n and nome_forte(n):
                parl_nome[chave(n)].add(p["id"])

    # indice: doadores pessoa fisica, por (nome, cpf6) -> para quem doou
    doador = defaultdict(lambda: defaultdict(float))
    for p in regs:
        for ano, b in (p.get("campanha") or {}).items():
            for d in b["doadores"]:
                if d["tipo"] != "PF" or not nome_forte(d["nome"]):
                    continue
                doador[(chave(d["nome"]), miolo(d["doc"]))][p["id"]] += d["valor"]

    # quem pagou o que para cada CNPJ
    cota_de = defaultdict(dict)       # cnpj -> pid -> valor
    primeiro_ano = defaultdict(dict)  # cnpj -> pid -> primeiro ano com nota
    camp_de = defaultdict(dict)
    for p in regs:
        if p.get("cota"):
            for f in p["cota"]["fornecedores"]:
                c = so_digitos(f["cnpj"])
                cota_de[c][p["id"]] = f["valor"]
                anos = sorted((f.get("anos") or {}).keys())
                if anos:
                    primeiro_ano[c][p["id"]] = anos[0]
        for ano, b in (p.get("campanha") or {}).items():
            for f in b["fornecedores"]:
                if f["tipo"] == "PJ" and f["doc"]:
                    c = so_digitos(f["doc"])
                    camp_de[c][p["id"]] = camp_de[c].get(p["id"], 0) + f["valor"]

    v_parl, v_doador, v_cadastro = [], [], []

    for cnpj, e in emp.items():
        recebeu_cota = cota_de.get(cnpj) or {}
        recebeu_camp = camp_de.get(cnpj) or {}
        quem = set(recebeu_cota) | set(recebeu_camp)

        for s in e.get("socios") or []:
            k, m = chave(s["nome"]), s.get("cpf6") or ""
            if not nome_forte(s["nome"]):
                continue

            # 1. socio é o proprio parlamentar
            for pid in parl_nome.get(k, ()):
                if m and cpf6.get(pid) and m != cpf6[pid]:
                    continue                      # mesmo nome, CPF diferente: homonimo
                # o Senado nao publica CPF: para senador o nome e tudo o que ha
                tem_cpf = bool(m and cpf6.get(pid))
                cota_p = recebeu_cota.get(pid, 0)
                camp_p = recebeu_camp.get(pid, 0)
                outros = sum(v for i, v in recebeu_cota.items() if i != pid)
                # sem CPF conferido e sem dinheiro nenhum ligando os dois, e so
                # coincidencia de nome — diretorio do proprio partido, por exemplo
                if not tem_cpf and not (cota_p or camp_p or outros):
                    continue
                v_parl.append({
                    "cnpj": cnpj, "empresa": e["razao"], "situacao": e["situacao"],
                    "id": pid, "socio": s["nome"], "qual": s["qual"], "desde": s["desde"],
                    "cpf_confere": tem_cpf, "cpf_disponivel": bool(cpf6.get(pid)),
                    "cota": cota_p, "campanha": camp_p, "cota_outros": outros,
                })

            # 2. socio é doador de campanha de quem pagou a empresa
            alvo = doador.get((k, m)) if m else None
            if alvo:
                for pid, valor in alvo.items():
                    if pid not in quem:
                        continue
                    # candidato que poe dinheiro proprio nao e "doador": e ele mesmo,
                    # e esse caso ja esta na tabela de socio = parlamentar
                    if (k, m) in eu_mesmo:
                        continue
                    v_doador.append({
                        "cnpj": cnpj, "empresa": e["razao"], "situacao": e["situacao"],
                        "id": pid, "socio": s["nome"], "qual": s["qual"],
                        "doou": round(valor),
                        "cota": recebeu_cota.get(pid, 0),
                        "campanha": recebeu_camp.get(pid, 0),
                    })

        # 3. o cadastro da empresa por si so
        if recebeu_cota:
            motivos = []
            sit = (e.get("situacao") or "").upper()
            if sit and sit != "ATIVA":
                motivos.append("situação " + sit.lower())
            # A cota e publicada por ano, nao por data da nota: dizer "aberta 3 dias
            # antes de receber" seria inventar precisao que o dado nao tem. O que da
            # para afirmar e a data de abertura e o ano do primeiro pagamento.
            ab = (e.get("abertura") or "")[:10]
            for pid, ano in sorted((primeiro_ano.get(cnpj) or {}).items(), key=lambda kv: kv[1]):
                if not ab:
                    break
                d = dias(ab, f"{int(ano)+1}-01-01")
                if d is not None and 0 <= d <= 365 + NOVA:
                    br = "/".join(reversed(ab.split("-")))
                    motivos.append(f"aberta em {br} e já recebeu de {por_id[pid]['nome']} em {ano}")
                    break
            if motivos:
                v_cadastro.append({
                    "cnpj": cnpj, "empresa": e["razao"], "situacao": e["situacao"],
                    "abertura": e.get("abertura", ""), "motivos": motivos,
                    "cota": sum(recebeu_cota.values()),
                    "gabinetes": len(recebeu_cota),
                    "quem": sorted(recebeu_cota, key=lambda i: -recebeu_cota[i])[:6],
                })

    # --- a leitura de cada achado, escrita a partir do proprio dado ---------------
    def brl(v):
        return "R$ " + f"{round(v):,}".replace(",", ".")

    def quanto(v):
        if v >= 1_000_000:
            return f"R$ {v/1_000_000:.1f} mi".replace(".", ",")
        if v >= 1000:
            return f"R$ {round(v/1000)} mil"
        return brl(v)

    for x in v_parl:
        p = por_id[x["id"]]
        quem_e = f"{p['nome']} ({p['partido']}/{p['uf']})"
        firmeza = ("Nome e CPF parcial batem com os da Receita, então é a mesma pessoa."
                   if x["cpf_confere"] else
                   "Só o nome bate: a fonte não publica CPF desta pessoa para conferir, "
                   "e homônimo acontece.")
        partes = [f"{quem_e} aparece como {x['qual'].lower() or 'sócio'} da "
                  f"{x['empresa']} no quadro societário da Receita. {firmeza}"]
        if x["campanha"] and x["cota"]:
            partes.append(f"A campanha dele pagou {quanto(x['campanha'])} a essa empresa, "
                          f"e o gabinete pagou mais {quanto(x['cota'])} com a cota parlamentar.")
            partes.append("Quem decide o gasto e quem recebe são a mesma pessoa nos dois casos. "
                          "É declarado e não é proibido, mas é o tipo de contratação que "
                          "costuma exigir explicação: o dinheiro sai do caixa público ou de "
                          "campanha e entra num patrimônio dele.")
        elif x["campanha"]:
            partes.append(f"A campanha dele pagou {quanto(x['campanha'])} a essa mesma empresa.")
            partes.append("Na prática, parte do gasto de campanha ficou dentro do próprio "
                          "patrimônio. A lei permite e a prestação de contas declara — o que "
                          "este site faz é mostrar que as duas pontas são a mesma pessoa.")
        elif x["cota"]:
            partes.append(f"O gabinete dele pagou {quanto(x['cota'])} a essa empresa com a "
                          f"cota parlamentar, que é dinheiro público.")
            partes.append("Gabinete contratando empresa do próprio titular é o caso mais "
                          "sensível desta página: cabe checar se houve declaração de "
                          "impedimento e qual serviço foi prestado.")
        elif x["cota_outros"]:
            partes.append(f"Ele não pagou nada a ela, mas outros gabinetes pagaram "
                          f"{quanto(x['cota_outros'])} com a cota.")
            partes.append("Empresa de parlamentar recebendo cota de colegas não é ilegal, "
                          "mas é um fluxo de dinheiro público para o patrimônio de alguém "
                          "que vota as regras desse mesmo dinheiro.")
        x["leitura"] = " ".join(partes)

    for x in v_doador:
        p = por_id[x["id"]]
        total = x["cota"] + x["campanha"]
        de_onde = []
        if x["campanha"]:
            de_onde.append(f"{quanto(x['campanha'])} da própria campanha")
        if x["cota"]:
            de_onde.append(f"{quanto(x['cota'])} da cota parlamentar, que é dinheiro público")
        volta = round(total / x["doou"], 1) if x["doou"] else 0
        x["leitura"] = (
            f"{x['socio'].title()} doou {quanto(x['doou'])} para a campanha de {p['nome']} "
            f"({p['partido']}/{p['uf']}). Essa mesma pessoa é {x['qual'].lower() or 'sócia'} "
            f"da {x['empresa']}, que recebeu {' e '.join(de_onde)} do mesmo parlamentar. "
            + (f"Voltou cerca de {str(volta).replace('.', ',')}× o valor doado. "
               if volta >= 1 else "")
            + "Doação e contratação são atos legais e separados; o que chama atenção é o "
              "circuito fechado — o dinheiro sai de quem doou e volta para uma empresa dele. "
              "Confira o serviço prestado antes de concluir qualquer coisa."
        )

    for x in v_cadastro:
        nomes = [por_id[i]["nome"] for i in x["quem"] if i in por_id][:3]
        sit = (x["situacao"] or "").upper()
        g = x["gabinetes"]
        base = (f"A {x['empresa']} recebeu {quanto(x['cota'])} da cota parlamentar de "
                f"{g} gabinete" + ("s" if g != 1 else "")
                + (f", entre eles {', '.join(nomes)}" if nomes else "") + ". ")
        if sit and sit != "ATIVA":
            base += (f"Hoje o CNPJ dela está {sit.lower()} na Receita. A situação é a de agora, "
                     "não a da data da nota: empresa que fecha depois de prestar o serviço é "
                     "comum e legítimo. Vale olhar quando a baixa aconteceu.")
        else:
            base += ("Ela foi aberta pouco antes do primeiro pagamento. Empresa nova também "
                     "nasce todo dia e precisa de cliente — o que pede checagem é empresa "
                     "aberta às vésperas de ganhar um contrato de porte.")
        x["leitura"] = base

    v_parl.sort(key=lambda x: -(x["cota"] + x["campanha"]))
    v_doador.sort(key=lambda x: -(x["cota"] + x["campanha"]))
    v_cadastro.sort(key=lambda x: -x["cota"])

    saida = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "socio_parlamentar": v_parl,
             "socio_doador": v_doador,
             "cadastro": v_cadastro}
    json.dump(saida, open("dados/vinculos.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"\nsócio que é o próprio parlamentar: {len(v_parl)}"
          f" (com CPF conferido: {sum(1 for x in v_parl if x['cpf_confere'])})")
    print(f"sócio que doou para quem pagou a empresa: {len(v_doador)}")
    print(f"empresa com cadastro que merece olhada: {len(v_cadastro)}")
    print(f"json: {os.path.getsize('dados/vinculos.json')/1024:.0f} KB")
    for x in v_parl[:5]:
        print(f"  · {por_id[x['id']]['nome']} — {x['empresa'][:40]} "
              f"({'CPF confere' if x['cpf_confere'] else 'só nome'})")


if __name__ == "__main__":
    main()
