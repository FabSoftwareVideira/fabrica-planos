// Administração: lista, exclusão e ocultação dos PDFs da pasta de planos (quem envia são os professores);
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

carregarPlanos();
