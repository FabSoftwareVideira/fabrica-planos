import csv
import os
from datetime import datetime

# Mesmas colunas e separador (;) que o workflow n8n gravava, para o dashboard e as planilhas continuarem compatíveis.

CAMPOS_COLUNA = [
    ('Ementa', 'ementa'),
    ('Metodologia', 'metodologia'),
    ('Proc. Avaliação', 'procedimentos_avaliacao'),
    ('Objetivos Geral', 'objetivos_geral'),
    ('Objetivos Específicos', 'objetivos_especificos'),
    ('Conteúdo Programático', 'conteudo_programatico'),
    ('Cronograma', 'cronograma'),
    ('Avaliações', 'avaliacoes'),
    ('Referências', 'referencias'),
    ('Identificação', 'identificacao'),
    ('Horário Atendimento', 'horario_atendimento'),
    ('Coerência', 'coerencia'),
]

COLUNAS = (
    ['Arquivo', 'Caminho PDF', 'Data Validação', 'Status Geral', 'Observação Geral']
    + [c for nome, _ in CAMPOS_COLUNA for c in (nome, nome + ' Obs')]
)


def linha_resultado(nome_arquivo, caminho, validacao, agora=None):
    agora = agora or datetime.now()

    def status(campo):
        return (validacao.get(campo) or {}).get('status') or 'ERRO'

    def obs(campo):
        return (validacao.get(campo) or {}).get('obs') or ''

    linha = {
        'Arquivo': nome_arquivo,
        'Caminho PDF': caminho,
        'Data Validação': agora.strftime('%d/%m/%Y, %H:%M:%S'),
        'Status Geral': validacao.get('status_geral') or 'ERRO',
        'Observação Geral': validacao.get('obs_geral') or '',
    }
    for nome, campo in CAMPOS_COLUNA:
        linha[nome] = status(campo)
        linha[nome + ' Obs'] = obs(campo)
    return linha


def escrever_csv(caminho, linhas):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, 'w', encoding='utf-8-sig', newline='') as arq:
        escritor = csv.DictWriter(arq, fieldnames=COLUNAS, delimiter=';', quoting=csv.QUOTE_ALL)
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow(linha)


def ler_csv(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding='utf-8-sig', newline='') as arq:
        return list(csv.DictReader(arq, delimiter=';'))
