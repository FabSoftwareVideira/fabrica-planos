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


# Começos de célula que o Excel e o LibreOffice tratam como fórmula (CSV injection)
INICIO_DE_FORMULA = ('=', '+', '-', '@', '\t', '\r')


def sem_formula(valor):
    """O texto da célula, com um apóstrofo na frente se ele viraria fórmula na planilha. As observações vêm da
    IA a partir do texto do PDF, que quem envia o plano controla."""
    valor = '' if valor is None else str(valor)
    return "'" + valor if valor.startswith(INICIO_DE_FORMULA) else valor


def csv_em_bytes(linhas):
    """O CSV dessas linhas (mesmo formato do arquivo da validação), para baixar, sem fórmulas."""
    import io
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=COLUNAS, delimiter=';', quoting=csv.QUOTE_ALL, extrasaction='ignore')
    escritor.writeheader()
    for linha in linhas:
        escritor.writerow({k: sem_formula(v) for k, v in linha.items()})
    return ('\ufeff' + saida.getvalue()).encode('utf-8')


def ler_csv(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding='utf-8-sig', newline='') as arq:
        return list(csv.DictReader(arq, delimiter=';'))
