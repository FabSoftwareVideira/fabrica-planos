// Administração: envio, lista e exclusão dos PDFs da pasta de planos. MAX_MB vem da página;
// $, msg, hora, corpo e rodando vêm de status.js (carregado antes).
// Excluir aparece só nos planos que quem vê enviou (ou sem dono) e apaga também a avaliação; nos de
// outras pessoas, Ocultar tira o plano do painel sem apagar nada (Mostrar desfaz).
function kb(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }

function botao(classe, icone, rotulo, acao) {
  const b = document.createElement('button');
  b.type = 'button'; b.className = classe; b.innerHTML = `<i class="fas ${icone}" aria-hidden="true"></i> ${rotulo}`;
  b.disabled = rodando; b.onclick = acao;
  return b;
}

async function carregarPlanos() {
  const { planos = [] } = await corpo(await fetch('/planos'));
  $('qtd-planos').textContent = `(${planos.length})`;
  const itens = planos.map(p => {
    const li = document.createElement('li');
    let titulo;
    if (p.na_pasta) {
      titulo = document.createElement('a');
      titulo.href = '/pdf?arquivo=' + encodeURIComponent(p.nome); titulo.target = '_blank'; titulo.rel = 'noopener';
    } else {  // o PDF já saiu da pasta; resta a avaliação na validação atual
      titulo = document.createElement('a');
      titulo.href = '/relatorio?arquivo=' + encodeURIComponent(p.nome);
    }
    titulo.innerHTML = '<i class="fas fa-file-pdf" aria-hidden="true"></i> '; titulo.append(p.nome);
    const info = document.createElement('span');
    const partes = p.na_pasta ? [kb(p.tamanho), hora(p.modificado)] : ['só a avaliação (PDF excluído)'];
    if (p.dono) partes.push(p.dono);
    if (p.oculto) partes.push('oculto do painel');
    info.textContent = partes.join(' · ');
    const acoes = [];
    if (p.na_pasta) {
      const val = botao('revalidar', 'fa-redo', 'Validar', null);
      val.dataset.arquivo = p.nome; val.title = 'Valida só este PDF e atualiza a última validação';
      acoes.push(val);
    }
    if (p.oculto) acoes.push(botao('ocultar', 'fa-eye', 'Mostrar', () => mostrar(p.nome)));
    else if (!p.pode_excluir) acoes.push(botao('ocultar', 'fa-eye-slash', 'Ocultar', () => ocultar(p.nome)));
    if (p.pode_excluir) acoes.push(botao('excluir', 'fa-trash-alt', 'Excluir', () => excluir(p.nome)));
    li.append(titulo, info, ...acoes);
    return li;
  });
  if (!itens.length) { const li = document.createElement('li'); li.innerHTML = '<span>Nenhum PDF na pasta.</span>'; itens.push(li); }
  $('lista').replaceChildren(...itens);
}

async function acaoNoPlano(url, metodo, sucesso) {
  const r = await fetch(url, { method: metodo });
  const d = await corpo(r);
  msg($('envio-msg'), r.ok ? sucesso : (d.erro || d.mensagem || 'Falha na operação'), r.ok ? 'ok' : 'erro');
  carregarPlanos();
}

function excluir(nome) {
  if (!confirm(`Excluir "${nome}"? O PDF e a avaliação dele no painel serão apagados.`)) return;
  acaoNoPlano('/planos?arquivo=' + encodeURIComponent(nome), 'DELETE', `"${nome}" excluído, com a avaliação.`);
}

function ocultar(nome) {
  acaoNoPlano('/planos/ocultar?arquivo=' + encodeURIComponent(nome), 'POST', `"${nome}" oculto do painel.`);
}

function mostrar(nome) {
  acaoNoPlano('/planos/ocultar?arquivo=' + encodeURIComponent(nome), 'DELETE', `"${nome}" de volta ao painel.`);
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

$('escolher').onclick = () => $('arquivo').click();
$('arquivo').onchange = e => { enviar([...e.target.files]); e.target.value = ''; };
const zona = $('soltar');
['dragenter', 'dragover'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); if (!rodando) zona.classList.add('ativo'); }));
['dragleave', 'drop'].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); zona.classList.remove('ativo'); }));
zona.addEventListener('drop', e => enviar([...e.dataTransfer.files]));
carregarPlanos();
