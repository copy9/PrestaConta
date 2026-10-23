# PrestaConta

Diretório dos **594 parlamentares em exercício** (513 deputados + 81 senadores) com foto
oficial, patrimônio declarado ao TSE eleição a eleição e a cota parlamentar nota a nota —
além de uma **teia de ligações** que mostra que empresas receberam dinheiro de que
gabinetes e quais fornecedores aparecem concentrados em poucos gabinetes.

Tudo vem de dados abertos oficiais. Não há nenhum número estimado, inferido ou inventado:
quando uma fonte não existe (emendas de autoria, por exemplo), a lente aparece marcada como
indisponível em vez de preenchida com chute.

## O que é cada coisa

| Caminho | Para que serve |
|---|---|
| `docs/` | O site pronto. É esta pasta que o GitHub Pages publica. |
| `docs/index.html` | A página inteira: HTML, CSS, JS e os dados embutidos. Nenhuma requisição externa. |
| `docs/sp0.jpg` … `sp5.jpg` | As 594 fotos empacotadas em 6 folhas (sprite sheets). |
| `template.html` | O código-fonte da página, com o marcador `/*__DADOS__*/{}` onde o JSON entra. **Edite aqui**, nunca no `docs/index.html`. |
| `dados/parlamentares.json` | O resultado da coleta: cadastro, cota, patrimônio e posição da foto. |
| `coleta.py` | Cadastro + fotos da Câmara e do Senado. Recorta cada foto para 128px. |
| `coleta2.py` | Detalhe de cada parlamentar + cota parlamentar da 57ª legislatura, nota por nota. |
| `coleta3.py` | Patrimônio declarado ao TSE (2014, 2018, 2022, 2026). |
| `sprites.py` | Junta as fotos nas 6 folhas e grava a posição de cada uma no JSON. |
| `build_site.py` | Gera `docs/` a partir do `template.html` + JSON. **Rode depois de qualquer alteração.** |
| `build.py` | Gera `prestaconta.html` (versão de um arquivo só, para o artifact do Claude). |

## Publicar no GitHub Pages

```bash
git init
git add .
git commit -m "PrestaConta: dados abertos da Câmara, do Senado e do TSE"
git branch -M main
git remote add origin git@github.com:SEU-USUARIO/prestaconta.git
git push -u origin main
```

Depois, no GitHub: **Settings → Pages → Build and deployment**

- Source: `Deploy from a branch`
- Branch: `main`, pasta `/docs`
- Save

Em um ou dois minutos o site fica em `https://SEU-USUARIO.github.io/prestaconta/`.

### Por que `/docs` e não a raiz

O Pages só publica a raiz do repositório ou a pasta `/docs`. Deixando o site em `docs/`,
os scripts de coleta, o `template.html` e o JSON bruto continuam no repositório sem virar
parte do site publicado.

O arquivo `docs/.nojekyll` precisa existir: sem ele o Pages passa tudo por um gerador que
descarta arquivos e pastas começando com `_`.

## Mexer no site

```bash
# 1. edite template.html
# 2. regenere a pasta publicada
python3 build_site.py
# 3. veja localmente antes de subir
python3 -m http.server 8000 --directory docs
#    abra http://localhost:8000
```

`docs/index.html` é **gerado**. Qualquer alteração feita direto nele se perde no próximo
`build_site.py`.

## Atualizar os dados

```bash
pip install -r requirements.txt

python3 coleta.py      # cadastro + fotos        (~3 min)
python3 coleta2.py     # cota parlamentar        (~8 min, é a parte longa)
python3 coleta3.py     # patrimônio do TSE       (precisa dos CSV do TSE, ver abaixo)
python3 sprites.py     # empacota as fotos
python3 build_site.py  # regenera docs/
```

Para o `coleta3.py`, baixe de `https://dadosabertos.tse.jus.br` os pacotes
`bem_candidato_<ano>` e `consulta_cand_<ano>` de 2014, 2018, 2022 e 2026, e descompacte os
arquivos `*_BRASIL.csv` dentro de `tse/x/`. São arquivos grandes (centenas de MB), por isso
ficam fora do repositório.

## Fontes

- **Câmara dos Deputados — Dados Abertos v2** · `dadosabertos.camara.leg.br/api/v2`
  cadastro, foto oficial e a cota parlamentar (`/deputados/{id}/despesas?idLegislatura=57`).
- **Senado Federal — Dados Abertos** · `legis.senado.leg.br/dadosabertos`
  cadastro e foto oficial.
- **TSE — Dados Abertos** · `cdn.tse.jus.br/estatistica/sead/odsele`
  bens declarados na candidatura, casados por CPF (deputados) ou nome+UF (senadores).

### O que o site não tem

- **Emendas de autoria.** Vêm do Portal da Transparência da CGU, que exige um token pessoal
  gerado com conta gov.br. Sem esse token a lente fica marcada como indisponível.
- **Quadro societário das empresas.** Fecharia o circuito empresa → sócio → político, mas
  depende da base de CNPJ da Receita Federal (`dadosabertos.rfb.gov.br`).
- **Cota do Senado (CEAPS).** Está em outra base, fora das APIs usadas aqui.

### Privacidade

O CPF dos deputados é lido da API da Câmara **apenas em memória**, para casar o cadastro com
o TSE, e é descartado em seguida. Nenhum CPF é gravado no JSON nem publicado.

### Licença dos dados

Os dados são públicos e de livre uso, dos portais de dados abertos da Câmara, do Senado e do
TSE. Um número conferido contra a fonte vale mais que um número repetido daqui: as páginas de
origem estão todas listadas na aba **Fontes** do site.
