#!/usr/bin/env python3
"""
Coleta parlamentares em exercicio (Camara + Senado) com foto oficial.

Saida:
  dados/parlamentares.json  -> lista de registros
  fotos/<id>.jpg            -> miniatura 128x128 (JPEG q78), ~6-9 KB cada

Fontes:
  Camara  https://dadosabertos.camara.leg.br/api/v2/deputados
  Senado  https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json
Nenhuma exige autenticacao.
"""
import io, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

CAMARA = "https://dadosabertos.camara.leg.br/api/v2"
SENADO = "https://legis.senado.leg.br/dadosabertos"
FOTOS = "fotos"
DADOS = "dados"
TAM = 128

ses = requests.Session()
ses.headers.update({"Accept": "application/json", "User-Agent": "PrestaConta/prototipo"})


def get(url, **kw):
    for tentativa in range(4):
        try:
            r = ses.get(url, timeout=40, **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * (tentativa + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(2 * (tentativa + 1))
    return None


def deputados():
    """Pagina /deputados ate o fim seguindo o link 'next' que a propria API devolve."""
    saida, url = [], f"{CAMARA}/deputados?ordem=ASC&ordenarPor=nome&itens=100"
    while url:
        r = get(url)
        if not r:
            raise SystemExit(f"falha ao ler {url}")
        corpo = r.json()
        for d in corpo.get("dados", []):
            saida.append({
                "id": f"d{d['id']}",
                "fonte_id": d["id"],
                "casa": "Câmara dos Deputados",
                "cargo": "Deputado Federal",
                "nome": d.get("nome", ""),
                "partido": d.get("siglaPartido") or "",
                "uf": d.get("siglaUf") or "",
                "email": d.get("email") or "",
                "url_foto": d.get("urlFoto") or "",
                "url_perfil": f"https://www.camara.leg.br/deputados/{d['id']}",
            })
        url = next((l["href"] for l in corpo.get("links", []) if l.get("rel") == "next"), None)
        print(f"  camara: {len(saida)} deputados", flush=True)
    return saida


def senadores():
    r = get(f"{SENADO}/senador/lista/atual.json")
    if not r:
        raise SystemExit("falha ao ler lista de senadores")
    corpo = r.json()
    # ListaParlamentarEmExercicio > Parlamentares > Parlamentar[]
    lista = (corpo.get("ListaParlamentarEmExercicio", {})
                  .get("Parlamentares", {})
                  .get("Parlamentar", []))
    if isinstance(lista, dict):
        lista = [lista]
    saida = []
    for p in lista:
        ident = p.get("IdentificacaoParlamentar", {})
        cod = ident.get("CodigoParlamentar")
        if not cod:
            continue
        saida.append({
            "id": f"s{cod}",
            "fonte_id": cod,
            "casa": "Senado Federal",
            "cargo": "Senador" if ident.get("SexoParlamentar") != "Feminino" else "Senadora",
            "nome": ident.get("NomeParlamentar") or ident.get("NomeCompletoParlamentar") or "",
            "nome_completo": ident.get("NomeCompletoParlamentar") or "",
            "partido": ident.get("SiglaPartidoParlamentar") or "",
            "uf": ident.get("UfParlamentar") or "",
            "email": ident.get("EmailParlamentar") or "",
            "url_foto": ident.get("UrlFotoParlamentar") or "",
            "url_perfil": ident.get("UrlPaginaParlamentar") or "",
        })
    print(f"  senado: {len(saida)} senadores", flush=True)
    return saida


def baixa_foto(reg):
    """Baixa, corta quadrado pelo centro e grava miniatura. Devolve True se gravou."""
    url = reg.get("url_foto")
    if not url:
        return False
    if url.startswith("http://"):          # o Senado publica a foto em http; aqui so passa https
        url = "https://" + url[len("http://"):]
    destino = os.path.join(FOTOS, f"{reg['id']}.jpg")
    if os.path.exists(destino):
        return True
    # o servidor de fotos devolve 406 se o Accept pedir JSON, entao sobrescreve aqui
    r = get(url, headers={"Accept": "image/jpeg,image/*,*/*"})
    if not r or not r.content:
        return False
    try:
        im = Image.open(io.BytesIO(r.content))
        im = im.convert("RGB")
        w, h = im.size
        lado = min(w, h)
        # corta pelo centro na horizontal, puxando para o alto na vertical (rosto)
        esq = (w - lado) // 2
        topo = int((h - lado) * 0.18)
        im = im.crop((esq, topo, esq + lado, topo + lado)).resize((TAM, TAM), Image.LANCZOS)
        im.save(destino, "JPEG", quality=78, optimize=True, progressive=True)
        return True
    except Exception as erro:
        print(f"    foto falhou {reg['id']}: {erro}", flush=True)
        return False


def main():
    os.makedirs(FOTOS, exist_ok=True)
    os.makedirs(DADOS, exist_ok=True)

    print("coletando parlamentares...", flush=True)
    regs = deputados() + senadores()

    print(f"baixando {len(regs)} fotos...", flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = list(pool.map(baixa_foto, regs))

    for reg, teve in zip(regs, ok):
        reg["foto"] = f"fotos/{reg['id']}.jpg" if teve else None
        reg.pop("url_foto", None)

    regs.sort(key=lambda r: r["nome"].lower())
    caminho = os.path.join(DADOS, "parlamentares.json")
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump({
            "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "fontes": [
                "Câmara dos Deputados — Dados Abertos API v2",
                "Senado Federal — Dados Abertos",
            ],
            "total": len(regs),
            "com_foto": sum(ok),
            "parlamentares": regs,
        }, fh, ensure_ascii=False, separators=(",", ":"))

    peso = sum(os.path.getsize(os.path.join(FOTOS, f)) for f in os.listdir(FOTOS))
    print(f"\npronto: {len(regs)} parlamentares, {sum(ok)} com foto")
    print(f"  {caminho}  ({os.path.getsize(caminho)/1024:.0f} KB)")
    print(f"  {FOTOS}/  ({peso/1024/1024:.1f} MB, media {peso/max(sum(ok),1)/1024:.1f} KB por foto)")
    if sum(ok) < len(regs):
        print(f"  sem foto: {len(regs)-sum(ok)}")


if __name__ == "__main__":
    sys.exit(main())
