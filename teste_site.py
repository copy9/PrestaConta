from playwright.sync_api import sync_playwright
U="http://127.0.0.1:8885/index.html"
falhas=[]
def ok(c,m):
    print(("OK    " if c else "FALHA ")+m)
    if not c: falhas.append(m)
GRUPO={"patrimonio":"m-dinheiro","campanha":"m-dinheiro","emendas":"m-dinheiro","cota":"m-dinheiro",
       "vinculos":"m-empresas","ligacoes":"m-empresas","votacoes":"m-congresso","composicao":"m-congresso"}
def vai(pg,t):
    g=GRUPO.get(t)
    if g:
        pg.click('.gbtn[data-menu="%s"]'%g); pg.wait_for_timeout(250)
        pg.click('#%s button[data-go="%s"]'%(g,t))
    else:
        pg.click('.tabs:not(.bottomnav) button[data-go="%s"]'%t)
with sync_playwright() as pw:
    b=pw.chromium.launch(); pg=b.new_page(viewport={"width":1440,"height":1000})
    pg.on("pageerror", lambda e: falhas.append("pageerror: "+str(e)))
    import time; t0=time.time()
    pg.goto(U, wait_until="domcontentloaded", timeout=120000); pg.wait_for_timeout(2000)
    print("carregou em %.1fs"%(time.time()-t0))

    for t in ["inicio","parlamentares","patrimonio","campanha","votacoes","emendas","vinculos","cota","ligacoes","composicao","fontes"]:
        vai(pg,t); pg.wait_for_timeout(500)
        vis=pg.eval_on_selector_all(".view","e=>e.filter(x=>!x.hidden).map(x=>x.id)")
        ok(vis==["view-"+t], "aba %s"%t)

    vai(pg,"vinculos"); pg.wait_for_timeout(1000)
    st=pg.eval_on_selector_all("#vi-stats div b","e=>e.map(x=>x.textContent)")
    ok(len(st)==5, "vinculos stats: %s"%st)
    n1=pg.eval_on_selector_all("#vi-parl tbody tr","e=>e.length")
    ok(n1>0, "socio = parlamentar: %d linhas"%n1)
    print("   1a:", pg.eval_on_selector_all("#vi-parl tbody tr:first-child td","e=>e.map(x=>x.textContent.trim().slice(0,34))"))
    n2=pg.eval_on_selector_all("#vi-doador tbody tr","e=>e.length")
    ok(n2>0, "socio = doador: %d linhas"%n2)
    print("   1a:", pg.eval_on_selector_all("#vi-doador tbody tr:first-child td","e=>e.map(x=>x.textContent.trim().slice(0,30))"))
    n3=pg.eval_on_selector_all("#vi-cadastro tbody tr","e=>e.length")
    ok(n3>0, "cadastro: %d linhas"%n3)
    pg.select_option("#vi-filtro","sit"); pg.wait_for_timeout(600)
    print("   so irregular:", pg.eval_on_selector("#vi-cad-achou","e=>e.textContent"))
    pg.select_option("#vi-filtro",""); pg.wait_for_timeout(400)

    # clicar numa empresa abre o detalhe com socios
    pg.locator("#vi-cadastro tbody .linkbtn").first.click(); pg.wait_for_timeout(800)
    ok(pg.locator("#dt-overlay").is_visible(), "detalhe da empresa abre: %r"%pg.eval_on_selector("#dt-titulo","e=>e.textContent")[:36])
    txt=pg.eval_on_selector("#dt-modal","e=>e.textContent")
    ok("dono" in txt.lower() or "Sócio" in txt, "detalhe traz o quadro societario")
    pg.click("#dt-fechar"); pg.wait_for_timeout(300)

    # ficha de quem tem vinculo
    pg.locator("#vi-parl tbody .linkbtn").first.click(); pg.wait_for_timeout(1000)
    vb=pg.eval_on_selector("#pl-vinculos","e=>e.textContent.trim()")
    ok(len(vb)>80, "ficha mostra bloco de vinculos (%d chars)"%len(vb))
    print("   trecho:", vb[:150].replace("\n"," "))

    # teia: lente de socios
    vai(pg,"ligacoes"); pg.wait_for_timeout(900)
    pg.click('#lg-lentes button[data-lente="socios"]'); pg.wait_for_timeout(900)
    n=pg.eval_on_selector_all(".rno","e=>e.length")
    ok(n>0, "lente socios: %d satelites, centro %r"%(n,pg.eval_on_selector(".rcentro b","e=>e.textContent")[:26]))
    pg.locator(".rno button").first.click(); pg.wait_for_timeout(800)
    ok(pg.locator("#dt-overlay").is_visible(), "detalhe do socio abre: %r"%pg.eval_on_selector("#dt-titulo","e=>e.textContent")[:30])
    pg.click("#dt-fechar"); pg.wait_for_timeout(300)

    # empresa da cota agora mostra socios
    pg.click('#lg-lentes button[data-lente="forn"]'); pg.wait_for_timeout(700)
    pg.locator(".rno button").first.click(); pg.wait_for_timeout(800)
    txt=pg.eval_on_selector("#dt-modal","e=>e.textContent")
    ok("dono" in txt.lower(), "detalhe de empresa da cota traz os donos")
    pg.click("#dt-fechar"); pg.wait_for_timeout(300)

    pg.set_viewport_size({"width":390,"height":844}); pg.wait_for_timeout(600)
    ok(not pg.evaluate("document.documentElement.scrollWidth>window.innerWidth+2"), "sem rolagem horizontal no celular")
    b.close()
print("\nfalhas:", falhas or "nenhuma")
