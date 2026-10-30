# Porte do nó "Preparar Prompt" do workflow n8n: prompt e schema enviados ao Ollama.

CAMPOS = [
    'identificacao', 'ementa', 'metodologia', 'procedimentos_avaliacao',
    'objetivos_geral', 'objetivos_especificos', 'conteudo_programatico',
    'cronograma', 'avaliacoes', 'referencias', 'horario_atendimento', 'coerencia',
]

CAMPO_SCHEMA = {
    'type': 'object',
    'properties': {
        'status': {'type': 'string', 'enum': ['OK', 'INCOMPLETO', 'AUSENTE']},
        'obs': {'type': 'string'},
    },
    'required': ['status', 'obs'],
}

FORMAT_SCHEMA = {
    'type': 'object',
    'properties': {
        **{campo: CAMPO_SCHEMA for campo in CAMPOS},
        'status_geral': {'type': 'string', 'enum': ['OK', 'PENDENTE', 'REPROVADO']},
        'obs_geral': {'type': 'string'},
    },
    'required': CAMPOS + ['status_geral', 'obs_geral'],
}

INSTRUCOES = """Você é um avaliador de planos de ensino de uma instituição de ensino superior brasileira.
Avalie cada campo APENAS com base no texto fornecido abaixo. Não invente informações.
Retorne APENAS um JSON válido, sem texto adicional, sem markdown.
Responda SEMPRE em português brasileiro (pt-BR), inclusive todas as observações.

Status possíveis por campo:
- "AUSENTE": o texto do campo está vazio, é "(não preenchido)" ou não tem nenhuma relação com o campo
- "INCOMPLETO": há conteúdo relacionado, mas não atende às regras do campo
- "OK": o conteúdo atende às regras do campo
IMPORTANTE: se houver texto real e relacionado no campo, NUNCA use AUSENTE — escolha entre OK e INCOMPLETO.

Regras por campo:
- identificacao: OK se contiver nome da instituição, nome do componente curricular (disciplina) e nome do docente. Se faltar qualquer um dos três, INCOMPLETO e diga qual falta.
- ementa: OK se descrever os temas da disciplina em texto corrido com pelo menos 15 palavras.
- objetivos_geral: OK se houver qualquer texto preenchido.
- objetivos_especificos: OK se houver qualquer texto preenchido.
- conteudo_programatico: OK se listar os tópicos ou unidades de conteúdo a serem trabalhados.
- metodologia: OK se descrever COMO as aulas serão conduzidas (ex.: aulas expositivas, práticas, projetos, recursos didáticos).
- procedimentos_avaliacao: OK se descrever os instrumentos de avaliação. NÃO exija menção a interdisciplinaridade.
- cronograma: OK se apresentar datas, semanas ou qualquer distribuição temporal dos conteúdos.
- avaliacoes: OK se indicar as avaliações previstas (instrumentos, datas ou pesos).
- horario_atendimento: OK se informar dia(s) e/ou horário(s) de atendimento ao aluno.
- referencias: NÃO conte nada. Use a CONTAGEM VERIFICADA informada nos dados abaixo. OK somente se houver no mínimo 3 básicas E 5 complementares; caso contrário INCOMPLETO, informando na obs quantas há de cada tipo.
- coerencia: OK se os objetivos, a metodologia e os procedimentos de avaliação forem compatíveis entre si; aponte na obs qualquer contradição encontrada.

Status geral:
- "OK": todos os campos estão OK
- "PENDENTE": um ou mais campos estão INCOMPLETO (e nenhum AUSENTE)
- "REPROVADO": um ou mais campos estão AUSENTE

Formato de retorno (JSON puro):
{
  "identificacao": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "ementa": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "metodologia": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "procedimentos_avaliacao": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "objetivos_geral": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "objetivos_especificos": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "conteudo_programatico": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "cronograma": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "avaliacoes": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "referencias": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "horario_atendimento": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "coerencia": {"status": "OK|INCOMPLETO|AUSENTE", "obs": "observação curta"},
  "status_geral": "OK|PENDENTE|REPROVADO",
  "obs_geral": "resumo geral do plano em 1 frase"
}

DADOS DO PLANO DE ENSINO:

"""


# Caracteres de cada seção enviados à IA; o excedente é cortado.
LIMITE_PADRAO = 1500
LIMITES = {'identificacao': 800, 'conteudo_programatico': 2500, 'cronograma': 2500, 'horario_atendimento': 500}


def _trunc(sec, chave):
    texto = sec.get(chave, '')
    maximo = LIMITES.get(chave, LIMITE_PADRAO)
    if not texto:
        return '(não preenchido)'
    return texto[:maximo] + ('...' if len(texto) > maximo else '')


def build_prompt(sec):
    dados = (
        'IDENTIFICAÇÃO (início do documento):\n' + _trunc(sec, 'identificacao') + '\n\n'
        'EMENTA:\n' + _trunc(sec, 'ementa') + '\n\n'
        'METODOLOGIA:\n' + _trunc(sec, 'metodologia') + '\n\n'
        'PROCEDIMENTOS DE AVALIAÇÃO:\n' + _trunc(sec, 'procedimentos_avaliacao') + '\n\n'
        'OBJETIVOS GERAL:\n' + _trunc(sec, 'objetivos_geral') + '\n\n'
        'OBJETIVOS ESPECÍFICOS:\n' + _trunc(sec, 'objetivos_especificos') + '\n\n'
        'CONTEÚDO PROGRAMÁTICO:\n' + _trunc(sec, 'conteudo_programatico') + '\n\n'
        'CRONOGRAMA:\n' + _trunc(sec, 'cronograma') + '\n\n'
        'AVALIAÇÕES:\n' + _trunc(sec, 'avaliacoes') + '\n\n'
        'HORÁRIO DE ATENDIMENTO:\n' + _trunc(sec, 'horario_atendimento') + '\n\n'
        'REFERÊNCIAS (CONTAGEM VERIFICADA — use exatamente estes números):\n'
        + str(sec.get('ref_basicas', 0)) + ' referência(s) básica(s) e '
        + str(sec.get('ref_complementares', 0)) + ' complementar(es).'
    )
    return INSTRUCOES + dados
