from app.secoes import analisar_texto, contar_referencias, tem_horario_atendimento

PLANO = """Plano de Ensino
Instituição: IFC  Componente: Fundamentos  Docente: Fulano
Ementa: Estudo dos fundamentos da computação e de seus conceitos básicos para estudantes.
Metodologia: aulas expositivas e práticas em laboratório.
Procedimentos de Avaliação da Aprendizagem: provas e trabalhos práticos.
Horário de Atendimento: segunda-feira, 14h às 16h
Programa
Objetivos Gerais: formar base conceitual
Objetivos Específicos: compreender algoritmos
Conteúdo Programático: unidade 1 e unidade 2
Cronograma: semana 1 a 10
Avaliações: prova 1 e prova 2
Referências Básicas
Livro Autor A. Título um. Editora X.
Livro Autor B. Título dois. Editora Y.
Livro Autor C. Título três. Editora Z.
Referências Complementares
Artigo Autor D. Título quatro.
"""


def test_separa_secoes_principais():
    sec = analisar_texto(PLANO)
    assert sec['ementa'].startswith('Estudo dos fundamentos')
    assert sec['metodologia'].startswith('aulas expositivas')
    assert 'provas' in sec['procedimentos_avaliacao']
    assert 'semana 1' in sec['cronograma']


def test_objetivos_gerais_e_especificos():
    sec = analisar_texto(PLANO)
    assert sec['objetivos_geral'].startswith('formar base')
    assert sec['objetivos_especificos'].startswith('compreender algoritmos')


def test_identificacao_pega_inicio_do_documento():
    sec = analisar_texto(PLANO)
    assert sec['identificacao'].startswith('Plano de Ensino')


def test_conta_referencias_por_tipo():
    basicas, complementares = contar_referencias(PLANO)
    assert basicas == 3
    assert complementares == 1


def test_horario_com_dia_ou_hora_e_positivo():
    assert tem_horario_atendimento('Horário de Atendimento: segunda-feira, 14h às 16h')
    assert tem_horario_atendimento('Horario de Atendimento\nQuarta 10:00 - 12:00')


def test_horario_sem_dia_nem_hora_e_negativo():
    texto = 'Horário de Atendimento: Conforme PTD no site oficial do IFC\n\nPrograma\nUnidade 1'
    assert not tem_horario_atendimento(texto)


def test_sem_secao_de_horario():
    assert not tem_horario_atendimento('texto qualquer sem seção')


def test_bloco_de_docentes_sai_da_ementa_e_vai_para_a_identificacao():
    texto = ('Plano de Ensino\n' + 'x' * 500 + '\nEmenta: Estudo de matrizes e determinantes.\n'
             'Matrícula Docente(s)\n1773245 FULANA DE TAL - 60h\nMetodologia: aulas.\n')
    sec = analisar_texto(texto)
    assert sec['ementa'] == 'Estudo de matrizes e determinantes.'
    assert 'FULANA DE TAL' in sec['identificacao']


def test_horario_usa_so_o_texto_da_secao():
    # Antes, a janela de 300 caracteres achava "12:00" na seção seguinte e marcava como informado.
    texto = 'Horário de Atendimento: https://planus.sou.ifc.edu.br\nPrograma\nObjetivos: aulas às 12:00\n'
    sec = analisar_texto(texto)
    assert sec['horario_atendimento'] == 'https://planus.sou.ifc.edu.br'
    assert sec['temHorarioAtendimento'] is False
