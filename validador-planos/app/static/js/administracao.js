// Administração: envio, lista e exclusão dos PDFs da pasta de planos. MAX_MB vem da página;
// $, msg, hora, corpo e rodando vêm de status.js (carregado antes).
function kb(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }

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

$('excluir-todos').onclick = excluirTodos;
$('escolher').onclick = () => $('arquivo').click();
$('arquivo').onchange = e => { enviar([...e.target.files]); e.target.value = ''; };
const zona = $('soltar');
['dragenter', 'dragover'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); if (!rodando) zona.classList.add('ativo'); }));
['dragleave', 'drop'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); zona.classList.remove('ativo'); }));
zona.addEventListener('drop', e => enviar([...e.dataTransfer.files]));
carregarPlanos();
