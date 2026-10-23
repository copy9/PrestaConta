#!/usr/bin/env python3
"""Injeta dados/parlamentares.json dentro de template.html e grava prestaconta.html."""
import json, os, re, sys

TPL = "template.html"
SRC = "dados/parlamentares.json"
OUT = "prestaconta.html"
MARCA = "/*__DADOS__*/{}"

dados = json.load(open(SRC, encoding="utf-8"))

# o Senado publica o perfil em http; o navegador do artifact so abre https
for p in dados["parlamentares"]:
    if p.get("url_perfil", "").startswith("http://"):
        p["url_perfil"] = "https://" + p["url_perfil"][len("http://"):]

tpl = open(TPL, encoding="utf-8").read()
if MARCA not in tpl:
    sys.exit("marcador /*__DADOS__*/{} nao encontrado no template")

bloco = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
# nada dentro do JSON pode fechar a tag <script> antes da hora
bloco = bloco.replace("</", "<\\/")

html = tpl.replace(MARCA, bloco)
open(OUT, "w", encoding="utf-8").write(html)

faltam = [p["id"] for p in dados["parlamentares"] if not p.get("sp")]
print(f"{OUT}: {os.path.getsize(OUT)/1024:.0f} KB")
print(f"  {dados['total']} parlamentares, {dados['com_foto']} com foto")
print(f"  sem recorte de foto: {len(faltam)}")
# confere que toda foto citada existe em disco
import glob
sumidas = [f"sp{i}.jpg" for i in range(dados.get("sprite",{}).get("folhas",0)) if not os.path.exists(f"sp{i}.jpg")]
print(f"  folhas de sprite ausentes: {len(sumidas)}")
