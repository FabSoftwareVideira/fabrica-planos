# TCC: texto final

Monografia do TCC no modelo LaTeX do IFC 2026 (abnTeX2). O projeto da primeira parte continua em `../tcc-escrito/`.

## Compilar

```bash
latexmk -pdf main.tex
```

Também compila no Overleaf: envie a pasta inteira e use `main.tex` como documento principal.

## Estrutura

| Pasta | Conteúdo |
|-------|----------|
| `conteudo/` | Capítulos: introdução, fundamentação, metodologia, desenvolvimento, resultados e conclusão |
| `figuras/` | Diagramas e gráficos em TikZ/pgfplots (editáveis) |
| `images/` | Print do dashboard (anonimizado) e gráfico de publicações |
| `codigo/` | Código dos nós do n8n, reproduzido nos apêndices |
| `dados/` | Resultado anonimizado da execução de 19/10/2026, planilha de anotação humana e `analise.py` |

## Antes de entregar

- Preencher a folha de aprovação (data da defesa e banca) em `pretextuais/folhadeaprovacao.tex`.
- Revisar dedicatória e agradecimentos (texto-base).
- Se for usar a folha de autorização, preencher matrícula e CPF em `pretextuais/folhadeautorizacao.tex` e descomentar no `main.tex`.
- Se o NDE anotar os critérios, rodar `python dados/analise.py dados/anotacao_humana.csv` e atualizar o Capítulo 5.
