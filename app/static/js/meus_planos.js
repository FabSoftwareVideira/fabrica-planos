// "Meus planos": as disciplinas do professor, separadas por período letivo (o atual e o próximo primeiro), com
// a situação do plano, a ação principal (enviar, atualizar, assinar) e, em "Detalhes", os PDFs, o aviso, a
// exclusão e as versões anteriores. MAX_MB, ASSINATURA_API e DESTAQUES ({período: 'Atual' | 'Próximo'}) vêm da
// página; $, msg, hora e corpo, de status.js (a barra de status, carregada antes).
const CORES = { OK: '#22c55e', PENDENTE: '#eab308', INCOMPLETO: '#eab308' };
const ROTULOS_REVISAO = { OK: 'Aprovado', PENDENTE: 'Ajustes necessários', REPROVADO: 'Reprovado' };
let timerLista, planos = [], periodoEscolhido = '';

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
  if (p.situacao === 'sem_plano') return [selo('Sem plano', '#9ca3af'), 'Envie o PDF do plano desta disciplina.'];
  if (p.assinatura) return [selo('Assinado', '#168821'), `Assinado via gov.br por ${p.assinatura.signatario}` + (p.assinatura.assinado_em ? ` em ${hora(p.assinatura.assinado_em)}.` : '.')];
  if (p.revisao && p.situacao === 'avaliado') {
    const r = p.revisao;
    const quem = `${r.parecer} por ${r.revisor} (${r.papel})` + (r.comentario ? ': ' + r.comentario : '.');
    return [selo(r.status === 'OK' ? 'Aprovado' : r.status, CORES[r.status] || '#ef4444'), quem];
  }
  if (p.situacao === 'na_fila') return [selo(`Na fila (${p.posicao}º)`, '#6b7280'), 'Aguardando a vez da avaliação automática.'];
  if (p.situacao === 'validando') return [selo('Avaliando…', '#2563eb'), 'A IA está lendo o plano; leva cerca de um minuto.'];
  if (p.situacao === 'aguardando') return [selo('Enviado', '#6b7280'), 'Será avaliado na próxima validação geral.'];
  const detalhe = p.status === 'OK' ? 'A avaliação automática não apontou ajustes.'
    : p.status === 'ERRO' || !p.problemas.length ? p.obs
    : 'Verificar: ' + p.problemas.join(', ') + '.';
  return [selo(p.status, CORES[p.status] || '#ef4444'), detalhe + ' Aguardando a revisão da coordenação/NDE.'];
}

function item(p) {
  const li = el('li', 'disciplina'); li.id = 'oferta-' + p.oferta_id;
  const topo = el('div', 'topo');
  const nome = el('span', 'nome', p.disciplina);
  const partes = [p.componente.split(' · ')[0]].filter(Boolean);
  if (p.fase) partes.push(`${p.fase}ª fase`);
  const outros = (p.docentes || []).map(d => d.nome || d.email);
  if (outros.length > 1) partes.push('com ' + outros.join(', '));
  nome.append(el('span', 'sub', partes.join(' · ')));
  const [marca, frase] = situacao(p);
  const acoes = el('span', 'acoes');
  acoes.append(marca, botaoEnviar(p));
  topo.append(nome, acoes);
  li.append(topo, el('p', 'frase', frase));
  if (p.tem_plano && p.aviso) {
    const aviso = el('p', 'aviso'); aviso.append(icone('exclamation-triangle'), ' ' + p.aviso); li.append(aviso);
  }
  if (p.pode_assinar && !p.assinatura) li.append(blocoAssinatura(p));
  if (p.tem_plano || p.versoes.length) li.append(detalhes(p));
  return li;
}

// Enviar (sem plano) ou Atualizar (com plano, mesmo assinado: a versão anterior vai para o histórico)
function botaoEnviar(p) {
  const entrada = el('input'); entrada.type = 'file'; entrada.accept = 'application/pdf,.pdf'; entrada.hidden = true;
  const botao = el('button', 'br-button small ' + (p.tem_plano ? 'secondary' : 'primary')); botao.type = 'button';
  botao.append(icone(p.tem_plano ? 'sync-alt' : 'upload'), p.tem_plano ? ' Atualizar' : ' Enviar plano');
  botao.title = p.tem_plano ? 'Enviar uma nova versão do plano (a atual fica no histórico)' : 'Enviar o PDF do plano';
  botao.onclick = () => {
    if (p.assinatura && !confirm(`O plano de "${p.disciplina}" já está assinado. A versão nova vai precisar de nova avaliação, revisão e assinatura; a assinada fica no histórico. Continuar?`)) return;
    entrada.click();
  };
  entrada.onchange = () => { if (entrada.files[0]) enviar(p, entrada.files[0]); entrada.value = ''; };
  const span = el('span'); span.append(botao, entrada);
  return span;
}

// PDFs, relatório, exclusão e versões anteriores, recolhidos
function detalhes(p) {
  const d = el('details', 'detalhes');
  const n = p.versoes.length;
  d.append(el('summary', '', n ? `Detalhes e versões (${n} anterior${n > 1 ? 'es' : ''})` : 'Detalhes'));
  if (p.tem_plano) {
    const atual = el('div', 'versao atual');
    atual.append(el('strong', '', `Versão ${p.versao} (atual)`), el('span', 'quando', `enviada em ${hora(p.enviado_em)}`));
    const links = el('span', 'links');
    links.append(link('/pdf?arquivo=' + encodeURIComponent(p.nome), 'file-pdf', 'PDF', true));
    if (p.situacao === 'avaliado') links.append(link('/relatorio?arquivo=' + encodeURIComponent(p.nome), 'file-alt', 'Relatório'));
    if (p.assinatura) links.append(link('/pdf-assinado?arquivo=' + encodeURIComponent(p.nome), 'file-signature', 'PDF assinado', true));
    const del = el('button', 'br-button small excluir-plano'); del.type = 'button';
    del.append(icone('trash-alt'), ' Excluir'); del.onclick = () => excluir(p);
    links.append(del);
    atual.append(links);
    d.append(atual);
  }
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
  div.append(links);
  return div;
}

// Aprovado na revisão: o professor assina pelo gov.br. Com a API de assinatura configurada (ASSINATURA_API),
// "Assinar com gov.br" faz tudo pelo app; senão (ou como alternativa), assina em assinador.iti.br e envia o PDF.
function blocoAssinatura(p) {
  const div = el('div', 'assinatura');
  const titulo = el('p'); const forte = el('strong'); forte.append(icone('file-signature'), ' Plano aprovado: falta a sua assinatura.');
  titulo.append(forte); div.append(titulo);
  if (ASSINATURA_API) {
    const assinar = link('/assinatura/govbr/iniciar?arquivo=' + encodeURIComponent(p.nome), 'signature', 'Assinar com gov.br');
    assinar.className = 'br-button primary small';
    const nota = el('p', 'nota', 'Você confirma no gov.br (conta nível prata ou ouro) e volta para cá com o plano assinado.');
    const alternativa = el('details', 'alternativa'); alternativa.append(el('summary', '', 'Ou assine em assinador.iti.br e envie o arquivo'));
    alternativa.append(passosManuais(p));
    div.append(assinar, nota, alternativa);
    return div;
  }
  div.append(passosManuais(p));
  return div;
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
  msg($('envio-msg'), r.ok ? `Plano de "${p.disciplina}" assinado por ${d.assinatura.signatario}.` : (d.erro || `Falha ao enviar o PDF assinado (erro ${r.status})`), r.ok ? 'ok' : 'erro');
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
  periodoEscolhido = per;
  history.replaceState(null, '', '#periodo=' + encodeURIComponent(per));
  desenhar();
}

function desenhar() {
  const lista = periodos();
  if (!lista.includes(periodoEscolhido)) periodoEscolhido = padrao(lista);
  desenharPeriodos(lista);
  const doPeriodo = planos.filter(p => p.periodo === periodoEscolhido);
  const itens = [];
  let grupo = null;
  for (const p of doPeriodo) {
    if (p.grupo !== grupo) { grupo = p.grupo; itens.push(el('li', 'cab-grupo', p.grupo_titulo)); }
    itens.push(item(p));
  }
  if (!itens.length) {
    const li = el('li');
    li.append(el('span', 'msg', 'Nenhuma disciplina vinculada a você ainda. A coordenação do curso vincula os docentes de cada disciplina do semestre; depois disso, envie aqui o plano de cada uma.'));
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

async function carregar() {
  clearTimeout(timerLista);
  let r;
  try { r = await fetch('/meus-planos/lista'); }
  catch { timerLista = setTimeout(carregar, 10000); return; }
  if (r.status === 401) { location.reload(); return; }  // sessão expirou: recarregar leva ao login
  ({ planos = [] } = await corpo(r));
  // Mantém abertos os "Detalhes" que estavam abertos
  const chave = d => (d.closest('li') || {}).id + d.className;
  const abertos = new Set([...document.querySelectorAll('#lista details[open]')].map(chave));
  desenhar();
  document.querySelectorAll('#lista details').forEach(d => { if (abertos.has(chave(d))) d.open = true; });
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
  if (q.get('assinatura') === 'ok') msg($('envio-msg'), `Plano assinado via gov.br por ${q.get('signatario') || 'você'}.`, 'ok');
  else msg($('envio-msg'), `Não foi possível assinar o plano: ${q.get('motivo') || 'tente de novo.'}`, 'erro');
  history.replaceState(null, '', location.pathname + location.hash);
})();
periodoEscolhido = decodeURIComponent((location.hash.match(/periodo=([^&]+)/) || [])[1] || '');
carregar();
