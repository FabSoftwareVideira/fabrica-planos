"""Matrizes curriculares dos PPCs, usadas para preencher a matriz de cada curso no banco na primeira vez
(armazenamento/ofertas.py). Depois disso, a coordenação monta cada semestre a partir dela, podendo renomear
disciplinas (as optativas, principalmente) e incluir disciplinas avulsas só naquele semestre.

Cada disciplina: (fase, código, nome, carga horária). As optativas não têm código fixo no PPC.

A sigla de cada curso vem das duas primeiras letras dos códigos do SIGAA (CCC0723 -> CC, LPC0701 -> LP); quando
elas não bastam, SIGLAS_SIGAA diz a sigla (INC0713-1 -> INFO). avaliacao/identificacao.py usa a mesma regra
para saber o curso pelo cabeçalho do plano."""

CURSOS = {
    'CC': 'Ciência da Computação',
    'LP': 'Pedagogia',
    'INFO': 'Técnico em Informática Integrado ao Ensino Médio',
}

# Prefixo dos códigos do SIGAA (duas letras) -> sigla do curso, quando forem diferentes. Os cursos integrados
# usam siglas mais longas (INFO), e o prefixo IN dos códigos (INC0713-1) seria ambíguo com outros que vierem.
SIGLAS_SIGAA = {
    'IN': 'INFO',
}

# Nível de cada curso: quem revisa os planos, além da coordenação, é o NDE na graduação e o NDB nos cursos
# técnicos integrados ao ensino médio. Sem nível definido, os dois papéis valem.
NIVEIS = {
    'CC': 'graduacao',
    'LP': 'graduacao',
    'INFO': 'integrado',
}
COLEGIADO = {'graduacao': 'nde', 'integrado': 'ndb'}


def sigla_do_codigo(prefixo):
    """Sigla do curso pelo prefixo de duas letras do código do componente no SIGAA."""
    return SIGLAS_SIGAA.get(prefixo, prefixo)


def colegiado(curso):
    """'nde', 'ndb' ou None (curso sem nível definido: os dois valem)."""
    return COLEGIADO.get(NIVEIS.get(curso))


def papel_vale(curso, papel):
    """A coordenação vale em todo curso; NDE e NDB, só no nível do curso (NDE na graduação, NDB no integrado)."""
    if papel not in COLEGIADO.values():
        return True
    return colegiado(curso) in (None, papel)


# Tipo de oferta de cada curso: 'semestral' (períodos 2027.1, 2027.2) ou 'anual' (período 2027). Sem tipo
# definido, vale semestral.
TIPOS = {
    'CC': 'semestral',
    'LP': 'semestral',  # ingresso anual, mas as disciplinas são por semestre (8 semestres)
    'INFO': 'anual',  # 3 anos; cada "fase" da matriz é um ano (série)
}

MATRIZES = {
    'CC': [
        (1, 'CCC0701', 'Algoritmos', 90),
        (1, 'CCC0702', 'Fundamentos da Computação', 60),
        (1, 'CCC0703', 'Fundamentos Matemáticos da Computação', 60),
        (1, 'CCC0704', 'Inglês Instrumental', 30),
        (1, 'CCC0705', 'Metodologia Científica', 30),
        (1, 'CCC0706', 'Pré-Cálculo', 60),
        (2, 'CCC0707', 'Álgebra Linear', 60),
        (2, 'CCC0708', 'Cálculo Diferencial e Integral I', 60),
        (2, 'CCC0709', 'Circuitos Digitais', 30),
        (2, 'CCC0710', 'Estrutura de Dados I', 60),
        (2, 'CCC0711', 'Ética e Legislação', 30),
        (2, 'CCC0712', 'Matemática Discreta', 60),
        (2, 'CCC0713', 'Programação Orientada a Objetos I', 60),
        (3, 'CCC0714', 'Arquitetura de Computadores', 60),
        (3, 'CCC0715', 'Banco de Dados I', 60),
        (3, 'CCC0716', 'Cálculo Diferencial e Integral II', 60),
        (3, 'CCC0717', 'Epistemologia e Filosofia', 30),
        (3, 'CCC0718', 'Estrutura de Dados II', 60),
        (3, 'CCC0719', 'Paradigmas de Programação', 30),
        (3, 'CCC0720', 'Programação Orientada a Objetos II', 60),
        (4, 'CCC0721', 'Banco de Dados II', 60),
        (4, 'CCC0722', 'Ciência, Tecnologia e Sociedade', 30),
        (4, 'CCC0723', 'Desenvolvimento Web I', 60),
        (4, 'CCC0724', 'Extensão e Pesquisa em Computação', 60),
        (4, 'CCC0725', 'Física', 30),
        (4, 'CCC0726', 'Métodos Numéricos', 60),
        (4, 'CCC0727', 'Sistemas Operacionais', 60),
        (5, 'CCC0728', 'Desenvolvimento Web II', 60),
        (5, 'CCC0729', 'Engenharia de Software I', 60),
        (5, 'CCC0730', 'Interação Humana com Dispositivos', 30),
        (5, 'CCC0731', 'Probabilidade e Estatística', 60),
        (5, 'CCC0732', 'Programação Lógica e Funcional', 30),
        (5, 'CCC0733', 'Projeto Aplicado I', 60),
        (5, 'CCC0734', 'Redes de Computadores I', 60),
        (6, 'CCC0735', 'Engenharia de Software II', 60),
        (6, 'CCC0736', 'Inteligência Artificial', 60),
        (6, 'CCC0737', 'Linguagens Formais e Autômatos', 60),
        (6, 'CCC0738', 'Projeto Aplicado II', 60),
        (6, 'CCC0739', 'Redes de Computadores II', 60),
        (6, '', 'Optativa I', 60),
        (7, 'CCC0740', 'Aprendizado de Máquina', 60),
        (7, 'CCC0741', 'Compiladores', 60),
        (7, 'CCC0742', 'Computação Gráfica', 60),
        (7, 'CCC0743', 'Projeto de Trabalho de Conclusão de Curso', 60),
        (7, 'CCC0744', 'Sistemas Embarcados', 60),
        (7, '', 'Optativa II', 60),
        (8, 'CCC0745', 'Ciência de Dados', 60),
        (8, 'CCC0746', 'Empreendedorismo', 60),
        (8, 'CCC0747', 'Segurança em Sistemas', 60),
        (8, 'CCC0748', 'Teoria da Computação', 60),
        (8, 'CCC0749', 'Trabalho de Conclusão de Curso', 60),
        (8, '', 'Optativa III', 60),
    ],
    # Licenciatura em Pedagogia (PPC 2024, matriz dos ingressantes a partir de 2023). Carga horária total do
    # componente (teórica + PCC + estágio), a que o SIGAA mostra. As optativas (30h) são escolhidas entre:
    # LPC0745 Educação Profissional e Tecnológica, LPC0746 Educação a Distância, LPC0747 Educação do Campo,
    # Indígena e Quilombola, LPC0748 Fundamentos da Matemática e LPC0749 a LPC0751 Tópicos Contemporâneos da
    # Educação I a III (a coordenação renomeia a optativa no período).
    'LP': [
        (1, 'LPC0701', 'Pesquisa e Processos Educativos I', 90),
        (1, 'LPC0702', 'Filosofia da Educação', 60),
        (1, 'LPC0703', 'Antropologia', 60),
        (1, 'LPC0704', 'Pedagogia e Profissão Docente', 60),
        (1, 'LPC0705', 'Leitura e Produção Textual', 60),
        (2, 'LPC0706', 'Pesquisa e Processos Educativos II', 90),
        (2, 'LPC0707', 'Educação, Sociedade e Trabalho', 60),
        (2, 'LPC0708', 'Infância e Pedagogia', 60),
        (2, 'LPC0709', 'História da Educação', 60),
        (2, 'LPC0710', 'Literatura e Educação', 60),
        (3, 'LPC0711', 'Pesquisa e Processos Educativos III', 90),
        (3, 'LPC0712', 'Infância e Educação Infantil', 60),
        (3, 'LPC0713', 'Psicologia da Educação', 60),
        (3, 'LPC0714', 'Linguística', 60),
        (3, 'LPC0715', 'Educação Especial', 30),
        (3, 'LPC0716', 'Fundamentos e Metodologia em Artes', 75),
        (4, 'LPC0717', 'Pesquisa e Processos Educativos IV', 90),
        (4, 'LPC0718', 'Alfabetização e Letramento I', 60),
        (4, 'LPC0719', 'Jogo, Brinquedo e Brincadeira', 60),
        (4, 'LPC0720', 'Fundamentos e Metodologia em Matemática', 75),
        (4, 'LPC0721', 'Didática-Geral', 60),
        (4, '', 'Optativa I', 30),
        (5, 'LPC0722', 'Pesquisa e Processos Educativos V', 90),
        (5, 'LPC0723', 'Alfabetização e Letramento II', 60),
        (5, 'LPC0724', 'Didática: Educação Infantil e Anos Iniciais', 60),
        (5, 'LPC0725', 'Fundamentos e Metodologia em Língua Portuguesa', 75),
        (5, 'LPC0726', 'Fundamentos e Metodologia em Ciências Naturais', 75),
        (5, 'LPC0727', 'Estágio Supervisionado I: Educação Infantil', 105),
        (6, 'LPC0728', 'Pesquisa e Processos Educativos VI', 90),
        (6, 'LPC0729', 'Teorias Educacionais e Curriculares', 60),
        (6, 'LPC0730', 'Políticas Públicas em Educação', 60),
        (6, 'LPC0731', 'Fundamentos e Metodologia de História', 75),
        (6, 'LPC0732', 'Fundamentos e Metodologia de Geografia', 75),
        (6, 'LPC0733', 'Estágio Supervisionado II: Educação Infantil', 90),
        (7, 'LPC0734', 'Pesquisa e Processos Educativos VII', 90),
        (7, 'LPC0735', 'Tecnologias Digitais da Informação e Comunicação na Educação', 60),
        (7, 'LPC0736', 'Linguagem, Corpo e Movimento', 60),
        (7, 'LPC0737', 'Gestão Educacional', 75),
        (7, 'LPC0738', 'Educação de Jovens e Adultos', 30),
        (7, 'LPC0739', 'Estágio Supervisionado III: Anos Iniciais do Ensino Fundamental', 105),
        (7, '', 'Optativa II', 30),
        (8, 'LPC0740', 'Pesquisa e Processos Educativos VIII', 30),
        (8, 'LPC0741', 'Gestão Escolar', 75),
        (8, 'LPC0742', 'Libras', 60),
        (8, 'LPC0743', 'Educação, Diversidade e Inclusão', 60),
        (8, 'LPC0744', 'Estágio Supervisionado IV: Anos Iniciais do Ensino Fundamental', 105),
        (8, '', 'Optativa III', 30),
    ],
    # Técnico em Informática Integrado ao Ensino Médio (PPC 2026): 3 anos, uma linha por componente e ano, como o
    # SIGAA oferta (Língua Portuguesa do 1º ano é um componente, a do 2º é outro). O PPC não traz os códigos do
    # SIGAA: a coordenação os preenche na disciplina, se quiser o aviso de código diferente no envio do plano.
    # Carga horária em hora-relógio, como na matriz do PPC (1º ano 1170h, 2º 1110h, 3º 960h). A Optativa I é
    # escolhida na lista do item 4.5.3 do PPC (a coordenação renomeia a optativa no período).
    'INFO': [
        (1, '', 'Artes I', 60),
        (1, '', 'Língua Estrangeira - Inglês I', 60),
        (1, '', 'Língua Portuguesa I', 90),
        (1, '', 'Filosofia I', 60),
        (1, '', 'Geografia I', 60),
        (1, '', 'História I', 60),
        (1, '', 'Biologia I', 60),
        (1, '', 'Física I', 60),
        (1, '', 'Química I', 60),
        (1, '', 'Matemática I', 120),
        (1, '', 'Educação Física I', 60),
        (1, '', 'Lógica de Programação', 120),
        (1, '', 'Fundamentos de Informática', 60),
        (1, '', 'Web Design', 60),
        (1, '', 'Multimídia', 60),
        (1, '', 'Hardware e Sistemas Operacionais', 120),
        (2, '', 'Artes II', 60),
        (2, '', 'Língua Estrangeira - Inglês II', 60),
        (2, '', 'Língua Portuguesa II', 90),
        (2, '', 'Filosofia II', 60),
        (2, '', 'Geografia II', 60),
        (2, '', 'História II', 60),
        (2, '', 'Sociologia I', 60),
        (2, '', 'Biologia II', 60),
        (2, '', 'Física II', 60),
        (2, '', 'Química II', 60),
        (2, '', 'Matemática II', 90),
        (2, '', 'Educação Física II', 60),
        (2, '', 'Programação I', 120),
        (2, '', 'Engenharia de Software', 60),
        (2, '', 'Banco de Dados', 90),
        (2, '', 'Redes', 60),
        (3, '', 'Língua Portuguesa III', 90),
        (3, '', 'Geografia III', 60),
        (3, '', 'História III', 60),
        (3, '', 'Sociologia II', 60),
        (3, '', 'Biologia III', 60),
        (3, '', 'Física III', 60),
        (3, '', 'Química III', 60),
        (3, '', 'Matemática III', 90),
        (3, '', 'Educação Física III', 60),
        (3, '', 'Programação II', 120),
        (3, '', 'Empreendedorismo', 60),
        (3, '', 'Desenvolvimento de Projetos em Informática', 120),
        (3, '', 'Optativa I', 60),
    ],
}

# Coordenação e NDE indicados no PPC, dados (pelo e-mail institucional) junto com a matriz, só na primeira vez
# que o curso entra no banco: depois, quem muda os papéis é a administração. Quem ainda não entrou no sistema
# já tem o papel no primeiro acesso.
EQUIPES = {
    'LP': {
        'coordenador': ['valdinei.marcolla@ifc.edu.br'],
        'nde': ['alexsandra.zanin@ifc.edu.br', 'claudio.bertotto@ifc.edu.br', 'jane.valter@ifc.edu.br',
                'jose.hilario@ifc.edu.br', 'josiani.silva@ifc.edu.br', 'luiza.kaim@ifc.edu.br',
                'sergio.correa@ifc.edu.br'],
    },
    # Técnico em Informática Integrado (PPC 2026, item 6.3): coordenação e NDB
    'INFO': {
        'coordenador': ['fabio.aresi@ifc.edu.br'],
        'ndb': ['angelita.zanella@ifc.edu.br', 'carlos.silva@ifc.edu.br', 'grazielle.garcia@ifc.edu.br',
                'fabio.aresi@ifc.edu.br', 'fabio.pinheiro@ifc.edu.br', 'fabricio.bizotto@ifc.edu.br',
                'lucilene.baerle@ifc.edu.br', 'tiago.goncalves@ifc.edu.br'],
    },
}
