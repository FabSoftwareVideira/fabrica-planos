from datetime import datetime
from html import escape
from urllib.parse import quote

from .csvsaida import CAMPOS_COLUNA

CORES = {
    'OK': '#22c55e',
    'INCOMPLETO': '#eab308',
    'PENDENTE': '#eab308',
}


def _cor(status):
    return CORES.get(status, '#ef4444')


def _badge(status):
    return (
        '<span style="background:' + _cor(status) + ';color:#fff;padding:2px 8px;border-radius:10px;'
        'font-size:11px;font-weight:600;white-space:nowrap">' + escape(status or '-') + '</span>'
    )


def _card(indice, linha, validacao, pdfs_guardados, ultima):
    nome = (linha.get('Arquivo') or '').replace('2024-1 - ', '').replace('.pdf', '')
    problemas = [rotulo for rotulo, _ in CAMPOS_COLUNA if linha.get(rotulo) != 'OK']
    topicos = []
    for rotulo, _ in CAMPOS_COLUNA:
        status = linha.get(rotulo, '')
        obs = linha.get(rotulo + ' Obs', '')
        topicos.append(
            '<div style="border:1px solid #e5e7eb;border-left:4px solid ' + _cor(status) + ';border-radius:8px;'
            'padding:10px 12px;background:#fafafa">'
            '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
            '<span style="font-size:13px;font-weight:600">' + escape(rotulo) + '</span>' + _badge(status) + '</div>'
            + ('<div style="font-size:12px;color:#6b7280;margin-top:6px">' + escape(obs) + '</div>' if obs else '')
            + '</div>'
        )
    arquivo = quote(linha.get('Arquivo', ''))
    estilo_link = (
        'style="font-size:13px;color:#2563eb;text-decoration:none;font-weight:600;white-space:nowrap" '
        'onclick="event.stopPropagation()"'
    )
    # O relatório abre na mesma aba e volta para este card (âncora #plano-N).
    link = '<a href="/relatorio?validacao=' + validacao + '&arquivo=' + arquivo + '" ' + estilo_link + '>📝 Relatório</a>'
    if linha.get('Arquivo') in pdfs_guardados:
        link += ('<a href="/validacoes/' + validacao + '/pdf?arquivo=' + arquivo + '" target="_blank" rel="noopener" '
                 + estilo_link + '>📄 Abrir PDF</a>')
    if ultima:  # revalidar atualiza a última validação; as anteriores ficam como estão
        link += ('<button type="button" class="revalidar" data-arquivo="' + escape(linha.get('Arquivo', ''), quote=True)
                 + '" title="Valida de novo só este plano, com o PDF atual da pasta">↻ Revalidar</button>')
    observacao = linha.get('Observação Geral', '')
    return (
        '<details id="plano-' + str(indice) + '" class="plano" data-arquivo="'
        + escape(linha.get('Arquivo', ''), quote=True) + '" data-status="' + escape(linha.get('Status Geral', ''))
        + '" data-problemas="' + escape('|'.join(problemas), quote=True) + '" '
        'style="background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:12px">'
        '<summary style="display:flex;align-items:center;gap:12px;padding:14px 16px;cursor:pointer;list-style:none">'
        '<span style="font-weight:600;flex:1">' + escape(nome) + '</span>' + _badge(linha.get('Status Geral', ''))
        + link + '<span style="color:#9ca3af;font-size:12px">▼ detalhes</span></summary>'
        '<div style="padding:0 16px 16px">'
        + ('<p style="margin:0 0 12px;font-size:13px;color:#6b7280">' + escape(observacao) + '</p>' if observacao else '')
        + '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px">'
        + ''.join(topicos) + '</div></div></details>'
    )


# Painéis de controle: validação (com progresso) e gestão dos PDFs, atualizados por /status e /planos.
ESTILO = (
    '.painel{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:16px}'
    '.painel h2{margin:0 0 12px;font-size:18px}'
    '.linha{display:flex;align-items:center;gap:12px;flex-wrap:wrap}'
    '.botao{border:0;border-radius:8px;padding:10px 18px;font:inherit;font-weight:600;cursor:pointer;'
    'background:#2563eb;color:#fff}'
    '.botao:disabled{background:#9ca3af;cursor:not-allowed}'
    '.botao.leve{background:#eef2ff;color:#2563eb;padding:6px 12px}'
    '.botao.leve:disabled{background:#f3f4f6;color:#9ca3af}'
    '.barra{height:10px;background:#e5e7eb;border-radius:5px;overflow:hidden;margin-top:12px}'
    '.barra>div{height:100%;width:0;background:#2563eb;transition:width .4s}'
    '.msg{font-size:14px;color:#6b7280;margin:0}.msg.erro{color:#dc2626}.msg.ok{color:#16a34a}'
    '.soltar{border:2px dashed #cbd5e1;border-radius:10px;padding:18px;text-align:center;color:#6b7280;'
    'font-size:14px;margin-bottom:12px}'
    '.soltar.ativo{border-color:#2563eb;background:#eff6ff;color:#2563eb}'
    '.arquivos{list-style:none;margin:12px 0 0;padding:0;max-height:320px;overflow:auto}'
    '.arquivos li{display:flex;align-items:center;gap:10px;padding:8px 4px;border-top:1px solid #f1f5f9;font-size:14px}'
    '.arquivos li a{flex:1;color:#111827;text-decoration:none;overflow-wrap:anywhere}'
    '.arquivos li span{color:#9ca3af;font-size:12px;white-space:nowrap}'
    '.excluir{border:0;background:none;color:#dc2626;cursor:pointer;font:inherit;font-size:13px;padding:4px 6px}'
    '.excluir:disabled{color:#d1d5db;cursor:not-allowed}'
    '.dica{font-size:12px;color:#9ca3af;margin:8px 0 0}'
    '.cab-resultados{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:32px 0 4px}'
    '.cab-resultados h2{margin:0 auto 0 0;font-size:20px}'
    '.cab-resultados select{font:inherit;font-size:14px;padding:7px 10px;border:1px solid #cbd5e1;border-radius:8px;'
    'background:#fff;max-width:100%}'
    'a.botao{text-decoration:none;display:inline-block;font-size:14px}'
    '.antiga{background:#fef3c7;color:#92400e;border-radius:8px;padding:10px 14px;margin:12px 0;font-size:14px}'
    '.antiga a{color:#92400e;font-weight:600}'
    '.cab-planos{display:flex;align-items:center;gap:8px;margin-bottom:12px}'
    '.cab-planos h2{margin:0 auto 0 0}'
    '.revalidar{border:0;background:none;color:#2563eb;font:inherit;font-size:13px;font-weight:600;cursor:pointer;'
    'padding:0;white-space:nowrap}'
    '.revalidar:disabled{color:#d1d5db;cursor:not-allowed}'
    '.arquivos .revalidar{font-weight:400;padding:4px 6px}'
    '.filtros{background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:14px 16px;'
    'margin-bottom:16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}'
    '.filtros input,.filtros select{font:inherit;font-size:14px;padding:7px 10px;border:1px solid #cbd5e1;'
    'border-radius:8px;background:#fff}'
    '.filtros input{flex:1 1 220px;min-width:0}'
    '.chips{display:flex;gap:6px;flex-wrap:wrap}'
    '.chip{border:1px solid #cbd5e1;background:#fff;border-radius:999px;padding:5px 12px;font:inherit;font-size:13px;'
    'cursor:pointer;color:#374151}'
    '.chip[aria-pressed="true"]{background:#1f2937;border-color:#1f2937;color:#fff}'
    '.contagem{font-size:13px;color:#6b7280;margin-left:auto}'
    '.limpar{border:0;background:none;color:#2563eb;font:inherit;font-size:13px;cursor:pointer}'
    '.plano[hidden]{display:none}'
    '.plano{scroll-margin-top:16px;transition:box-shadow .3s}'
    '.plano.destaque{box-shadow:0 0 0 3px #93c5fd !important}'
    '.usuario{margin:-16px 0 24px;font-size:14px;color:#6b7280}.usuario a{color:#2563eb}'
)

PAINEL_VALIDACAO = (
    '<section class="painel"><h2>Validação</h2><div class="linha">{BOTAO}'
    '<p class="msg" id="status-msg">Carregando…</p></div>'
    '<div class="barra" id="barra" hidden><div></div></div></section>'
)

# Só para administradores: envio e exclusão dos PDFs.
PAINEL_PLANOS = (
    '<section class="painel"><div class="cab-planos"><h2>Planos (PDFs) <span class="msg" id="qtd-planos"></span></h2>'
    '<button class="excluir" id="excluir-todos" type="button">Excluir todos</button></div>'
    '<div class="soltar" id="soltar">Arraste PDFs para cá ou '
    '<button class="botao leve" id="escolher" type="button">escolha arquivos</button>'
    '<input type="file" id="arquivo" accept="application/pdf,.pdf" multiple hidden>'
    '<p class="dica">Somente PDF com texto selecionável (não digitalizado), até {MAX_MB} MB por arquivo.</p></div>'
    '<p class="msg" id="envio-msg" hidden></p>'
    '<ul class="arquivos" id="lista"></ul></section>'
)

SCRIPT = r"""
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
    a.textContent = '📄 ' + p.nome;
    const info = document.createElement('span');
    info.textContent = kb(p.tamanho) + ' · ' + hora(p.modificado) + (p.dono ? ' · ' + p.dono : '');
    const val = document.createElement('button');
    val.className = 'revalidar'; val.textContent = '↻ Validar'; val.disabled = rodando; val.dataset.arquivo = p.nome;
    val.title = 'Valida só este PDF e atualiza a última validação';
    const del = document.createElement('button');
    del.className = 'excluir'; del.textContent = 'Excluir'; del.disabled = rodando;
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
let filtro = { busca: '', status: '', campo: '' };

function aplicarFiltros() {
  if (!$('filtros')) return;
  const termos = semAcento(filtro.busca).split(/\s+/).filter(Boolean);
  const cards = [...document.querySelectorAll('.plano')];
  let visiveis = 0;
  for (const c of cards) {
    const nome = semAcento(c.dataset.arquivo);
    const ok = termos.every(t => nome.includes(t))
      && (!filtro.status || c.dataset.status === filtro.status)
      && (!filtro.campo || c.dataset.problemas.split('|').includes(filtro.campo));
    c.hidden = !ok;
    if (ok) visiveis++;
  }
  document.querySelectorAll('.chip').forEach(ch => ch.setAttribute('aria-pressed', String(ch.dataset.status === filtro.status)));
  $('busca').value = filtro.busca;
  $('campo').value = filtro.campo;
  const ativo = filtro.busca || filtro.status || filtro.campo;
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
  document.querySelectorAll('.chip').forEach(ch => ch.onclick = () => { filtro.status = ch.dataset.status; aplicarFiltros(); });
  $('limpar-filtros').onclick = () => { filtro = { busca: '', status: '', campo: '' }; aplicarFiltros(); };
  aplicarFiltros();
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
  if (alvo.hidden) { filtro = { busca: '', status: '', campo: '' }; aplicarFiltros(); }  // não esconder o plano pedido
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
"""


STATUS_FILTRO = [('OK', 'Aprovados'), ('PENDENTE', 'Pendentes'), ('REPROVADO', 'Reprovados'), ('ERRO', 'Com erro')]


def _filtros(linhas):
    """Barra de filtros dos cards (busca, status e campo com problema); a filtragem é feita no navegador."""
    chips = '<button type="button" class="chip" data-status="" aria-pressed="true">Todos (' + str(len(linhas)) + ')</button>'
    for status, rotulo in STATUS_FILTRO:
        n = sum(1 for l in linhas if l.get('Status Geral') == status)
        if n:
            chips += ('<button type="button" class="chip" data-status="' + status + '" aria-pressed="false">'
                      + rotulo + ' (' + str(n) + ')</button>')
    campos = ''.join(
        '<option value="' + escape(rotulo, quote=True) + '">' + escape(rotulo) + '</option>'
        for rotulo, _ in CAMPOS_COLUNA
        if any(l.get(rotulo) != 'OK' for l in linhas)
    )
    return (
        '<div class="filtros" id="filtros">'
        '<input type="search" id="busca" placeholder="Buscar por disciplina ou docente" aria-label="Buscar planos">'
        '<div class="chips" role="group" aria-label="Filtrar por status">' + chips + '</div>'
        '<select id="campo" aria-label="Campo com problema"><option value="">Qualquer campo</option>' + campos + '</select>'
        '<span class="contagem" id="contagem"></span>'
        '<button type="button" class="limpar" id="limpar-filtros" hidden>Limpar filtros</button>'
        '</div>'
    )


def data_br(iso):
    try:
        return datetime.fromisoformat(iso).strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return '—'


def _rotulo_execucao(meta, ultima):
    partes = [data_br(meta.get('finalizado_em')), f"{meta.get('total', 0)} plano(s)",
              f"{meta.get('ok', 0)} OK", f"{meta.get('pendentes', 0)} pendente(s)",
              f"{meta.get('problemas', 0)} com problemas"]
    if meta.get('erro'):
        partes.append('interrompida')
    return ' · '.join(partes) + (' (última)' if ultima else '')


def _cabecalho_resultados(execucoes, execucao):
    if execucao is None:
        return '<div class="cab-resultados"><h2>Resultados</h2></div>'
    opcoes = ''.join(
        '<option value="' + escape(e.id, quote=True) + '"' + (' selected' if e.id == execucao.id else '') + '>'
        + escape(_rotulo_execucao(e.meta(), i == 0)) + '</option>'
        for i, e in enumerate(execucoes)
    )
    botoes = ''
    if execucao.pdfs():
        botoes += '<a class="botao leve" href="/validacoes/' + execucao.id + '/pdfs.zip">⬇ PDFs (zip)</a>'
    botoes += '<a class="botao leve" href="/validacoes/' + execucao.id + '/csv">⬇ CSV</a>'
    meta = execucao.meta()
    linha_meta = 'Concluída em ' + data_br(meta.get('finalizado_em'))
    if meta.get('modelo'):
        linha_meta += ' · modelo ' + escape(meta['modelo'])
    if meta.get('erro'):
        linha_meta += (' · <span style="color:#dc2626">interrompida após ' + str(meta.get('processados', 0)) + ' de '
                       + str(meta.get('total', 0)) + ' plano(s): ' + escape(meta['erro']) + '</span>')
    aviso = ''
    if execucao.id != execucoes[0].id:
        aviso = ('<div class="antiga">Você está vendo uma validação anterior. Os PDFs dela não são guardados, só o '
                 'resultado. <a href="/dashboard">Ver a última validação</a></div>')
    return (
        '<div class="cab-resultados"><h2>Resultados</h2>'
        '<select id="historico" aria-label="Validação exibida">' + opcoes + '</select>' + botoes + '</div>'
        '<p style="margin:0 0 16px;color:#6b7280;font-size:14px">' + linha_meta + '</p>' + aviso
    )


def _usuario(email, admin):
    if not email:
        return ''
    return ('<p class="usuario">' + escape(email) + ' · ' + ('administrador' if admin else 'consulta')
            + ' · <a href="/meus-planos">Meus planos</a> · <a href="/oauth2/sign_out">Sair</a></p>')


# No lugar do painel de PDFs (só do administrador): leva o professor à entrega do próprio plano.
PAINEL_ENTREGA = (
    '<section class="painel"><h2>Entregar plano de ensino</h2><div class="linha">'
    '<p class="msg">Envie o PDF do seu plano e acompanhe a avaliação automática.</p>'
    '<a class="botao" href="/meus-planos">Meus planos</a></div></section>'
)


def gerar_html(linhas, max_mb=10, execucoes=(), execucao=None, usuario='', admin=True):
    total = len(linhas)
    ok = sum(1 for l in linhas if l.get('Status Geral') == 'OK')
    pendente = sum(1 for l in linhas if l.get('Status Geral') == 'PENDENTE')
    problema = total - ok - pendente

    def pct(n):
        return round(n / total * 100) if total else 0

    cartoes = (
        '<div style="background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.1)">'
        '<div style="font-size:13px;color:#6b7280">Total de planos</div>'
        '<div style="font-size:32px;font-weight:700">' + str(total) + '</div></div>'
    )
    for rotulo, valor, cor in (('Aprovados', ok, '#22c55e'), ('Pendentes', pendente, '#eab308'),
                               ('Com problemas', problema, '#ef4444')):
        cartoes += (
            '<div style="background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.1);'
            'border-left:4px solid ' + cor + '"><div style="font-size:13px;color:#6b7280">' + rotulo + '</div>'
            '<div style="font-size:32px;font-weight:700;color:' + cor + '">' + str(valor)
            + ' <span style="font-size:14px;color:#9ca3af">(' + str(pct(valor)) + '%)</span></div></div>'
        )

    if execucao is not None and linhas:
        pdfs = set(execucao.pdfs())
        ultima = execucao.id == execucoes[0].id and admin  # revalidar é coisa de administrador
        corpo = _filtros(linhas) + ''.join(_card(i, l, execucao.id, pdfs, ultima) for i, l in enumerate(linhas))
        corpo += '<p class="msg" id="sem-resultado" hidden>Nenhum plano corresponde aos filtros.</p>'
    else:
        corpo = '<p style="color:#6b7280">Nenhuma validação concluída ainda.</p>'
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Validação de Planos de Ensino</title>'
        '<style>details summary::-webkit-details-marker{display:none}' + ESTILO + '</style></head>'
        '<body style="margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f3f4f6;color:#111827">'
        '<div style="max-width:1100px;margin:0 auto;padding:32px 16px">'
        '<h1 style="margin:0 0 24px">📋 Validação de Planos de Ensino</h1>' + _usuario(usuario, admin)
        + PAINEL_VALIDACAO.replace('{BOTAO}', '<button class="botao" id="validar">▶ Validar agora</button>' if admin else '')
        + (PAINEL_PLANOS.replace('{MAX_MB}', str(max_mb)) if admin else PAINEL_ENTREGA)
        + _cabecalho_resultados(list(execucoes), execucao) +
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:24px">'
        + cartoes + '</div>' + corpo +
        '</div><script>const MAX_MB = ' + str(int(max_mb)) + ', ADMIN = ' + ('true' if admin else 'false') + ';' + SCRIPT + '</script></body></html>'
    )
