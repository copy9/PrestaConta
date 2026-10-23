#!/usr/bin/env python3
"""
Junta as 594 fotos em poucas folhas (sprites), porque o artifact aceita no
maximo 512 arquivos por versao. Cada parlamentar passa a guardar a folha,
a coluna e a linha onde o rosto dele esta.
"""
import json, os

from PIL import Image

CEL = 112      # lado da celula em pixels
COLS = 12
LINHAS = 9     # 108 rostos por folha
POR_FOLHA = COLS * LINHAS

dados = json.load(open("dados/parlamentares.json", encoding="utf-8"))
regs = dados["parlamentares"]          # ja vem ordenado por nome
regs = [r for r in regs if r.get("foto")]

folhas = (len(regs) + POR_FOLHA - 1) // POR_FOLHA
print(f"{len(regs)} rostos -> {folhas} folhas de {COLS}x{LINHAS}")

for f in range(folhas):
    lote = regs[f * POR_FOLHA:(f + 1) * POR_FOLHA]
    linhas_usadas = (len(lote) + COLS - 1) // COLS
    folha = Image.new("RGB", (COLS * CEL, linhas_usadas * CEL), (235, 236, 231))
    for i, reg in enumerate(lote):
        col, lin = i % COLS, i // COLS
        with Image.open(reg["foto"]) as im:
            im = im.convert("RGB")
            if im.size != (CEL, CEL):
                im = im.resize((CEL, CEL), Image.LANCZOS)
            folha.paste(im, (col * CEL, lin * CEL))
        reg["sp"] = [f, col, lin]
        reg.pop("foto", None)
    nome = f"sp{f}.jpg"
    folha.save(nome, "JPEG", quality=80, optimize=True, progressive=True)
    print(f"  {nome}: {len(lote)} rostos, {folha.size[0]}x{folha.size[1]}, "
          f"{os.path.getsize(nome)/1024:.0f} KB")

dados["sprite"] = {"cel": CEL, "cols": COLS, "folhas": folhas}
json.dump(dados, open("dados/parlamentares.json", "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))

peso = sum(os.path.getsize(f"sp{f}.jpg") for f in range(folhas))
print(f"total das folhas: {peso/1024/1024:.2f} MB em {folhas} arquivos")
