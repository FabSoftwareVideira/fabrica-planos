import re

# Dados de identificação do cabeçalho do plano (SIGAA), usados para agrupar os resultados:
#   graduação (semestral): "CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)"
#   técnico (anual):       "INC0713-1 - WEB DESIGN (60h) - Turma: 03 (2026)"
#                          "Turma: [TÉCNICO EM INFORMÁTICA INTEGRADO AO ENSINO MÉDIO - IN07 (MT) - A (2026)]"
# As duas primeiras letras do código do componente identificam o curso (CC = Ciência da Computação).
# O período diz o tipo de oferta: "2026.2" é semestral (2º semestre), "2026" é anual.

# Nome dos cursos de graduação pela sigla; o técnico traz o nome no próprio plano.
CURSOS = {
    'CC': 'Ciência da Computação',
}

CABECALHO = 1500  # a identificação fica no início do documento

# Depois da carga horária vem a turma, mas o SIGAA às vezes quebra o cabeçalho com um "Turma:" vazio no
# meio ("(30h) Turma: - Turma: 01 (2026.2)"); por isso a turma é o primeiro "Turma:" seguido de um número
# ou letra, logo adiante. Sem ela, o plano ainda é identificado pelo código e pelo período.
COMPONENTE = re.compile(
    r'\b(?P<codigo>(?P<sigla>[A-Z]{2})[A-Z]?\d{3,6}(?:-\d+)?)\s*-\s*(?P<disciplina>.+?)\s*\((?P<ch>\d+)\s*h\)'
    r'(?:.{0,40}?Turma:\s*(?P<turma>[A-Za-z0-9]+)\b)?'
)
PERIODO = re.compile(r'\((?P<ano>(?:19|20)\d{2})(?:\.(?P<semestre>[12]))?\)')
TURMA_TECNICO = re.compile(r'Turma:\s*\[(?P<curso>[^\]]+?)\s*-\s*[A-Z]{2}\d{2}\b[^\]]*\]')

MINUSCULAS = {'a', 'ao', 'aos', 'as', 'à', 'da', 'das', 'de', 'do', 'dos', 'e', 'em', 'na', 'no', 'o', 'os', 'para'}


def _titulo(texto):
    """'TÉCNICO EM INFORMÁTICA' -> 'Técnico em Informática' (siglas curtas como 'I' e 'II' ficam)."""
    palavras = []
    for i, palavra in enumerate(texto.split()):
        minuscula = palavra.lower()
        if i and minuscula in MINUSCULAS:
            palavras.append(minuscula)
        elif re.fullmatch(r'[IVX]+', palavra):
            palavras.append(palavra)
        else:
            palavras.append(minuscula[:1].upper() + minuscula[1:])
    return ' '.join(palavras)


def extrair(texto):
    """Identificação do plano a partir do texto do PDF, ou None se o cabeçalho não for reconhecido."""
    cabecalho = ' '.join((texto or '')[:CABECALHO].split())
    componente = COMPONENTE.search(cabecalho)
    if not componente:
        return None
    periodo = PERIODO.search(cabecalho, componente.end())
    sigla = componente['sigla']
    tecnico = TURMA_TECNICO.search(cabecalho)
    curso = _titulo(tecnico['curso']) if tecnico else CURSOS.get(sigla, sigla)
    ano = periodo['ano'] if periodo else ''
    semestre = periodo['semestre'] if periodo else None
    return {
        'codigo': componente['codigo'],
        'disciplina': _titulo(componente['disciplina']),
        'carga_horaria': int(componente['ch']),
        'turma': componente['turma'] or '',
        'sigla_curso': sigla,
        'curso': curso,
        'ano': ano,
        'semestre': int(semestre) if semestre else None,
        'periodo': f'{ano}.{semestre}' if semestre else ano,
        'oferta': 'semestral' if semestre else ('anual' if ano else ''),
    }


def de_detalhes(det):
    """Identificação a partir do texto guardado nos detalhes do plano. Lê o texto de novo em vez de confiar
    na que foi gravada na validação, para que correções neste leitor valham sem validar outra vez."""
    if not det:
        return None
    return extrair(det.get('texto', '')) or det.get('identificacao_plano')
