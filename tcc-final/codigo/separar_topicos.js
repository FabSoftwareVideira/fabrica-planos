// ponytail: contagem de referencias feita em codigo — o LLM erra ao contar linhas de tabela.
// Ajuste TIPOS_MATERIAL se o PDF usar outros rotulos na coluna "Tipo de Material".
const TIPOS_MATERIAL = /^[ \t]*(Livro|Peri[oó]dico|Revista|Artigo|Outros|Site|Manual|Apostila|Norma|Disserta[cç][aã]o|Tese|V[ií]deo|Software|Anais|Cap[ií]tulo|E-?book)\s+\S/gim;
function contarRefs(bloco) {
  return ((bloco || '').match(TIPOS_MATERIAL) || []).length;
}
// start = início do cabeçalho (onde a seção anterior termina), position = início do conteúdo
function findSection(text, pattern) {
  const match = new RegExp(pattern, 'im').exec(text);
  return match ? { start: match.index, position: match.index + match[0].length } : null;
}

// Cabeçalhos ancorados no início da linha (template SIGAA); tolerantes a caixa e à falta de acentos.
// Sem a âncora, "As avaliações..." no meio do texto era tomado como a seção Avaliações.
const sectionDefs = [
  { key: 'ementa', pattern: '^Ementa\\s*:?' },
  { key: 'metodologia', pattern: '^Metodologia\\s*:' },
  { key: 'procedimentos_avaliacao', pattern: '^Procedimentos\\s+de\\s+Avalia[çc][ãa]o(\\s+da\\s+Aprendizagem)?\\s*:?' },
  { key: 'horario_atendimento', pattern: '^Hor[áa]rio\\s+de\\s+Atendimento\\s*:?' },
  { key: 'programa', pattern: '^Programa[ \\t]*$' }, // só marca o fim do horário de atendimento
  { key: 'objetivos', pattern: '^Objetivos?(\\s+Gerais?)?\\s*:' },
  { key: 'conteudo_programatico', pattern: '^Conte[úu]do\\s+Program[áa]tico\\s*:?' },
  { key: 'cronograma', pattern: '^Cronograma' },
  { key: 'avaliacoes', pattern: '^Avalia[çc][õo]es\\s*:?[ \\t]*$' },
  { key: 'referencias', pattern: '^Refer[êe]ncias(\\s+B[áa]sicas|\\s+Bibliogr[áa]ficas)?\\s*:?' }
];

return $input.all().map(item => {
  const text = item.json.text || '';

  const sectionPositions = sectionDefs
    .map(s => {
      const found = findSection(text, s.pattern);
      return found ? { key: s.key, ...found } : null;
    })
    .filter(Boolean)
    .sort((a, b) => a.position - b.position);

  const result = {};
  result.identificacao = text.substring(0, 500).trim();

  for (let i = 0; i < sectionPositions.length; i++) {
    const cur = sectionPositions[i];
    const next = sectionPositions[i + 1];
    const content = text.substring(cur.position, next ? next.start : text.length).trim();

    if (cur.key === 'objetivos') {
      // Aceita "GERAL:", "Objetivo Geral", "ESPECÍFICOS:", "Objetivos Específicos" etc.
      const geralMatch = /(OBJETIVO\s+)?GERAL\s*:?/i.exec(content);
      const espMatch = /(OBJETIVOS?\s+)?ESPEC[ÍI]FICOS?\s*:?/i.exec(content);
      const geralEnd = espMatch ? espMatch.index : content.length;
      result.objetivos_geral = geralMatch
        ? content.substring(geralMatch.index + geralMatch[0].length, geralEnd).trim()
        : (espMatch ? content.substring(0, espMatch.index).trim() : content);
      result.objetivos_especificos = espMatch
        ? content.substring(espMatch.index + espMatch[0].length).trim()
        : '';
    } else {
      result[cur.key] = content;
    }
  }

  const iBas = text.search(/Refer[êe]ncias\s+B[áa]sicas/i);
  const iCom = text.search(/Refer[êe]ncias\s+Complementares/i);
  result.ref_basicas = iBas >= 0 ? contarRefs(text.slice(iBas, iCom > iBas ? iCom : text.length)) : 0;
  result.ref_complementares = iCom >= 0 ? contarRefs(text.slice(iCom)) : 0;

  return { json: result };
});
