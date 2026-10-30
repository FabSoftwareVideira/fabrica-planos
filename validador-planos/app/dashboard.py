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


def _card(indice, linha):
    nome = (linha.get('Arquivo') or '').replace('2024-1 - ', '').replace('.pdf', '')
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
    link = (
        '<a href="/relatorio?arquivo=' + arquivo + '" ' + estilo_link + '>📝 Relatório</a>'
        '<a href="/pdf?arquivo=' + arquivo + '" target="_blank" rel="noopener" ' + estilo_link + '>📄 Abrir PDF</a>'
    )
    observacao = linha.get('Observação Geral', '')
    return (
        '<details id="plano-' + str(indice) + '" class="plano" '
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
    '.plano{scroll-margin-top:16px;transition:box-shadow .3s}'
    '.plano.destaque{box-shadow:0 0 0 3px #93c5fd !important}'
)

PAINEIS = (
    '<section class="painel"><h2>Validação</h2><div class="linha">'
    '<button class="botao" id="validar">▶ Validar agora</button>'
    '<p class="msg" id="status-msg">Carregando…</p></div>'
    '<div class="barra" id="barra" hidden><div></div></div></section>'
    '<section class="painel"><h2>Planos (PDFs) <span class="msg" id="qtd-planos"></span></h2>'
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
  $('validar').disabled = rodando;
  $('escolher').disabled = rodando;
  document.querySelectorAll('.excluir').forEach(b => b.disabled = rodando);
}

async function atualizarStatus() {
  clearTimeout(timer);
  let s;
  try { s = await (await fetch('/status')).json(); }
  catch { msg($('status-msg'), 'Sem conexão com o servidor', 'erro'); timer = setTimeout(atualizarStatus, 5000); return; }
  rodando = s.rodando;
  bloquear();
  const barra = $('barra');
  if (rodando) {
    barra.hidden = false;
    barra.firstChild.style.width = (s.total ? s.processados / s.total * 100 : 0) + '%';
    msg($('status-msg'), `Validando ${Math.min(s.processados + 1, s.total)} de ${s.total}: ${s.atual || '…'}`);
  } else {
    barra.hidden = true;
    if (s.erro) msg($('status-msg'), `Última validação falhou (${hora(s.finalizado_em)}): ${s.erro}`, 'erro');
    else if (s.finalizado_em) msg($('status-msg'), `Validação concluída em ${hora(s.finalizado_em)}`, 'ok');
    else msg($('status-msg'), 'Nenhuma validação em andamento');
  }
  // Ao terminar um lote, recarrega a página para mostrar os resultados novos.
  if (estavaRodando && !rodando) { location.reload(); return; }
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
    info.textContent = kb(p.tamanho) + ' · ' + hora(p.modificado);
    const del = document.createElement('button');
    del.className = 'excluir'; del.textContent = 'Excluir'; del.disabled = rodando;
    del.onclick = () => excluir(p.nome);
    li.append(a, info, del);
    return li;
  });
  if (!itens.length) { const li = document.createElement('li'); li.innerHTML = '<span>Nenhum PDF na pasta.</span>'; itens.push(li); }
  $('lista').replaceChildren(...itens);
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

// Ao voltar do relatório (#plano-N), abre e destaca o plano de onde o usuário saiu.
function focarPlano() {
  const alvo = location.hash.startsWith('#plano-') && document.querySelector(location.hash);
  if (!alvo) return;
  alvo.open = true;
  alvo.scrollIntoView({ block: 'start' });
  alvo.classList.add('destaque');
  setTimeout(() => alvo.classList.remove('destaque'), 2000);
}

$('validar').onclick = async () => {
  $('validar').disabled = true;
  const r = await fetch('/validar', { method: 'POST' });
  const d = await corpo(r);
  if (r.ok || d.status === 'ocupado') { estavaRodando = true; atualizarStatus(); }
  else { msg($('status-msg'), d.mensagem || 'Não foi possível iniciar', 'erro'); $('validar').disabled = false; }
};
$('escolher').onclick = () => $('arquivo').click();
$('arquivo').onchange = e => { enviar([...e.target.files]); e.target.value = ''; };
const zona = $('soltar');
['dragenter', 'dragover'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); if (!rodando) zona.classList.add('ativo'); }));
['dragleave', 'drop'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); zona.classList.remove('ativo'); }));
zona.addEventListener('drop', e => enviar([...e.dataTransfer.files]));

atualizarStatus();
carregarPlanos();
focarPlano();
"""


def gerar_html(linhas, atualizado_em, max_mb=10):
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

    corpo = ''.join(_card(i, l) for i, l in enumerate(linhas)) if linhas else (
        '<p style="color:#6b7280">Nenhuma validação concluída ainda.</p>'
    )
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Validação de Planos de Ensino</title>'
        '<style>details summary::-webkit-details-marker{display:none}' + ESTILO + '</style></head>'
        '<body style="margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f3f4f6;color:#111827">'
        '<div style="max-width:1100px;margin:0 auto;padding:32px 16px">'
        '<h1 style="margin:0 0 24px">📋 Validação de Planos de Ensino</h1>'
        + PAINEIS.replace('{MAX_MB}', str(max_mb)) +
        '<h2 style="margin:32px 0 4px;font-size:20px">Resultados</h2>'
        '<p style="margin:0 0 16px;color:#6b7280">Última validação: ' + escape(atualizado_em or '—') + '</p>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:24px">'
        + cartoes + '</div>' + corpo +
        '</div><script>const MAX_MB = ' + str(int(max_mb)) + ';' + SCRIPT + '</script></body></html>'
    )
