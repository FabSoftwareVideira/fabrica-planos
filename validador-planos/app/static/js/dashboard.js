// Dashboard: andamento da validação, envio e exclusão de PDFs, filtros e agrupamento dos cards.
// MAX_MB e ADMIN vêm da página (templates/dashboard.html).
const $ = id => document.getElementById(id);
let rodando = false, estavaRodando = false, timer;

function msg(el, texto, tipo) { el.textContent = texto; el.className = 'msg' + (tipo ? ' ' + tipo : ''); el.hidden = !texto; }
function hora(iso) { return iso ? new Date(iso).toLocaleString('pt-BR') : ''; }
function kb(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }
async function corpo(resp) { try { return await resp.json(); } catch { return {}; } }

function bloquear() {
  for (const b of [$('validar'), $('escolher')]) if (b) b.disabled = rodando;
  document.querySelectorAll('.excluir, .revalidar').forEach(b => b.disabled = rodando);
}

function trocarValidacao(id) { location.href = '/dashboard' + (id ? '?validacao=' + encodeURIComponent(id) : ''); }

async function atualizarStatus() {
  clearTimeout(timer);
  let s;
  try {
    const r = await fetch('/status');
    if (r.status === 401) { location.reload(); return; }  // sessão expirou: recarregar leva ao login
    s = await r.json();
  }
  catch { msg($('status-msg'), 'Sem conexão com o servidor', 'erro'); timer = setTimeout(atualizarStatus, 5000); return; }
  rodando = s.rodando;
  bloquear();
  const barra = $('barra');
  if (rodando) {
    barra.hidden = false;
    barra.firstChild.style.width = (s.total ? s.processados / s.total * 100 : 0) + '%';
    const fila = s.fila && s.fila.length ? ` · ${s.fila.length} na fila` : '';
    msg($('status-msg'), `Validando ${Math.min(s.processados + 1, s.total)} de ${s.total}: ${s.atual || '…'}${fila}`);
  } else {
    barra.hidden = true;
    if (s.erro) msg($('status-msg'), `Última validação falhou (${hora(s.finalizado_em)}): ${s.erro}`, 'erro');
    else if (s.finalizado_em) msg($('status-msg'), `Validação concluída em ${hora(s.finalizado_em)}`, 'ok');
    else msg($('status-msg'), 'Nenhuma validação em andamento');
  }
  // Ao terminar, abre a validação mais recente; numa revalidação, já no card do plano.
  if (estavaRodando && !rodando) {
    history.replaceState(null, '', '/dashboard' + (s.unico ? '#arquivo=' + encodeURIComponent(s.unico) : ''));
    location.reload();
    return;
  }
  estavaRodando = rodando;
  timer = setTimeout(atualizarStatus, rodando ? 2000 : 10000);
}

async function carregarPlanos() {
  const { planos = [] } = await corpo(await fetch('/planos'));
  $('qtd-planos').textContent = `(${planos.length})`;
  const itens = planos.map(p => {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = '/pdf?arquivo=' + encodeURIComponent(p.nome); a.target = '_blank'; a.rel = 'noopener';
    a.innerHTML = '<i class="fas fa-file-pdf" aria-hidden="true"></i> '; a.append(p.nome);
    const info = document.createElement('span');
    info.textContent = kb(p.tamanho) + ' · ' + hora(p.modificado) + (p.dono ? ' · ' + p.dono : '');
    const val = document.createElement('button');
    val.type = 'button'; val.className = 'revalidar'; val.innerHTML = '<i class="fas fa-redo" aria-hidden="true"></i> Validar'; val.disabled = rodando; val.dataset.arquivo = p.nome;
    val.title = 'Valida só este PDF e atualiza a última validação';
    const del = document.createElement('button');
    del.type = 'button'; del.className = 'excluir'; del.innerHTML = '<i class="fas fa-trash-alt" aria-hidden="true"></i> Excluir'; del.disabled = rodando;
    del.onclick = () => excluir(p.nome);
    li.append(a, info, val, del);
    return li;
  });
  if (!itens.length) { const li = document.createElement('li'); li.innerHTML = '<span>Nenhum PDF na pasta.</span>'; itens.push(li); }
  $('lista').replaceChildren(...itens);
  $('excluir-todos').hidden = !planos.length;
}

async function excluirTodos() {
  const n = document.querySelectorAll('#lista a').length;
  if (!confirm(`Excluir todos os ${n} PDF(s) da pasta? Os resultados do histórico não são apagados.`)) return;
  const r = await fetch('/planos/todos', { method: 'DELETE' });
  const d = await corpo(r);
  msg($('envio-msg'), r.ok ? `${d.excluidos} PDF(s) excluído(s).` : (d.erro || d.mensagem || 'Falha ao excluir'), r.ok ? 'ok' : 'erro');
  carregarPlanos();
}

async function excluir(nome) {
  if (!confirm(`Excluir "${nome}"?`)) return;
  const r = await fetch('/planos?arquivo=' + encodeURIComponent(nome), { method: 'DELETE' });
  const d = await corpo(r);
  msg($('envio-msg'), r.ok ? `"${nome}" excluído.` : (d.erro || d.mensagem || 'Falha ao excluir'), r.ok ? 'ok' : 'erro');
  carregarPlanos();
}

// Checagem prévia no navegador (o servidor repete todas e ainda confere se o PDF tem texto).
function motivoLocal(a) {
  if (!/\.pdf$/i.test(a.name) || (a.type && a.type !== 'application/pdf')) return 'Apenas arquivos .pdf são aceitos';
  if (a.size > MAX_MB * 1048576) return `Arquivo maior que ${MAX_MB} MB (${kb(a.size)})`;
  return '';
}

async function enviar(arquivos) {
  if (!arquivos.length || rodando) return;
  const locais = arquivos.filter(motivoLocal).map(a => ({ nome: a.name, motivo: motivoLocal(a) }));
  const validos = arquivos.filter(a => !motivoLocal(a));
  let r = { ok: true }, d = {};
  if (validos.length) {
    const form = new FormData();
    for (const a of validos) form.append('arquivos', a);
    msg($('envio-msg'), `Enviando e conferindo ${validos.length} arquivo(s)…`);
    try { r = await fetch('/planos', { method: 'POST', body: form }); d = await corpo(r); }
    catch { msg($('envio-msg'), 'Falha de conexão no envio', 'erro'); return; }
  }
  const salvos = d.salvos || [], recusados = locais.concat(d.recusados || []);
  const substituidos = salvos.filter(s => s.substituido).length;
  const partes = [];
  if (salvos.length) partes.push(`${salvos.length} enviado(s)` + (substituidos ? ` (${substituidos} substituído(s))` : ''));
  if (recusados.length) partes.push(`${recusados.length} recusado(s): ` + recusados.map(x => `${x.nome} (${x.motivo})`).join('; '));
  if (!partes.length) partes.push(d.erro || d.mensagem || 'Falha no envio');
  msg($('envio-msg'), partes.join(' · '), r.ok && !recusados.length ? 'ok' : 'erro');
  if (salvos.length) carregarPlanos();
}

async function revalidar(nome) {
  if (rodando) return;
  let r, d;
  try { r = await fetch('/validar?arquivo=' + encodeURIComponent(nome), { method: 'POST' }); d = await corpo(r); }
  catch { msg($('status-msg'), 'Sem conexão com o servidor; tente de novo', 'erro'); return; }
  if (r.ok || d.status === 'ocupado') { estavaRodando = true; atualizarStatus(); $('status-msg').scrollIntoView({ block: 'center' }); }
  else msg($('status-msg'), d.mensagem || d.erro || 'Não foi possível revalidar', 'erro');
}

// Botões ↻ dos cards e da lista de PDFs (o do card fica dentro do <summary>: não abre/fecha o card).
document.addEventListener('click', e => {
  const b = e.target.closest('.revalidar');
  if (!b) return;
  e.preventDefault(); e.stopPropagation();
  revalidar(b.dataset.arquivo);
});

// Filtros dos resultados: busca (sem acento/caixa), status e campo com problema. Ficam salvos na aba.
const semAcento = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
let filtro = { busca: '', grupo: '', status: '', campo: '' };

// Agrupamento dos cards, feito aqui com os data-* de cada card (chave, título e ordem de cada forma).
const SITUACOES = { OK: 'Aprovados', PENDENTE: 'Pendentes', REPROVADO: 'Reprovados', ERRO: 'Com erro' };
const CRITERIOS = {
  cp: c => [c.dataset.cp, c.dataset.cpTitulo, c.dataset.cpOrdem],
  periodo: c => [c.dataset.periodo, c.dataset.periodoTitulo, c.dataset.periodoOrdem],
  curso: c => [c.dataset.curso, c.dataset.cursoTitulo, c.dataset.cursoOrdem],
  docente: c => c.dataset.docente ? [c.dataset.docente, c.dataset.docente, '0' + semAcento(c.dataset.docente)]
    : ['-', 'Sem docente identificado', '1'],
  status: c => [c.dataset.status, SITUACOES[c.dataset.status] || c.dataset.status,
    String(Object.keys(SITUACOES).indexOf(c.dataset.status) + 10)],
  '': () => ['', '', ''],
};
let agruparPor = 'cp';

function agrupar() {
  const area = $('resultados');
  if (!area) return;
  const cards = [...area.querySelectorAll('.plano')].sort((a, b) => a.dataset.indice - b.dataset.indice);
  const grupos = new Map();
  for (const c of cards) {
    const [chave, titulo, ordem] = (CRITERIOS[agruparPor] || CRITERIOS.cp)(c);
    if (!grupos.has(chave)) grupos.set(chave, { titulo, ordem, cards: [] });
    grupos.get(chave).cards.push(c);
  }
  const secoes = [...grupos.entries()]
    .sort(([, a], [, b]) => a.ordem.localeCompare(b.ordem) || a.titulo.localeCompare(b.titulo, 'pt-BR'))
    .map(([chave, g]) => {
      const secao = document.createElement('section');
      secao.className = 'grupo';
      if (agruparPor) {
        const cab = document.createElement('h3'); cab.className = 'cab-grupo';
        const resumo = document.createElement('span');
        const n = s => g.cards.filter(c => c.dataset.status === s).length;
        const ok = n('OK'), pend = n('PENDENTE');
        resumo.textContent = `${g.cards.length} plano(s) · ${ok} OK · ${pend} pendente(s) · ${g.cards.length - ok - pend} com problemas`;
        const zip = document.createElement('a'); zip.className = 'zip'; zip.innerHTML = '<i class="fas fa-file-archive" aria-hidden="true"></i> PDFs (zip)';
        zip.dataset.titulo = g.titulo;
        cab.append(g.titulo, resumo, zip);
        secao.append(cab);
      }
      secao.append(...g.cards);
      return secao;
    });
  area.replaceChildren(...secoes);
  try { localStorage.setItem('agrupar', agruparPor); } catch {}
  aplicarFiltros();
}

// Link do zip de cada grupo: os PDFs dos planos visíveis nele (só a última validação guarda os PDFs).
function atualizarZips() {
  const validacao = $('resultados') && $('resultados').dataset.validacao;
  document.querySelectorAll('.grupo').forEach(g => {
    const zip = g.querySelector('.zip');
    if (!zip) return;
    const nomes = [...g.querySelectorAll('.plano[data-pdf]:not([hidden])')].map(c => c.dataset.arquivo);
    zip.hidden = !nomes.length;
    zip.href = `/validacoes/${encodeURIComponent(validacao)}/pdfs.zip?` + new URLSearchParams(
      [['nome', zip.dataset.titulo], ...nomes.map(n => ['arquivo', n])]);
  });
}

function aplicarFiltros() {
  if (!$('filtros')) return;
  const termos = semAcento(filtro.busca).split(/\s+/).filter(Boolean);
  const cards = [...document.querySelectorAll('.plano')];
  let visiveis = 0;
  for (const c of cards) {
    const nome = semAcento(c.dataset.arquivo + ' ' + (c.dataset.docente || ''));
    const ok = termos.every(t => nome.includes(t))
      && (!filtro.status || c.dataset.status === filtro.status)
      && (!filtro.campo || c.dataset.problemas.split('|').includes(filtro.campo))
      && (!filtro.grupo || c.dataset.cp === filtro.grupo);
    c.hidden = !ok;
    if (ok) visiveis++;
  }
  document.querySelectorAll('.chip').forEach(ch => ch.setAttribute('aria-pressed', String(ch.dataset.status === filtro.status)));
  $('busca').value = filtro.busca;
  $('campo').value = filtro.campo;
  if ($('grupo')) $('grupo').value = filtro.grupo;
  document.querySelectorAll('.grupo').forEach(g => g.hidden = !g.querySelector('.plano:not([hidden])'));
  atualizarZips();
  const ativo = filtro.busca || filtro.status || filtro.campo || filtro.grupo;
  $('contagem').textContent = ativo ? `${visiveis} de ${cards.length} plano(s)` : `${cards.length} plano(s)`;
  $('limpar-filtros').hidden = !ativo;
  $('sem-resultado').hidden = visiveis > 0;
  try { sessionStorage.setItem('filtros', JSON.stringify(filtro)); } catch {}
}

function iniciarFiltros() {
  if (!$('filtros')) return;
  try { Object.assign(filtro, JSON.parse(sessionStorage.getItem('filtros') || '{}')); } catch {}
  if (filtro.status && !document.querySelector(`.chip[data-status="${filtro.status}"]`)) filtro.status = '';
  if (filtro.campo && ![...$('campo').options].some(o => o.value === filtro.campo)) filtro.campo = '';
  $('busca').oninput = e => { filtro.busca = e.target.value; aplicarFiltros(); };
  $('campo').onchange = e => { filtro.campo = e.target.value; aplicarFiltros(); };
  if (filtro.grupo && !($('grupo') && [...$('grupo').options].some(o => o.value === filtro.grupo))) filtro.grupo = '';
  if ($('grupo')) $('grupo').onchange = e => { filtro.grupo = e.target.value; aplicarFiltros(); };
  try { const salvo = localStorage.getItem('agrupar'); if (salvo !== null && salvo in CRITERIOS) agruparPor = salvo; } catch {}
  $('agrupar').value = agruparPor;
  $('agrupar').onchange = e => { agruparPor = e.target.value; agrupar(); };
  document.querySelectorAll('.chip').forEach(ch => ch.onclick = () => { filtro.status = ch.dataset.status; aplicarFiltros(); });
  $('limpar-filtros').onclick = () => { filtro = { busca: '', grupo: '', status: '', campo: '' }; aplicarFiltros(); };
  agrupar();  // monta os grupos e aplica os filtros
}

// Ao voltar do relatório (#plano-N) ou depois de revalidar (#arquivo=nome), abre e destaca o plano.
function focarPlano() {
  let alvo = null;
  if (location.hash.startsWith('#plano-')) alvo = document.querySelector(location.hash);
  if (location.hash.startsWith('#arquivo=')) {
    const nome = decodeURIComponent(location.hash.slice(9));
    alvo = [...document.querySelectorAll('.plano')].find(c => c.dataset.arquivo === nome);
  }
  if (!alvo) return;
  if (alvo.hidden) { filtro = { busca: '', grupo: '', status: '', campo: '' }; aplicarFiltros(); }  // não esconder o plano pedido
  alvo.open = true;
  alvo.scrollIntoView({ block: 'start' });
  alvo.classList.add('destaque');
  setTimeout(() => alvo.classList.remove('destaque'), 2000);
}

async function validarTodos() {
  $('validar').disabled = true;
  let r, d;
  try { r = await fetch('/validar', { method: 'POST' }); d = await corpo(r); }
  catch { msg($('status-msg'), 'Sem conexão com o servidor; tente de novo', 'erro'); $('validar').disabled = false; return; }
  if (r.ok || d.status === 'ocupado') { estavaRodando = true; atualizarStatus(); }
  else { msg($('status-msg'), d.mensagem || 'Não foi possível iniciar', 'erro'); $('validar').disabled = false; }
}

if ($('historico')) $('historico').onchange = e => trocarValidacao(e.target.value);
// Quem só consulta não recebe os controles de validação e de PDFs.
if (ADMIN) {
  $('validar').onclick = validarTodos;
  $('excluir-todos').onclick = excluirTodos;
  $('escolher').onclick = () => $('arquivo').click();
  $('arquivo').onchange = e => { enviar([...e.target.files]); e.target.value = ''; };
  const zona = $('soltar');
  ['dragenter', 'dragover'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); if (!rodando) zona.classList.add('ativo'); }));
  ['dragleave', 'drop'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); zona.classList.remove('ativo'); }));
  zona.addEventListener('drop', e => enviar([...e.dataTransfer.files]));
  carregarPlanos();
}

atualizarStatus();
iniciarFiltros();
focarPlano();
