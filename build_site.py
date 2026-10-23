#!/usr/bin/env python3
"""
Monta a pasta 'site/' com um index.html que roda sozinho em qualquer servidor
estatico (GitHub Pages, Netlify, Vercel, Apache) ou aberto direto no navegador.

Por que este passo existe: o arquivo publicado como artifact nao tem <!doctype>,
<html>, <head> nem <body> — a plataforma embrulha isso. Fora dela, o embrulho
tem de vir aqui, e junto com ele o reset de CSS. O mais importante do reset e
[hidden]{display:none!important}: as abas do site usam el.hidden, mas .view tem
display:grid, que vence o [hidden] padrao do navegador. Sem essa linha, todas as
abas aparecem empilhadas na mesma tela.

Uso:
  python3 build_site.py              # dados embutidos no html (abre ate por file://)
  python3 build_site.py --externo    # dados num .json a parte (precisa de servidor)
"""
import json, os, re, shutil, sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(RAIZ, "template.html")
DADOS = os.path.join(RAIZ, "dados", "parlamentares.json")
SAIDA = os.path.join(RAIZ, "docs")
MARCA = "/*__DADOS__*/{}"

RESET = """
/* --- reset minimo: fora do artifact, o embrulho e o reset vem daqui --- */
html,body{margin:0;padding:0}
img{max-width:100%}
[hidden]{display:none!important}
:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
"""

externo = "--externo" in sys.argv

dados = json.load(open(DADOS, encoding="utf-8"))
for p in dados["parlamentares"]:
    if p.get("url_perfil", "").startswith("http://"):
        p["url_perfil"] = "https://" + p["url_perfil"][len("http://"):]

tpl = open(TPL, encoding="utf-8").read()
if MARCA not in tpl:
    sys.exit("marcador /*__DADOS__*/{} nao encontrado no template")

bloco = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))

if externo:
    corpo = tpl.replace(
        "<script>\nvar DADOS = " + MARCA + ";\n</script>",
        '<script>var DADOS={parlamentares:[]};</script>')
    # carrega o json antes de rodar o app
    corpo = corpo.replace("<script>\n(function(){", """<script>
(function(){
function iniciar(){""", 1)
    corpo = corpo.replace("})();\n</script>", """}
fetch("dados.json").then(function(r){return r.json();}).then(function(j){DADOS=j;iniciar();})
  .catch(function(){document.body.insertAdjacentHTML("afterbegin",
    '<p style="padding:24px">Nao consegui carregar dados.json. Esta pagina precisa de um servidor web; abrir o arquivo direto do disco nao funciona nesta versao.</p>');});
})();
</script>""", 1)
else:
    corpo = tpl.replace(MARCA, bloco.replace("</", "<\\/"))

# separa cabeca (ate o fim do <style>) do corpo
corte = corpo.index("</style>") + len("</style>")
cabeca, resto = corpo[:corte], corpo[corte:]
cabeca = cabeca.replace("</style>", RESET + "</style>")
# metas e title so fazem sentido dentro do artifact; fora dele viram lixo
cabeca = re.sub(r'<meta name="claude:[^>]*>\s*', "", cabeca)

titulo = re.search(r"<title>(.*?)</title>", cabeca)
titulo = titulo.group(1) if titulo else "PrestaConta"

html = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Diretorio dos 594 parlamentares em exercicio, com foto oficial, patrimonio declarado ao TSE e a cota parlamentar nota a nota. Dados abertos da Camara, do Senado e do TSE.">
<meta name="color-scheme" content="dark light">
{cabeca}
</head>
<body>
{resto}
</body>
</html>
"""

folhas = dados.get("sprite", {}).get("folhas", 0)


def onde_esta_a_folha(i):
    """As folhas podem estar na raiz (maquina de coleta) ou so em docs/ (clone)."""
    for base in (RAIZ, SAIDA):
        p = os.path.join(base, f"sp{i}.jpg")
        if os.path.exists(p):
            return p
    sys.exit(f"sp{i}.jpg nao encontrado nem na raiz nem em docs/")


# Guarda as folhas antes de mexer em qualquer coisa: se elas so existem em docs/,
# copiar docs/ -> raiz depois de reescrever docs/ apagaria a origem.
folha_origem = [onde_esta_a_folha(i) for i in range(folhas)]


def escreve_site(destino):
    os.makedirs(destino, exist_ok=True)
    open(os.path.join(destino, "index.html"), "w", encoding="utf-8").write(html)
    for i, orig in enumerate(folha_origem):
        alvo = os.path.join(destino, f"sp{i}.jpg")
        if os.path.abspath(orig) != os.path.abspath(alvo):
            shutil.copy(orig, alvo)
    if externo:
        open(os.path.join(destino, "dados.json"), "w", encoding="utf-8").write(bloco)
    # sem isto o Pages passa tudo por um gerador que descarta arquivos com _
    open(os.path.join(destino, ".nojekyll"), "w").close()


# O site vai para os dois lugares de proposito: assim o GitHub Pages serve a
# pagina tanto configurado na pasta /docs quanto na raiz (/), que e onde o Pages
# mostraria o README se nao houvesse index.html. Ninguem precisa acertar a
# configuracao para o site abrir.
escreve_site(SAIDA)
escreve_site(RAIZ)

tam = os.path.getsize(os.path.join(SAIDA, "index.html")) / 1024
total = sum(os.path.getsize(os.path.join(SAIDA, f)) for f in os.listdir(SAIDA))
print(f"site pronto em docs/ e na raiz ({'dados externos' if externo else 'dados embutidos'})")
print(f"  index.html  {tam:.0f} KB")
print(f"  {folhas} folhas de foto")
print(f"  cada copia  {total/1024/1024:.2f} MB")
