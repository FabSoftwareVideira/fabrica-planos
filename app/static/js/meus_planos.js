// "Meus planos": as disciplinas do professor, separadas por período letivo (o atual e o próximo primeiro) e
// filtradas pela etapa (a fazer, em andamento, assinados). Cada disciplina é uma linha com a situação e a ação
// principal (enviar, enviar nova versão, assinar); ao abri-la aparecem a versão atual (PDF, relatório, excluir), os
// avisos, a assinatura e as versões anteriores. MAX_MB, ASSINATURA_API e DESTAQUES ({período: 'Atual' | 'Próximo'}) vêm da
// página; $, msg, hora e corpo, de status.js (a barra de status, carregada antes).
const CORES = { OK: '#168821', PENDENTE: '#a15c00', INCOMPLETO: '#a15c00' };
const ROTULOS_REVISAO = { OK: 'Aprovado', PENDENTE: 'Ajustes necessários', REPROVADO: 'Reprovado' };
let timerLista, planos = [], periodoEscolhido = '', filtro = '', busca = '', voltarPara = '';
const abertos = new Set();  // disciplinas abertas (oferta_id), mantidas quando a lista recarrega
const ETAPAS = [['fazer', 'A fazer'], ['andamento', 'Em andamento'], ['assinados', 'Assinados'], ['todas', 'Todas']];
const BUSCA_A_PARTIR_DE = 7;  // com mais disciplinas no período que isso, aparece a busca

function selo(texto, cor) { const s = document.createElement('span'); s.className = 'br-tag status-plano'; s.style.background = cor; s.textContent = texto; return s; }
function el(tag, classe, texto) { const e = document.createElement(tag); if (classe) e.className = classe; if (texto) e.textContent = texto; return e; }
function icone(nome) { const i = el('i', 'fas fa-' + nome); i.setAttribute('aria-hidden', 'true'); return i; }
function link(href, nomeIcone, texto, novaAba) {
  const a = el('a'); a.href = href; a.append(icone(nomeIcone), ' ' + texto);
  if (novaAba) { a.target = '_blank'; a.rel = 'noopener'; }
  return a;
}

// Situação do plano: o selo e uma frase curta
function situacao(p) {
  if (p.situacao === 'sem_plano') return [selo('Sem plano', '#636363'), 'Envie o PDF do plano desta disciplina.'];
  if (p.assinatura) return [selo('Assinado', '#168821'), `Assinado via gov.br por ${p.assinatura.signatario}`
    + (p.assinatura.assinado_em ? ` em ${hora(p.assinatura.assinado_em)}.` : '.')
    + (p.assinatura.aviso ? ` Atenção: ${p.assinatura.aviso}` : '')];
  if (p.revisao && p.situacao === 'avaliado') {
    const r = p.revisao;
    const quem = `${r.parecer} por ${r.revisor} (${r.papel})` + (r.comentario ? ': ' + r.comentario : '.');
    return [selo(r.status === 'OK' ? 'Aprovado' : r.status, CORES[r.status] || '#c51d1d'), quem];
  }
  if (p.situacao === 'na_fila') return [selo(`Na fila (${p.posicao}º)`, '#6b7280'), 'Aguardando a vez da avaliação automática.'];
  if (p.situacao === 'validando') return [selo('Avaliando…', '#2563eb'), 'A IA está lendo o plano; leva cerca de um minuto.'];
  if (p.situacao === 'aguardando') return [selo('Enviado', '#6b7280'), 'Será avaliado na próxima validação geral.'];
  const detalhe = p.status === 'OK' ? 'A avaliação automática não apontou ajustes.'
    : p.status === 'ERRO' || !p.problemas.length ? p.obs
    : 'Verificar: ' + p.problemas.join(', ') + '.';
  return [selo(p.status, CORES[p.status] || '#c51d1d'), detalhe + ' Aguardando a revisão da coordenação/NDE.'];
}

// Etapa do plano, para os filtros: o que o professor precisa fazer, o que espera os outros e o que acabou
function etapa(p) {
  if (p.assinatura) return 'assinados';
  if (!p.tem_plano || (p.pode_assinar && !p.assinatura)) return 'fazer';
  if (p.revisao && p.situacao === 'avaliado' && p.revisao.status !== 'OK') return 'fazer';  // ajustes pedidos
  return 'andamento';
}

// Uma disciplina: a linha (nome, situação, ação principal) e, ao abrir, o resto
function item(p) {
  const li = el('li', 'disciplina'); li.id = 'oferta-' + p.oferta_id;
  const aberto = abertos.has(p.oferta_id);
  const corpoId = 'corpo-' + p.oferta_id;
  const linha = el('div', 'linha');
  const abrir = el('button', 'abrir'); abrir.type = 'button';
  abrir.setAttribute('aria-expanded', String(aberto)); abrir.setAttribute('aria-controls', corpoId);
  abrir.title = aberto ? 'Fechar os detalhes' : 'Ver a versão atual, os avisos e o histórico';
  const nome = el('span', 'nome', p.disciplina);
  const partes = [p.componente.split(' · ')[0]].filter(Boolean);
  if (p.fase) partes.push(`${p.fase}ª fase`);
  if (p.tem_plano) partes.push(`versão ${p.versao}`);
  const outros = (p.docentes || []).map(d => d.nome || d.email);
  if (outros.length > 1) partes.push('com ' + outros.join(', '));
  nome.append(el('span', 'sub', partes.join(' · ')));
  abrir.append(icone('chevron-right'), nome);
  abrir.onclick = () => alternar(p.oferta_id);
  const [marca, frase] = situacao(p);
  const acoes = el('span', 'acoes');
  if ((p.tem_plano && p.aviso) || (p.assinatura && p.assinatura.aviso)) {
    const alerta = el('span', 'alerta'); alerta.title = 'Há um aviso sobre este plano: abra para ver';
    alerta.append(icone('exclamation-triangle')); acoes.append(alerta);
  }
  acoes.append(marca, acaoPrincipal(p));
  linha.append(abrir, acoes);

  const corpo = el('div', 'corpo'); corpo.id = corpoId; corpo.hidden = !aberto;
  corpo.append(el('p', 'frase', frase));
  if (p.tem_plano) corpo.append(versaoAtual(p));
  if (p.tem_plano && p.aviso) {
    const aviso = el('p', 'aviso'); aviso.append(icone('exclamation-triangle'), ' ' + p.aviso); corpo.append(aviso);
  }
  if (p.pode_assinar && !p.assinatura) corpo.append(blocoAssinatura(p));
  if (p.tem_plano && p.pode_assinar && !p.assinatura) {  // na linha está Assinar: Enviar nova versão fica aqui
    const atualizar = el('div', 'atualizar'); atualizar.append(botaoEnviar(p)); corpo.append(atualizar);
  }
  if (p.versoes.length) corpo.append(detalhes(p));
  li.classList.toggle('aberta', aberto);
  li.append(linha, corpo);
  return li;
}

function alternar(id, abrir) {
  const deve = abrir === undefined ? !abertos.has(id) : abrir;
  if (deve) abertos.add(id); else abertos.delete(id);
  const li = document.getElementById('oferta-' + id);
  if (!li) return;
  li.classList.toggle('aberta', deve);
  li.querySelector('.corpo').hidden = !deve;
  const b = li.querySelector('.abrir'); b.setAttribute('aria-expanded', String(deve));
  b.title = deve ? 'Fechar os detalhes' : 'Ver a versão atual, os avisos e o histórico';
}

// A ação principal, na linha: enviar o plano, assinar (aprovado) ou enviar nova versão (com destaque se pediram ajustes)
function acaoPrincipal(p) {
  if (p.pode_assinar && !p.assinatura) {
    if (ASSINATURA_API && ASSINATURA_NIVEL === 'bronze') return el('span', 'br-tag sem-assinatura', 'Assinatura indisponível');
    if (ASSINATURA_API && ASSINATURA_NIVEL === 'sem_nivel') return botaoConferirConta(p);
    if (ASSINATURA_API && ASSINATURA_NIVEL === 'ok') {  // prata ou ouro
      const a = link('/assinatura/govbr/iniciar?arquivo=' + encodeURIComponent(p.nome), 'signature', 'Assinar');
      a.className = 'br-button primary small'; a.title = 'Assinar o plano aprovado com a sua conta gov.br';
      return a;
    }
    const b = el('button', 'br-button primary small'); b.type = 'button';
    b.append(icone('signature'), ' Assinar'); b.title = 'Ver como assinar o plano aprovado';
    b.onclick = () => { alternar(p.oferta_id, true); document.getElementById('oferta-' + p.oferta_id).querySelector('.assinatura').scrollIntoView({ block: 'nearest', behavior: 'smooth' }); };
    return b;
  }
  return botaoEnviar(p, etapa(p) === 'fazer');
}

// Enviar plano (sem plano) ou Enviar nova versão (com plano, mesmo assinado: a versão anterior vai para o histórico)
function botaoEnviar(p, destaque) {
  const entrada = el('input'); entrada.type = 'file'; entrada.accept = 'application/pdf,.pdf'; entrada.hidden = true;
  const botao = el('button', 'br-button small ' + (!p.tem_plano || destaque ? 'primary' : 'secondary')); botao.type = 'button';
  botao.append(icone(p.tem_plano ? 'file-upload' : 'upload'), p.tem_plano ? ' Enviar nova versão' : ' Enviar plano');
  botao.title = p.tem_plano ? 'Trocar o PDF por uma versão corrigida (a atual fica no histórico)' : 'Enviar o PDF do plano';
  botao.onclick = () => {
    if (p.assinatura && !confirm(`O plano de "${p.disciplina}" já está assinado. A versão nova vai precisar de nova avaliação, revisão e assinatura; a assinada fica no histórico. Continuar?`)) return;
    entrada.click();
  };
  entrada.onchange = () => { if (entrada.files[0]) enviar(p, entrada.files[0]); entrada.value = ''; };
  const span = el('span'); span.append(botao, entrada);
  return span;
}

// Versão atual, no card: quando foi enviada e os botões (PDF, relatório, PDF assinado, excluir)
function versaoAtual(p) {
    const atual = el('div', 'versao atual');
    atual.append(el('strong', '', `Versão ${p.versao}`), el('span', 'quando', `enviada em ${hora(p.enviado_em)}`));
    const links = el('span', 'links');
    links.append(link('/pdf?arquivo=' + encodeURIComponent(p.nome), 'file-pdf', 'PDF', true));
    if (p.situacao === 'avaliado') links.append(link('/relatorio?arquivo=' + encodeURIComponent(p.nome), 'file-alt', 'Relatório'));
    // O endereço muda a cada assinatura (v=), para o navegador não reabrir a de uma versão anterior
    if (p.assinatura) links.append(link('/pdf-assinado?arquivo=' + encodeURIComponent(p.nome)
      + '&v=' + encodeURIComponent(p.assinatura.enviado_em || ''), 'file-signature', 'PDF assinado', true));
    // Assinada, a versão atual não é excluída: para corrigir, Enviar nova versão (ela fica no histórico)
    if (p.assinatura) links.append(protegida('Assinada: não pode ser excluída; para corrigir, use Enviar nova versão'));
    else links.append(botaoExcluir(' Excluir', () => excluir(p)));
    atual.append(links);
    return atual;
}

// Versões anteriores, recolhidas
function detalhes(p) {
  const d = el('details', 'detalhes');
  const n = p.versoes.length;
  d.append(el('summary', '', `Versões anteriores (${n})`));
  for (const v of p.versoes) d.append(versao(p, v));
  return d;
}

function versao(p, v) {
  const div = el('div', 'versao');
  div.append(el('strong', '', `Versão ${v.numero}`), el('span', 'quando', `enviada em ${hora(v.enviado_em)}, substituída em ${hora(v.arquivado_em)}`));
  const marcas = [];
  if (v.signatario) marcas.push(`assinada por ${v.signatario}`);
  else if (v.revisao_status) marcas.push(`${ROTULOS_REVISAO[v.revisao_status] || v.revisao_status} na revisão` + (v.revisor ? ` (${v.revisor})` : ''));
  else if (v.status_ia) marcas.push(`IA: ${v.status_ia}`);
  if (marcas.length) div.append(el('span', 'marca-versao', marcas.join(' · ')));
  const base = `/meus-planos/versao?arquivo=${encodeURIComponent(p.nome)}&numero=${v.numero}`;
  const links = el('span', 'links');
  links.append(link(base, 'file-pdf', 'PDF', true));
  if (v.tem_assinado) links.append(link(base + '&assinado=1', 'file-signature', 'PDF assinado', true));
  links.append(v.protegida ? protegida('Aprovada e assinada: fica guardada')
    : botaoExcluir(' Excluir', () => excluirVersao(p, v)));
  div.append(links);
  return div;
}

function botaoExcluir(texto, acao) {
  const b = el('button', 'br-button small excluir-plano'); b.type = 'button';
  b.append(icone('trash-alt'), texto); b.onclick = acao;
  return b;
}

function protegida(dica) {
  const s = el('span', 'protegida'); s.title = dica; s.append(icone('lock'), ' Protegida');
  return s;
}

async function excluirVersao(p, v) {
  if (!confirm(`Excluir a versão ${v.numero} do plano de "${p.disciplina}"? O PDF dela é apagado do histórico.`)) return;
  const r = await fetch(`/meus-planos/versao?arquivo=${encodeURIComponent(p.nome)}&numero=${v.numero}`, { method: 'DELETE' });
  const d = await corpo(r);
  msg($('envio-msg'), r.ok ? `Versão ${v.numero} do plano de "${p.disciplina}" excluída.` : (d.erro || 'Falha ao excluir a versão'), r.ok ? 'ok' : 'erro');
  carregar();
}

// Aprovado na revisão: o professor assina pelo gov.br. Com a API de assinatura configurada (ASSINATURA_API),
// "Assinar com gov.br" faz tudo pelo app; senão (ou como alternativa), assina em assinador.iti.br e envia o PDF.
function blocoAssinatura(p) {
  const div = el('div', 'assinatura');
  const titulo = el('p'); const forte = el('strong'); forte.append(icone('file-signature'), ' Plano aprovado: falta a sua assinatura.');
  titulo.append(forte); div.append(titulo);
  if (ASSINATURA_API && ASSINATURA_NIVEL === 'bronze') {
    // Roteiro da assinatura gov.br: conta bronze não chega à autorização; aviso com o link para elevar o nível
    div.append(avisoBronze());
    return div;
  }
  if (ASSINATURA_API && ASSINATURA_NIVEL === 'sem_nivel') {
    // Nível desconhecido (entrou pelo Google): sem botão de assinar; primeiro, entrar com gov.br para o
    // sistema conferir o nível da conta
    div.append(botaoConferirConta(p), el('p', 'nota', 'A assinatura exige conta gov.br nível prata ou ouro. Entre com a sua conta gov.br para o sistema conferir o nível; com prata ou ouro, o botão de assinar aparece aqui.'));
    return div;
  }
  if (ASSINATURA_API) {
    const assinar = link('/assinatura/govbr/iniciar?arquivo=' + encodeURIComponent(p.nome), 'signature', 'Assinar com gov.br');
    assinar.className = 'br-button primary small';
    const nota = el('p', 'nota', (ASSINATURA_NIVEL === 'sem_nivel'
      ? 'Primeiro você entra com a sua conta gov.br, para o sistema conferir o nível dela (prata ou ouro). ' : '')
      + (ASSINATURA_HOMOLOGACAO
        ? 'Ambiente de homologação do gov.br: a assinatura é de teste, sem validade jurídica. Entre com uma conta de '
          + 'teste (sso.staging.acesso.gov.br); o código do SMS pode ser 12345.'
        : 'Você confirma no gov.br (conta nível prata ou ouro) e volta para cá com o plano assinado.'));
    const alternativa = el('details', 'alternativa'); alternativa.append(el('summary', '', 'Ou assine em assinador.iti.br e envie o arquivo'));
    alternativa.append(passosManuais(p));
    div.append(assinar, nota, alternativa);
    return div;
  }
  div.append(passosManuais(p));
  return div;
}

// Entrar com gov.br só para conferir o nível da conta (sem assinar), voltando a esta página
function botaoConferirConta(p) {
  const a = link('/conta/govbr/vincular?rd=' + encodeURIComponent('/meus-planos#oferta-' + p.oferta_id), 'user-check', 'Entrar com gov.br');
  a.className = 'br-button secondary small'; a.title = 'Entrar com a conta gov.br para o sistema conferir o nível dela';
  return a;
}

// Aviso do roteiro para conta bronze, com o link para elevar o nível da conta
function avisoBronze() {
  const aviso = el('p', 'nota aviso-nivel');
  const upgrade = el('a', '', 'Clique aqui'); upgrade.href = 'https://confiabilidades.acesso.gov.br/';
  upgrade.target = '_blank'; upgrade.rel = 'noopener';
  aviso.append(icone('exclamation-triangle'), ' É necessário possuir conta gov.br nível prata ou ouro para utilizar o serviço de assinatura. ',
    upgrade, ' para realizar o upgrade da conta. Depois, saia e entre de novo com gov.br.');
  return aviso;
}

// Assinatura manual: baixar o PDF, assinar em assinador.iti.br e enviar o arquivo assinado.
function passosManuais(p) {
  const div = el('div');
  div.innerHTML = '<ol><li>Baixe o <a target="_blank" rel="noopener">PDF do plano</a>.</li>'
    + '<li>Assine-o em <a href="https://assinador.iti.br" target="_blank" rel="noopener">assinador.iti.br</a>, com a sua conta gov.br.</li>'
    + '<li>Envie aqui o arquivo assinado que o assinador devolve.</li></ol>';
  div.querySelector('a').href = '/pdf?arquivo=' + encodeURIComponent(p.nome);
  const entrada = el('input'); entrada.type = 'file'; entrada.accept = 'application/pdf,.pdf'; entrada.hidden = true;
  const botao = el('button', 'br-button primary small'); botao.type = 'button';
  botao.append(icone('upload'), ' Enviar PDF assinado');
  botao.onclick = () => entrada.click();
  entrada.onchange = () => { if (entrada.files[0]) enviarAssinado(p, entrada.files[0]); entrada.value = ''; };
  div.append(botao, entrada);
  return div;
}

async function enviarAssinado(p, arquivo) {
  const local = motivoLocal(arquivo);
  if (local) { msg($('envio-msg'), `${arquivo.name}: ${local}`, 'erro'); return; }
  const form = new FormData(); form.append('arquivo', p.nome); form.append('pdf', arquivo);
  msg($('envio-msg'), `Conferindo a assinatura do plano de "${p.disciplina}"…`);
  let r;
  try { r = await fetch('/meus-planos/assinatura', { method: 'POST', body: form }); }
  catch { msg($('envio-msg'), 'Falha de conexão no envio', 'erro'); return; }
  if (r.status === 401) { location.reload(); return; }  // sessão expirou: recarregar leva ao login
  const d = await corpo(r);
  msg($('envio-msg'), r.ok ? `Plano de "${p.disciplina}" assinado por ${d.assinatura.signatario}.`
    + (d.assinatura.aviso ? ` Atenção: ${d.assinatura.aviso}` : '') : (d.erro || `Falha ao enviar o PDF assinado (erro ${r.status})`), r.ok ? 'ok' : 'erro');
  carregar();
}

// Períodos: o atual e o próximo como abas, os demais num seletor -----------------------------------------
function periodos() {
  const vistos = [...new Set(planos.map(p => p.periodo))];
  const peso = per => DESTAQUES[per] === 'Atual' ? 0 : DESTAQUES[per] === 'Próximo' ? 1 : 2;
  return vistos.sort((a, b) => peso(a) - peso(b) || b.localeCompare(a));
}

function padrao(lista) {
  return lista.find(per => DESTAQUES[per] === 'Atual') || lista.find(per => DESTAQUES[per] === 'Próximo') || lista[0] || '';
}

function desenharPeriodos(lista) {
  const area = $('periodos');
  const abas = [], outros = [];
  for (const per of lista) (DESTAQUES[per] ? abas : outros).push(per);
  const itens = abas.map(per => {
    const n = planos.filter(p => p.periodo === per).length;
    const b = el('button', 'aba-periodo' + (per === periodoEscolhido ? ' ativa' : '')); b.type = 'button';
    b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(per === periodoEscolhido));
    b.append(el('strong', '', per), el('span', '', ` ${DESTAQUES[per]} · ${n}`));
    b.onclick = () => escolher(per);
    return b;
  });
  if (outros.length) {
    const sel = el('select', 'outros-periodos' + (outros.includes(periodoEscolhido) ? ' ativa' : ''));
    sel.setAttribute('aria-label', 'Outros períodos');
    const vazio = el('option', '', 'Outros períodos'); vazio.value = ''; sel.append(vazio);
    for (const per of outros) {
      const o = el('option', '', `${per} (${planos.filter(p => p.periodo === per).length})`); o.value = per;
      o.selected = per === periodoEscolhido; sel.append(o);
    }
    sel.onchange = () => sel.value && escolher(sel.value);
    itens.push(sel);
  }
  area.replaceChildren(...itens);
  area.hidden = lista.length < 2 && !outros.length;
}

function escolher(per) {
  periodoEscolhido = per; filtro = ''; busca = '';
  history.replaceState(null, '', '#periodo=' + encodeURIComponent(per));
  const campo = $('busca'); if (campo) campo.value = '';
  desenhar();
}

// Filtros por etapa (com a contagem) e a busca, quando o período tem muitas disciplinas
function desenharFiltros(doPeriodo) {
  const conta = e => e === 'todas' ? doPeriodo.length : doPeriodo.filter(p => etapa(p) === e).length;
  if (!filtro) filtro = conta('fazer') ? 'fazer' : 'todas';
  const area = $('filtros');
  area.hidden = doPeriodo.length < 2;
  const botoes = ETAPAS.map(([e, rotulo]) => {
    const b = el('button', 'filtro' + (e === filtro ? ' ativo' : '') + (e === 'fazer' && conta(e) ? ' pendente' : ''));
    b.type = 'button'; b.setAttribute('aria-pressed', String(e === filtro));
    b.append(rotulo + ' ', el('span', 'n', String(conta(e))));
    b.onclick = () => { filtro = e; desenhar(); };
    return b;
  });
  $('etapas').replaceChildren(...botoes);
  $('caixa-busca').hidden = doPeriodo.length < BUSCA_A_PARTIR_DE;
}

function combina(p) {
  if (!busca) return true;
  const norm = t => (t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  return norm(`${p.disciplina} ${p.componente} ${p.turma || ''}`).includes(norm(busca));
}

function desenhar() {
  const lista = periodos();
  if (!lista.includes(periodoEscolhido)) periodoEscolhido = padrao(lista);
  desenharPeriodos(lista);
  const doPeriodo = planos.filter(p => p.periodo === periodoEscolhido);
  desenharFiltros(doPeriodo);
  if (doPeriodo.length === 1) abertos.add(doPeriodo[0].oferta_id);  // uma só: já aberta
  const visiveis = doPeriodo.filter(p => (filtro === 'todas' || etapa(p) === filtro) && combina(p));
  const itens = [];
  let grupo = null;
  for (const p of visiveis) {
    if (p.grupo !== grupo) { grupo = p.grupo; itens.push(el('li', 'cab-grupo', p.grupo_titulo)); }
    itens.push(item(p));
  }
  if (!itens.length) {
    const li = el('li', 'vazio');
    li.append(el('span', 'msg', !doPeriodo.length
      ? 'Nenhuma disciplina vinculada a você ainda. A coordenação do curso vincula os docentes de cada disciplina do semestre; depois disso, envie aqui o plano de cada uma.'
      : busca ? `Nenhuma disciplina com "${busca}".`
      : filtro === 'fazer' ? 'Nada a fazer neste período: os planos estão em andamento ou assinados.'
      : 'Nenhuma disciplina nesta situação.'));
    itens.push(li);
  }
  $('lista').replaceChildren(...itens);
  // Resumo do período: o que falta fazer
  const n = f => doPeriodo.filter(f).length;
  const partes = doPeriodo.length ? [`${doPeriodo.length} disciplina${doPeriodo.length > 1 ? 's' : ''}`] : [];
  if (n(p => !p.tem_plano)) partes.push(`${n(p => !p.tem_plano)} sem plano`);
  if (n(p => p.pode_assinar && !p.assinatura)) partes.push(`${n(p => p.pode_assinar && !p.assinatura)} para assinar`);
  if (n(p => p.assinatura)) partes.push(`${n(p => p.assinatura)} assinado${n(p => p.assinatura) > 1 ? 's' : ''}`);
  $('resumo').textContent = partes.join(' · ');
}

// A barra de status (status.js) chama ao fim de uma avaliação: só atualiza a lista, sem sair da página.
function aoTerminar() { carregar(); }

// "Validar meus planos" (barra de status): põe na fila os planos ainda sem revisão humana
async function validarMeus() {
  const b = $('validar-meus'); b.disabled = true;
  let r, d;
  try { r = await fetch('/meus-planos/validar', { method: 'POST' }); d = await corpo(r); }
  catch { msg($('envio-msg'), 'Sem conexão com o servidor; tente de novo', 'erro'); b.disabled = false; return; }
  b.disabled = false;
  if (!r.ok) { msg($('envio-msg'), d.mensagem || d.erro || 'Não foi possível iniciar a validação', r.status === 422 ? 'aviso' : 'erro'); return; }
  msg($('envio-msg'), d.planos === 1 ? 'Um plano entrou na fila de avaliação.' : `${d.planos} planos entraram na fila de avaliação.`, 'ok');
  estavaRodando = true; atualizarStatus();  // status.js: mostra o andamento na barra e recarrega ao terminar
  carregar();
}
if ($('validar-meus')) $('validar-meus').onclick = validarMeus;

async function carregar() {
  clearTimeout(timerLista);
  let r;
  try { r = await fetch('/meus-planos/lista'); }
  catch { timerLista = setTimeout(carregar, 10000); return; }
  if (r.status === 401) { location.reload(); return; }  // sessão expirou: recarregar leva ao login
  ({ planos = [] } = await corpo(r));
  if (voltarPara) {  // de volta da assinatura: a disciplina aberta, no período dela
    const p = planos.find(x => x.nome === voltarPara);
    if (p) { abertos.add(p.oferta_id); periodoEscolhido = p.periodo; filtro = 'todas'; }
  }
  // Mantém abertos os "Versões anteriores" e afins que estavam abertos
  const chave = d => (d.closest('li') || {}).id + d.className;
  const detalhesAbertos = new Set([...document.querySelectorAll('#lista details[open]')].map(chave));
  desenhar();
  document.querySelectorAll('#lista details').forEach(d => { if (detalhesAbertos.has(chave(d))) d.open = true; });
  if (voltarPara) {
    const li = planos.find(x => x.nome === voltarPara) && document.getElementById('oferta-' + planos.find(x => x.nome === voltarPara).oferta_id);
    if (li) li.scrollIntoView({ block: 'center' });
    voltarPara = '';
  }
  const andamento = planos.some(p => p.situacao === 'na_fila' || p.situacao === 'validando');
  timerLista = setTimeout(carregar, andamento ? 3000 : 30000);
}

async function excluir(p) {
  if (!confirm(`Excluir o plano de "${p.disciplina}"? Ele deixa de constar como entregue (as versões anteriores ficam no histórico).`)) return;
  const r = await fetch('/meus-planos?arquivo=' + encodeURIComponent(p.nome), { method: 'DELETE' });
  const d = await corpo(r);
  msg($('envio-msg'), r.ok ? `Plano de "${p.disciplina}" excluído.` : (d.erro || d.mensagem || 'Falha ao excluir'), r.ok ? 'ok' : 'erro');
  carregar();
}

function motivoLocal(a) {
  if (!/\.pdf$/i.test(a.name) && a.type !== 'application/pdf') return 'Apenas arquivos .pdf são aceitos';
  if (a.size > MAX_MB * 1048576) return `Arquivo maior que ${MAX_MB} MB`;
  return '';
}

async function enviar(p, arquivo) {
  const local = motivoLocal(arquivo);
  if (local) { msg($('envio-msg'), `${arquivo.name}: ${local}`, 'erro'); return; }
  const form = new FormData(); form.append('oferta', p.oferta_id); form.append('arquivo', arquivo);
  msg($('envio-msg'), `Enviando e conferindo o plano de "${p.disciplina}"…`);
  let r;
  try { r = await fetch('/meus-planos', { method: 'POST', body: form }); }
  catch { msg($('envio-msg'), 'Falha de conexão no envio', 'erro'); return; }
  if (r.status === 401) { location.reload(); return; }
  const d = await corpo(r);
  if (!r.ok) msg($('envio-msg'), d.erro || d.mensagem || `Falha no envio (erro ${r.status})`, 'erro');
  else {
    const guardada = d.versao_anterior ? ` A versão ${d.versao_anterior} ficou no histórico.` : '';
    msg($('envio-msg'), `Plano de "${p.disciplina}" enviado; a avaliação começou.${guardada}` + (d.aviso ? ' ' + d.aviso : ''), d.aviso ? 'aviso' : 'ok');
  }
  carregar();
}

// Volta da assinatura pela API (rotas/assinatura_govbr.py): mostra o resultado e limpa o endereço.
(function resultadoDaAssinatura() {
  const q = new URLSearchParams(location.search);
  if (!q.has('assinatura')) return;
  voltarPara = q.get('arquivo') || '';
  if (q.get('assinatura') === 'bronze') {
    msg($('envio-msg'), 'Não foi possível assinar o plano: sua conta gov.br é nível bronze.', 'erro');
    $('envio-msg').append(' ', avisoBronze());
  } else if (q.get('assinatura') === 'ok') msg($('envio-msg'), `Plano assinado via gov.br por ${q.get('signatario') || 'você'}.`
    + (q.get('aviso') ? ` Atenção: ${q.get('aviso')}` : ''), 'ok');
  else msg($('envio-msg'), `Não foi possível assinar o plano: ${q.get('motivo') || 'tente de novo.'}`, 'erro');
  history.replaceState(null, '', location.pathname + location.hash);
})();
periodoEscolhido = decodeURIComponent((location.hash.match(/periodo=([^&]+)/) || [])[1] || '');
$('busca').oninput = e => { busca = e.target.value.trim(); desenhar(); };
carregar();
