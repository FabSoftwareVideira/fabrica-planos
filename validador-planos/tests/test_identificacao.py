from app.avaliacao.identificacao import de_detalhes, extrair

CABECALHO = 'Ministério da Educação\nInstituto Federal Catarinense\nPlano de Ensino\n'


def test_graduacao_semestral():
    ident = extrair(CABECALHO + 'Turma: CCC0707 - ÁLGEBRA LINEAR (60h) - Turma: 01 (2026.2)\nHorário: 2M123')
    assert ident == {
        'codigo': 'CCC0707', 'disciplina': 'Álgebra Linear', 'carga_horaria': 60, 'turma': '01',
        'sigla_curso': 'CC', 'curso': 'Ciência da Computação', 'ano': '2026', 'semestre': 2,
        'periodo': '2026.2', 'oferta': 'semestral',
    }


def test_periodo_em_outra_linha():
    # Em alguns PDFs o SIGAA quebra a linha antes do período.
    ident = extrair(CABECALHO + 'CCC0711 - ÉTICA E LEGISLAÇÃO (30h) - Turma: 01\nTurma:\n(2026.2)\nHorário: 4N12')
    assert (ident['disciplina'], ident['periodo'], ident['semestre']) == ('Ética e Legislação', '2026.2', 2)


def test_rotulo_turma_vazio_antes_da_turma():
    # "2026-2 Tecnologia Ciência e Sociedade": o SIGAA põe um "Turma:" vazio entre a carga horária e a turma.
    ident = extrair(CABECALHO + 'CCC0722 - CIÊNCIA, TECNOLOGIA E SOCIEDADE (30h)\nTurma:\n- Turma: 01 (2026.2)\n'
                    'Horário: 5N12')
    assert ident['codigo'] == 'CCC0722' and ident['disciplina'] == 'Ciência, Tecnologia e Sociedade'
    assert (ident['turma'], ident['curso'], ident['periodo']) == ('01', 'Ciência da Computação', '2026.2')


def test_sem_turma_ainda_identifica_curso_e_periodo():
    ident = extrair('CCC0722 - CIÊNCIA, TECNOLOGIA E SOCIEDADE (30h)\n(2026.2)')
    assert (ident['turma'], ident['sigla_curso'], ident['periodo']) == ('', 'CC', '2026.2')


def test_tecnico_anual_traz_o_nome_do_curso():
    ident = extrair(CABECALHO + 'INC0713-1 - WEB DESIGN (60h) - Turma: 03 (2026)\n'
                    'Turma: [TÉCNICO EM INFORMÁTICA INTEGRADO AO ENSINO\nMÉDIO - IN07 (MT) - A (2026)]')
    assert ident['codigo'] == 'INC0713-1' and ident['sigla_curso'] == 'IN'
    assert ident['curso'] == 'Técnico em Informática Integrado ao Ensino Médio'
    assert (ident['periodo'], ident['semestre'], ident['oferta']) == ('2026', None, 'anual')


def test_curso_sem_nome_conhecido_usa_a_sigla_e_mantem_numerais():
    ident = extrair('ADS0101 - DESENVOLVIMENTO WEB II (60h) - Turma: 02 (2027.1)')
    assert (ident['curso'], ident['disciplina'], ident['periodo']) == ('AD', 'Desenvolvimento Web II', '2027.1')


def test_cabecalho_nao_reconhecido():
    assert extrair('Um PDF qualquer, sem o cabeçalho do SIGAA') is None
    assert extrair('') is None


def test_de_detalhes_le_o_texto_de_novo():
    assert de_detalhes(None) is None
    # Gravado como não identificado por uma versão anterior do leitor: vale o que o texto diz hoje.
    det = {'identificacao_plano': None, 'texto': 'CCC0722 - CTS (30h)\nTurma:\n- Turma: 01 (2026.2)'}
    assert de_detalhes(det)['periodo'] == '2026.2'
    assert de_detalhes({'texto': 'CCC0707 - X (60h) - Turma: 01 (2026.2)'})['periodo'] == '2026.2'  # validação antiga
    assert de_detalhes({'identificacao_plano': {'periodo': '2026.1'}})['periodo'] == '2026.1'  # sem texto guardado
