from html import escape

from .dashboard import ESTILO as ESTILO_DASHBOARD

# Página "Meus planos": o servidor envia os próprios PDFs (a entrega oficial) e acompanha a avaliação,
# que começa logo após o envio ou espera a vez na fila. A lista vem de /meus-planos/lista.
ESTILO = ESTILO_DASHBOARD + (
    '.meus{list-style:none;margin:0;padding:0}'
    '.meus li{border-top:1px solid #f1f5f9;padding:14px 4px;display:flex;flex-wrap:wrap;gap:6px 12px;'
    'align-items:center}'
    '.meus li:first-child{border-top:0}'
    '.meus .nome{flex:1 1 240px;font-weight:600;overflow-wrap:anywhere}'
    '.meus .sub{display:block;font-size:12px;font-weight:400;color:#6b7280;margin-top:2px}'
    '.meus li.cab-grupo{display:block;border-top:0;padding:18px 4px 6px;font-size:15px;font-weight:700;color:#374151}'
    '.meus li.cab-grupo:first-child{padding-top:0}'
    '.meus .info{flex-basis:100%;font-size:13px;color:#6b7280;overflow-wrap:anywhere}'
    '.meus .acoes{display:flex;flex-wrap:wrap;gap:12px;align-items:center;font-size:13px}'
    '.meus .acoes a{color:#2563eb;font-weight:600;text-decoration:none}'
    '.selo{color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap}'
    '.aviso{background:#eff6ff;color:#1e40af;border-radius:8px;padding:10px 14px;font-size:14px;margin:0 0 16px}'
)

CORPO = (
    '<section class="painel"><h2>Enviar plano de ensino</h2>'
    '<p class="aviso">O PDF enviado aqui é a entrega do plano ao NDE. A avaliação automática começa logo em '
    'seguida; se algo precisar de ajuste, corrija no SIGAA, gere o PDF de novo e envie com o mesmo nome para '
    'substituir.</p>'
    '<div class="soltar" id="soltar">Arraste o PDF para cá ou '
    '<button class="botao leve" id="escolher" type="button">escolha arquivos</button>'
    '<input type="file" id="arquivo" accept="application/pdf,.pdf" multiple hidden>'
    '<p class="dica">PDF gerado pelo SIGAA (com texto selecionável), até {MAX_MB} MB. Use um nome que identifique a '
    'disciplina, por exemplo: <b>2026-1 - Banco de Dados II - Seu Nome.pdf</b></p></div>'
    '<p class="msg" id="envio-msg" hidden></p></section>'
    '<section class="painel"><h2>Meus planos <span class="msg" id="qtd"></span></h2>'
    '<ul class="meus" id="lista"><li><span class="msg">Carregando…</span></li></ul></section>'
)

SCRIPT = r"""
const $ = id => document.getElementById(id);
const CORES = { OK: '#22c55e', PENDENTE: '#eab308', INCOMPLETO: '#eab308' };
let timer;

function msg(el, texto, tipo) { el.textContent = texto; el.className = 'msg' + (tipo ? ' ' + tipo : ''); el.hidden = !texto; }
function hora(iso) { return iso ? new Date(iso).toLocaleString('pt-BR') : ''; }
async function corpo(resp) { try { return await resp.json(); } catch { return {}; } }
function selo(texto, cor) { const s = document.createElement('span'); s.className = 'selo'; s.style.background = cor; s.textContent = texto; return s; }

function situacao(p) {
  if (p.situacao === 'na_fila') return [selo(`Na fila (${p.posicao}º)`, '#6b7280'), 'Aguardando a vez da avaliação automática.'];
  if (p.situacao === 'validando') return [selo('Avaliando…', '#2563eb'), 'A IA está lendo o plano; leva cerca de um minuto.'];
  if (p.situacao === 'aguardando') return [selo('Aguardando', '#6b7280'), 'Será avaliado na próxima validação geral.'];
  const detalhe = p.status === 'OK' ? 'Nenhum ajuste necessário.'
    : p.status === 'ERRO' || !p.problemas.length ? p.obs  // ERRO: o motivo (PDF ilegível, falha da IA)
    : 'Verificar: ' + p.problemas.join(', ') + '.';
  return [selo(p.status, CORES[p.status] || '#ef4444'), detalhe];
}

function item(p) {
    const li = document.createElement('li');
    const nome = document.createElement('span'); nome.className = 'nome'; nome.textContent = p.nome;
    if (p.componente) {
      const sub = document.createElement('span'); sub.className = 'sub'; sub.textContent = p.componente;
      nome.append(sub);
    }
    const [marca, detalhe] = situacao(p);
    const acoes = document.createElement('span'); acoes.className = 'acoes';
    acoes.append(marca);
    if (p.situacao === 'avaliado') {
      const a = document.createElement('a'); a.href = '/relatorio?arquivo=' + encodeURIComponent(p.nome);
      a.textContent = '📝 Relatório'; acoes.append(a);
    }
    const pdf = document.createElement('a'); pdf.href = '/pdf?arquivo=' + encodeURIComponent(p.nome);
    pdf.target = '_blank'; pdf.rel = 'noopener'; pdf.textContent = '📄 PDF';
    const del = document.createElement('button'); del.className = 'excluir'; del.textContent = 'Excluir';
    del.onclick = () => excluir(p.nome);
    acoes.append(pdf, del);
    const info = document.createElement('span'); info.className = 'info';
    info.textContent = `Enviado em ${hora(p.enviado_em)} · ${detalhe}`;
    li.append(nome, acoes, info);
    return li;
}

async function carregar() {
  clearTimeout(timer);
  let r;
  try { r = await fetch('/meus-planos/lista'); }
  catch { timer = setTimeout(carregar, 10000); return; }
  if (r.status === 401) { location.reload(); return; }  // sessão expirou: recarregar leva ao login
  const { planos = [] } = await corpo(r);
  $('qtd').textContent = `(${planos.length})`;
  // Lista agrupada por curso e período: o servidor já manda na ordem dos grupos.
  const itens = [];
  let grupo = null;
  for (const p of planos) {
    if (p.grupo !== grupo) {
      grupo = p.grupo;
      const cab = document.createElement('li'); cab.className = 'cab-grupo'; cab.textContent = p.grupo_titulo;
      itens.push(cab);
    }
    itens.push(item(p));
  }
  if (!itens.length) { const li = document.createElement('li'); li.innerHTML = '<span class="msg">Você ainda não enviou planos.</span>'; itens.push(li); }
  $('lista').replaceChildren(...itens);
  const andamento = planos.some(p => p.situacao === 'na_fila' || p.situacao === 'validando');
  timer = setTimeout(carregar, andamento ? 3000 : 30000);
}

async function excluir(nome) {
  if (!confirm(`Excluir "${nome}"? O plano deixa de constar como entregue.`)) return;
  const r = await fetch('/meus-planos?arquivo=' + encodeURIComponent(nome), { method: 'DELETE' });
  const d = await corpo(r);
  msg($('envio-msg'), r.ok ? `"${nome}" excluído.` : (d.erro || d.mensagem || 'Falha ao excluir'), r.ok ? 'ok' : 'erro');
  carregar();
}

function motivoLocal(a) {
  if (!/\.pdf$/i.test(a.name) || (a.type && a.type !== 'application/pdf')) return 'Apenas arquivos .pdf são aceitos';
  if (a.size > MAX_MB * 1048576) return `Arquivo maior que ${MAX_MB} MB`;
  return '';
}

async function enviar(arquivos) {
  if (!arquivos.length) return;
  const locais = arquivos.filter(motivoLocal).map(a => ({ nome: a.name, motivo: motivoLocal(a) }));
  const validos = arquivos.filter(a => !motivoLocal(a));
  let d = {};
  if (validos.length) {
    const form = new FormData();
    for (const a of validos) form.append('arquivos', a);
    msg($('envio-msg'), `Enviando e conferindo ${validos.length} arquivo(s)…`);
    try { d = await corpo(await fetch('/meus-planos', { method: 'POST', body: form })); }
    catch { msg($('envio-msg'), 'Falha de conexão no envio', 'erro'); return; }
  }
  const salvos = d.salvos || [], recusados = locais.concat(d.recusados || []);
  const partes = [];
  if (salvos.length) partes.push(`${salvos.length} enviado(s); a avaliação começou`);
  if (recusados.length) partes.push(`${recusados.length} recusado(s): ` + recusados.map(x => `${x.nome} (${x.motivo})`).join('; '));
  if (!partes.length) partes.push(d.erro || d.mensagem || 'Falha no envio');
  msg($('envio-msg'), partes.join(' · '), recusados.length || !salvos.length ? 'erro' : 'ok');
  carregar();
}

$('escolher').onclick = () => $('arquivo').click();
$('arquivo').onchange = e => { enviar([...e.target.files]); e.target.value = ''; };
const zona = $('soltar');
['dragenter', 'dragover'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); zona.classList.add('ativo'); }));
['dragleave', 'drop'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); zona.classList.remove('ativo'); }));
zona.addEventListener('drop', e => enviar([...e.dataTransfer.files]));
carregar();
"""


def gerar_html(email='', max_mb=10):
    usuario = ''
    if email:
        usuario = ('<p class="usuario">' + escape(email) + ' · <a href="/dashboard">Painel geral</a> · '
                   '<a href="/oauth2/sign_out">Sair</a></p>')
    else:
        usuario = '<p class="usuario"><a href="/dashboard">Painel geral</a></p>'
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Meus planos · Validação de Planos de Ensino</title><style>' + ESTILO + '</style></head>'
        '<body style="margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f3f4f6;color:#111827">'
        '<div style="max-width:900px;margin:0 auto;padding:32px 16px">'
        '<h1 style="margin:0 0 24px">📋 Meus planos de ensino</h1>' + usuario
        + CORPO.replace('{MAX_MB}', str(max_mb)) +
        '</div><script>const MAX_MB = ' + str(int(max_mb)) + ';' + SCRIPT + '</script></body></html>'
    )
