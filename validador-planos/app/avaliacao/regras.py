import re

from .prompt import CAMPOS

# Porte do nó "Parsear Validação": regras determinísticas aplicadas sobre a resposta da IA.


def aplicar_regras(validacao, dados):
    nb = dados.get('refBasicas', 0)
    nc = dados.get('refComplementares', 0)
    ok_ref = nb >= 3 and nc >= 5
    validacao['referencias'] = {
        'status': 'OK' if ok_ref else 'INCOMPLETO',
        'obs': (
            f'{nb} referências básicas e {nc} complementares.' if ok_ref
            else f'{nb} referências básicas (mín. 3) e {nc} complementares (mín. 5).'
        ),
    }

    if dados.get('temObjGeral'):
        validacao['objetivos_geral'] = {'status': 'OK', 'obs': 'Objetivo geral preenchido.'}
    if dados.get('temObjEspecificos'):
        validacao['objetivos_especificos'] = {'status': 'OK', 'obs': 'Objetivos especificos preenchidos.'}
    # Horário decidido só por regra: muitos docentes só indicam onde consultar (Planus, quadro, PTD),
    # o que não informa ao estudante quando é o atendimento.
    texto_horario = ' '.join((dados.get('textoHorario') or '').split())
    if dados.get('temHorarioAtendimento'):
        validacao['horario_atendimento'] = {'status': 'OK', 'obs': 'Horário de atendimento informado.'}
    elif texto_horario:
        validacao['horario_atendimento'] = {
            'status': 'INCOMPLETO',
            'obs': f'Não informa dias e horários de atendimento; apenas indica onde consultá-los ("{texto_horario[:120]}").',
        }
    else:
        validacao['horario_atendimento'] = {'status': 'AUSENTE', 'obs': 'Horário de atendimento não preenchido.'}

    proc = validacao.get('procedimentos_avaliacao') or {}
    if proc.get('status') == 'INCOMPLETO' and re.search('interdisciplinar', proc.get('obs', ''), re.IGNORECASE):
        validacao['procedimentos_avaliacao'] = {'status': 'OK', 'obs': 'Instrumentos de avaliacao descritos.'}

    sts = [(validacao.get(campo) or {}).get('status') for campo in CAMPOS]
    if 'AUSENTE' in sts:
        validacao['status_geral'] = 'REPROVADO'
    elif 'INCOMPLETO' in sts:
        validacao['status_geral'] = 'PENDENTE'
    else:
        validacao['status_geral'] = 'OK'
    return validacao
