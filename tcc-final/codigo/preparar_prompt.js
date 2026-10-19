return $input.all().map((item, index) => {
const sections = item.json;

// Recupera nome e id do arquivo do nó de busca (mantido no lineage do item)
const fileMeta = $('Search files and folders').itemMatching(index)?.json || {};
const fileName = fileMeta.name || 'arquivo_desconhecido';
const fileLink = fileMeta.id ? `https://drive.google.com/file/d/${fileMeta.id}/view` : '';

// Limites maiores para campos que precisam ser lidos por inteiro (ex.: contar referências)
const trunc = (str, max = 1500) => str ? str.substring(0, max) + (str.length > max ? '...' : '') : '(não preenchido)';

// ⚙️ CONFIGURE O MODELO AQUI (ex: qwen2.5:7b, qwen2.5:14b, llama3.2, gemma2)
const OLLAMA_MODEL = 'qwen2.5:7b';

// Schema imposto ao Ollama via "format": garante os campos e enums exatos na resposta
const campos = ['identificacao','ementa','metodologia','procedimentos_avaliacao','objetivos_geral','objetivos_especificos','conteudo_programatico','cronograma','avaliacoes','referencias','horario_atendimento','coerencia'];
const campoSchema = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['OK', 'INCOMPLETO', 'AUSENTE'] },
    obs: { type: 'string' }
  },
  required: ['status', 'obs']
};
const formatSchema = {
  type: 'object',
  properties: Object.fromEntries(campos.map(c => [c, campoSchema])),
  required: [...campos, 'status_geral', 'obs_geral']
};
formatSchema.properties.status_geral = { type: 'string', enum: ['OK', 'PENDENTE', 'REPROVADO'] };
formatSchema.properties.obs_geral = { type: 'string' };

const prompt = `Você é um avaliador de planos de ensino de uma instituição de ensino superior brasileira.
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

IDENTIFICAÇÃO (início do documento):
${trunc(sections.identificacao, 800)}

EMENTA:
${trunc(sections.ementa)}

METODOLOGIA:
${trunc(sections.metodologia)}

PROCEDIMENTOS DE AVALIAÇÃO:
${trunc(sections.procedimentos_avaliacao)}

OBJETIVOS GERAL:
${trunc(sections.objetivos_geral)}

OBJETIVOS ESPECÍFICOS:
${trunc(sections.objetivos_especificos)}

CONTEÚDO PROGRAMÁTICO:
${trunc(sections.conteudo_programatico, 2500)}

CRONOGRAMA:
${trunc(sections.cronograma, 2500)}

AVALIAÇÕES:
${trunc(sections.avaliacoes)}

HORÁRIO DE ATENDIMENTO:
${trunc(sections.horario_atendimento, 500)}

REFERÊNCIAS (CONTAGEM VERIFICADA — use exatamente estes números):
${sections.ref_basicas} referência(s) básica(s) e ${sections.ref_complementares} complementar(es).`;

return {
    json: {
      fileName,
      fileLink,
      refBasicas: sections.ref_basicas ?? 0,
      refComplementares: sections.ref_complementares ?? 0,
      temObjGeral: !!(sections.objetivos_geral || '').trim(),
      temObjEspecificos: !!(sections.objetivos_especificos || '').trim(),
      ollamaPayload: JSON.stringify({
        model: OLLAMA_MODEL,
        prompt,
        stream: false,
        format: formatSchema,
        keep_alive: '30m',
        // num_ctx 8192: maior prompt medido ~4,4k tokens (+ resposta ~300); 12288 não cabia na GPU de 6 GB
        options: { num_ctx: 8192, num_predict: 1500, temperature: 0.1 }
      }),
      // Payload alternativo para o Google Gemini (ver README, seção "Usar o Gemini")
      geminiPayload: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.1, responseMimeType: 'application/json' }
      })
    }
  };
});
