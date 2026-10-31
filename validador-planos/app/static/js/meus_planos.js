// "Meus planos": envio, lista com a situação de cada plano e exclusão. MAX_MB vem da página.
const $ = id => document.getElementById(id);
const CORES = { OK: '#22c55e', PENDENTE: '#eab308', INCOMPLETO: '#eab308' };
let timer;

function msg(el, texto, tipo) { el.textContent = texto; el.className = 'msg' + (tipo ? ' ' + tipo : ''); el.hidden = !texto; }
function hora(iso) { return iso ? new Date(iso).toLocaleString('pt-BR') : ''; }
async function corpo(resp) { try { return await resp.json(); } catch { return {}; } }
function selo(texto, cor) { const s = document.createElement('span'); s.className = 'br-tag status-plano'; s.style.background = cor; s.textContent = texto; return s; }

function situacao(p) {
  // Revisado pela coordenação/NDE/NDB: o parecer vale sobre a avaliação da IA
  if (p.revisao && p.situacao === 'avaliado') {
    const r = p.revisao;
    const quem = `${r.parecer} por ${r.revisor} (${r.papel}) em ${hora(r.revisado_em)}`;
    return [selo(r.status, CORES[r.status] || '#ef4444'), quem + (r.comentario ? ': ' + r.comentario : '.')];
  }
  if (p.situacao === 'na_fila') return [selo(`Na fila (${p.posicao}º)`, '#6b7280'), 'Aguardando a vez da avaliação automática.'];
  if (p.situacao === 'validando') return [selo('Avaliando…', '#2563eb'), 'A IA está lendo o plano; leva cerca de um minuto.'];
  if (p.situacao === 'aguardando') return [selo('Aguardando', '#6b7280'), 'Será avaliado na próxima validação geral.'];
  const detalhe = p.status === 'OK' ? 'Nenhum ajuste necessário.'
    : p.status === 'ERRO' || !p.problemas.length ? p.obs  // ERRO: o motivo (PDF ilegível, falha da IA)
    : 'Verificar: ' + p.problemas.join(', ') + '.';
  return [selo(p.status, CORES[p.status] || '#ef4444'), detalhe + ' Aguardando a revisão da coordenação/NDE.'];
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
      a.innerHTML = '<i class="fas fa-file-alt" aria-hidden="true"></i> Relatório'; acoes.append(a);
    }
    const pdf = document.createElement('a'); pdf.href = '/pdf?arquivo=' + encodeURIComponent(p.nome);
    pdf.target = '_blank'; pdf.rel = 'noopener'; pdf.innerHTML = '<i class="fas fa-file-pdf" aria-hidden="true"></i> PDF';
    const del = document.createElement('button'); del.type = 'button'; del.className = 'br-button small excluir';
    del.innerHTML = '<i class="fas fa-trash-alt" aria-hidden="true"></i> Excluir';
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
