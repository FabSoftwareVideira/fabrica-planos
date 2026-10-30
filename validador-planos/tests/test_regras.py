from app.regras import aplicar_regras


def _validacao_ok():
    return {
        'identificacao': {'status': 'OK', 'obs': ''},
        'ementa': {'status': 'OK', 'obs': ''},
        'metodologia': {'status': 'OK', 'obs': ''},
        'procedimentos_avaliacao': {'status': 'OK', 'obs': ''},
        'objetivos_geral': {'status': 'OK', 'obs': ''},
        'objetivos_especificos': {'status': 'OK', 'obs': ''},
        'conteudo_programatico': {'status': 'OK', 'obs': ''},
        'cronograma': {'status': 'OK', 'obs': ''},
        'avaliacoes': {'status': 'OK', 'obs': ''},
        'referencias': {'status': 'OK', 'obs': ''},
        'horario_atendimento': {'status': 'OK', 'obs': ''},
        'coerencia': {'status': 'OK', 'obs': ''},
        'status_geral': 'OK',
        'obs_geral': 'tudo certo',
    }


BASE = {
    'refBasicas': 3, 'refComplementares': 5,
    'temObjGeral': True, 'temObjEspecificos': True, 'temHorarioAtendimento': True,
}


def test_referencias_minimas_ok():
    v = aplicar_regras(_validacao_ok(), BASE)
    assert v['referencias']['status'] == 'OK'


def test_referencias_insuficientes_viram_pendente():
    v = aplicar_regras(_validacao_ok(), {**BASE, 'refBasicas': 2})
    assert v['referencias']['status'] == 'INCOMPLETO'
    assert v['status_geral'] == 'PENDENTE'


def test_ausente_da_ia_vira_reprovado():
    entrada = _validacao_ok()
    entrada['ementa'] = {'status': 'AUSENTE', 'obs': 'não há'}
    v = aplicar_regras(entrada, BASE)
    assert v['status_geral'] == 'REPROVADO'


def test_objetivo_preenchido_sobrescreve_ia():
    entrada = _validacao_ok()
    entrada['objetivos_geral'] = {'status': 'AUSENTE', 'obs': 'nao achei'}
    v = aplicar_regras(entrada, BASE)
    assert v['objetivos_geral'] == {'status': 'OK', 'obs': 'Objetivo geral preenchido.'}


def test_interdisciplinaridade_nao_reprova():
    entrada = _validacao_ok()
    entrada['procedimentos_avaliacao'] = {'status': 'INCOMPLETO', 'obs': 'falta interdisciplinaridade'}
    v = aplicar_regras(entrada, BASE)
    assert v['procedimentos_avaliacao']['status'] == 'OK'
    assert v['status_geral'] == 'OK'


def test_horario_detectado_sobrescreve_ia():
    entrada = _validacao_ok()
    entrada['horario_atendimento'] = {'status': 'INCOMPLETO', 'obs': 'sem dia'}
    v = aplicar_regras(entrada, {**BASE, 'temHorarioAtendimento': True, 'textoHorario': 'Terça 10:00'})
    assert v['horario_atendimento']['status'] == 'OK'


def test_horario_que_so_indica_onde_consultar_e_incompleto():
    v = aplicar_regras(_validacao_ok(), {
        **BASE, 'temHorarioAtendimento': False,
        'textoHorario': 'Disponível no quadro de horários do docente em:\nhttps://planus.sou.ifc.edu.br/',
    })
    assert v['horario_atendimento']['status'] == 'INCOMPLETO'
    assert 'https://planus.sou.ifc.edu.br/' in v['horario_atendimento']['obs']
    assert v['status_geral'] == 'PENDENTE'


def test_horario_vazio_e_ausente_mesmo_que_a_ia_diga_ok():
    v = aplicar_regras(_validacao_ok(), {**BASE, 'temHorarioAtendimento': False, 'textoHorario': '  '})
    assert v['horario_atendimento']['status'] == 'AUSENTE'
    assert v['status_geral'] == 'REPROVADO'
