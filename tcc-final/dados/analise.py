"""Métricas do capítulo de resultados, a partir de validacoes_2026-10-19.csv.

Uso: python analise.py [anotacao_humana.csv]

Sem argumento, calcula as estatísticas descritivas e a concordância do critério
"Horário de Atendimento" com o oráculo estrutural (texto vazio entre o cabeçalho
e a seção seguinte). Com a planilha de anotação humana preenchida (mesmo formato
de anotacao_humana_modelo.csv), calcula precisão, recall, F1, acurácia e Kappa
de Cohen por critério, tratando INCOMPLETO e AUSENTE como "não conforme".
"""
import csv
import statistics as st
import sys
from collections import Counter
from pathlib import Path

AQUI = Path(__file__).parent
CAMPOS = ['Identificação', 'Ementa', 'Objetivos Geral', 'Objetivos Específicos',
          'Conteúdo Programático', 'Metodologia', 'Proc. Avaliação', 'Cronograma',
          'Avaliações', 'Horário Atendimento', 'Referências', 'Coerência']


def metricas(pares):
    """pares = [(referencia, sistema)] com True = não conforme (classe positiva)."""
    vp = sum(r and s for r, s in pares)
    fp = sum((not r) and s for r, s in pares)
    fn = sum(r and not s for r, s in pares)
    vn = sum((not r) and not s for r, s in pares)
    n = len(pares)
    prec = vp / (vp + fp) if vp + fp else float('nan')
    rec = vp / (vp + fn) if vp + fn else float('nan')
    f1 = 2 * prec * rec / (prec + rec) if vp else 0.0
    po = (vp + vn) / n
    pe = ((vp + fp) * (vp + fn) + (fn + vn) * (fp + vn)) / n ** 2
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    return dict(VP=vp, FP=fp, FN=fn, VN=vn, acuracia=po, precisao=prec, recall=rec, f1=f1, kappa=kappa)


def main():
    linhas = list(csv.DictReader(open(AQUI / 'validacoes_2026-10-19.csv', encoding='utf-8')))
    print(f'Planos: {len(linhas)}')
    print('Status geral:', dict(Counter(l['status_geral'] for l in linhas)))
    for c in CAMPOS:
        print(f'  {c:24s}', dict(Counter(l[c] for l in linhas)))

    for k in ['paginas', 'caracteres', 'tokens_prompt', 'tokens_resposta', 's_prompt', 's_geracao']:
        v = [float(l[k]) for l in linhas]
        print(f'{k:16s} min={min(v):.2f} max={max(v):.2f} media={st.mean(v):.2f} '
              f'mediana={st.median(v):.2f} dp={st.stdev(v):.2f}')
    tps = [float(l['tokens_resposta']) / float(l['s_geracao']) for l in linhas]
    print(f'Velocidade de geração: {st.mean(tps):.1f} tokens/s')

    pares = [(l['horario_texto_vazio'] == '1', l['Horário Atendimento'] != 'OK') for l in linhas]
    print('Horário x oráculo estrutural:', {k: round(v, 4) for k, v in metricas(pares).items()})

    if len(sys.argv) > 1:
        anot = {(a['plano'], a['criterio']): a['humano'].strip().upper()
                for a in csv.DictReader(open(sys.argv[1], encoding='utf-8')) if a['humano'].strip()}
        todos = []
        for c in CAMPOS:
            p = [(anot[(l['plano'], c)] != 'OK', l[c] != 'OK') for l in linhas if (l['plano'], c) in anot]
            todos += p
            if p:
                print(c, {k: round(v, 3) for k, v in metricas(p).items()})
        if todos:
            print('GERAL', {k: round(v, 3) for k, v in metricas(todos).items()})


if __name__ == '__main__':
    main()
