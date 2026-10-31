// Dashboard: filtros, agrupamento e destaque dos cards dos planos, e troca da validação exibida.
// $ e a barra de status vêm de status.js (carregado antes).
function trocarValidacao(id) { location.href = '/dashboard' + (id ? '?validacao=' + encodeURIComponent(id) : ''); }

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

if ($('historico')) $('historico').onchange = e => trocarValidacao(e.target.value);
iniciarFiltros();
focarPlano();
