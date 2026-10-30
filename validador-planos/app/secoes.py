import re

# Porte direto do nó "Separar Texto por Tópicos" do workflow n8n.

TIPOS_MATERIAL = re.compile(
    r'^[ \t]*(Livro|Peri[oó]dico|Revista|Artigo|Outros|Site|Manual|Apostila|Norma|'
    r'Disserta[cç][aã]o|Tese|V[ií]deo|Software|Anais|Cap[ií]tulo|E-?book)\s+\S',
    re.IGNORECASE | re.MULTILINE,
)

# Cabeçalhos ancorados no início da linha (template SIGAA), tolerantes a caixa e a acentos.
SECTION_DEFS = [
    ('ementa', r'^Ementa\s*:?'),
    ('metodologia', r'^Metodologia\s*:'),
    ('procedimentos_avaliacao', r'^Procedimentos\s+de\s+Avalia[çc][ãa]o(\s+da\s+Aprendizagem)?\s*:?'),
    ('horario_atendimento', r'^Hor[áa]rio\s+de\s+Atendimento\s*:?'),
    ('programa', r'^Programa[ \t]*$'),
    ('objetivos', r'^Objetivos?(\s+Gerais?)?\s*:'),
    ('conteudo_programatico', r'^Conte[úu]do\s+Program[áa]tico\s*:?'),
    ('cronograma', r'^Cronograma'),
    ('avaliacoes', r'^Avalia[çc][õo]es\s*:?[ \t]*$'),
    ('referencias', r'^Refer[êe]ncias(\s+B[áa]sicas|\s+Bibliogr[áa]ficas)?\s*:?'),
]

HORARIO_CABECALHO = re.compile(r'Hor[^ ]*rio[ ]+de[ ]+Atend', re.IGNORECASE)
HORARIO_DIA_OU_HORA = re.compile(
    r'(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|[0-9]{1,2}[:h][0-9]{0,2})',
    re.IGNORECASE,
)


def _objetivos(content):
    geral = re.search(r'(OBJETIVO\s+)?GERAL\s*:?', content, re.IGNORECASE)
    esp = re.search(r'(OBJETIVOS?\s+)?ESPEC[ÍI]FICOS?\s*:?', content, re.IGNORECASE)
    if geral:
        fim = esp.start() if esp else len(content)
        objetivo_geral = content[geral.end():fim].strip()
    elif esp:
        objetivo_geral = content[:esp.start()].strip()
    else:
        objetivo_geral = content
    objetivos_especificos = content[esp.end():].strip() if esp else ''
    return {'objetivos_geral': objetivo_geral, 'objetivos_especificos': objetivos_especificos}


def contar_refs(bloco):
    return len(TIPOS_MATERIAL.findall(bloco or ''))


def contar_referencias(text):
    basica = re.search(r'Refer[êe]ncias\s+B[áa]sicas', text, re.IGNORECASE)
    complementar = re.search(r'Refer[êe]ncias\s+Complementares', text, re.IGNORECASE)
    pos_b = basica.start() if basica else -1
    pos_c = complementar.start() if complementar else -1
    if pos_b >= 0:
        fim = pos_c if pos_c > pos_b else len(text)
        n_basicas = contar_refs(text[pos_b:fim])
    else:
        n_basicas = 0
    n_complementares = contar_refs(text[pos_c:]) if pos_c >= 0 else 0
    return n_basicas, n_complementares


def tem_horario_atendimento(text):
    cabecalho = HORARIO_CABECALHO.search(text)
    if not cabecalho:
        return False
    janela = text[cabecalho.start():cabecalho.start() + 300]
    return bool(HORARIO_DIA_OU_HORA.search(janela))


def analisar_texto(text):
    encontradas = []
    for chave, padrao in SECTION_DEFS:
        m = re.search(padrao, text, re.IGNORECASE | re.MULTILINE)
        if m:
            encontradas.append({'key': chave, 'start': m.start(), 'position': m.end()})
    encontradas.sort(key=lambda s: s['position'])

    result = {'identificacao': text[:500].strip()}
    for i, atual in enumerate(encontradas):
        proxima = encontradas[i + 1] if i + 1 < len(encontradas) else None
        fim = proxima['start'] if proxima else len(text)
        content = text[atual['position']:fim].strip()
        if atual['key'] == 'objetivos':
            result.update(_objetivos(content))
        else:
            result[atual['key']] = content

    n_basicas, n_complementares = contar_referencias(text)
    result['ref_basicas'] = n_basicas
    result['ref_complementares'] = n_complementares
    result['temHorarioAtendimento'] = tem_horario_atendimento(text)
    return result
