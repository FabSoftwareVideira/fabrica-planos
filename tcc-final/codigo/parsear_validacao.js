const CAMPOS = ['identificacao','ementa','metodologia','procedimentos_avaliacao','objetivos_geral','objetivos_especificos','conteudo_programatico','cronograma','avaliacoes','referencias','horario_atendimento','coerencia'];

function extrairJson(rawText) {
  const m = (rawText || '').match(/\{[\s\S]*\}/);
  const v = JSON.parse(m ? m[0] : rawText);
  if (!v.status_geral) throw new Error('JSON sem status_geral');
  return v;
}

const out = [];
const items = $input.all();

for (let index = 0; index < items.length; index++) {
  const item = items[index];
  const prep = $('Preparar Prompt').itemMatching(index)?.json || {};
  const fileName = prep.fileName || 'arquivo_desconhecido';
  const fileLink = prep.fileLink || '';

  let validacao = null;
  let ultimoErro = '';

  // Erro reportado pelo nó HTTP (timeout, conexão etc.) — mostra a causa real na planilha
  const errHttp = item.json.error?.message || (typeof item.json.error === 'string' ? item.json.error : '');

  try {
    // Ollama: response.response · Gemini: candidates[0].content.parts[0].text
    const rawText = item.json.response
      || item.json.candidates?.[0]?.content?.parts?.[0]?.text
      || '';
    validacao = extrairJson(rawText);
  } catch (e) {
    ultimoErro = errHttp || e.message;
  }

  if (!validacao) {
    validacao = {
      status_geral: 'ERRO',
      obs_geral: 'Falha ao processar resposta da IA: ' + ultimoErro
    };
  }

  // ponytail: contagem deterministica do node "Separar Texto por Topicos" vence a da IA
  if (validacao.status_geral !== 'ERRO') {
    const nb = prep.refBasicas ?? 0;
    const nc = prep.refComplementares ?? 0;
    const okRef = nb >= 3 && nc >= 5;
    validacao.referencias = {
      status: okRef ? 'OK' : 'INCOMPLETO',
      obs: okRef
        ? `${nb} referências básicas e ${nc} complementares.`
        : `${nb} referências básicas (mín. 3) e ${nc} complementares (mín. 5).`
    };
    // ponytail: objetivo preenchido = OK, qualquer que seja a redacao
    if (prep.temObjGeral) validacao.objetivos_geral = { status: 'OK', obs: 'Objetivo geral preenchido.' };
    if (prep.temObjEspecificos) validacao.objetivos_especificos = { status: 'OK', obs: 'Objetivos especificos preenchidos.' };

    // ponytail: interdisciplinaridade nao reprova — rede de seguranca caso o modelo ainda cobre
    if (validacao.procedimentos_avaliacao?.status === 'INCOMPLETO' && /interdisciplinar/i.test(validacao.procedimentos_avaliacao.obs || '')) {
      validacao.procedimentos_avaliacao = { status: 'OK', obs: 'Instrumentos de avaliacao descritos.' };
    }

    const sts = CAMPOS.map(f => validacao[f]?.status);
    validacao.status_geral = sts.includes('AUSENTE') ? 'REPROVADO'
      : sts.includes('INCOMPLETO') ? 'PENDENTE' : 'OK';
  }

  const s = (field) => validacao[field]?.status || 'ERRO';
  const o = (field) => validacao[field]?.obs || '';

  out.push({
    json: {
      'Arquivo': fileName,
      'Link PDF': fileLink,
      'Data Validação': new Date().toLocaleString('pt-BR'),
      'Status Geral': validacao.status_geral || 'ERRO',
      'Observação Geral': validacao.obs_geral || '',
      'Ementa': s('ementa'),
      'Ementa Obs': o('ementa'),
      'Metodologia': s('metodologia'),
      'Metodologia Obs': o('metodologia'),
      'Proc. Avaliação': s('procedimentos_avaliacao'),
      'Proc. Avaliação Obs': o('procedimentos_avaliacao'),
      'Objetivos Geral': s('objetivos_geral'),
      'Objetivos Geral Obs': o('objetivos_geral'),
      'Objetivos Específicos': s('objetivos_especificos'),
      'Objetivos Específicos Obs': o('objetivos_especificos'),
      'Conteúdo Programático': s('conteudo_programatico'),
      'Conteúdo Programático Obs': o('conteudo_programatico'),
      'Cronograma': s('cronograma'),
      'Cronograma Obs': o('cronograma'),
      'Avaliações': s('avaliacoes'),
      'Avaliações Obs': o('avaliacoes'),
      'Referências': s('referencias'),
      'Referências Obs': o('referencias'),
      'Identificação': s('identificacao'),
      'Identificação Obs': o('identificacao'),
      'Horário Atendimento': s('horario_atendimento'),
      'Horário Atendimento Obs': o('horario_atendimento'),
      'Coerência': s('coerencia'),
      'Coerência Obs': o('coerencia')
    }
  });
}

return out;
