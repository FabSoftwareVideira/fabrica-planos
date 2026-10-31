// Barra de status da validação (dashboard e administração): andamento via /status, "Validar agora" e
// revalidação de um plano. Ao terminar, abre a validação mais recente no dashboard. ADMIN vem da página.
const $ = id => document.getElementById(id);
let rodando = false, estavaRodando = false, timer;

function msg(el, texto, tipo) { el.textContent = texto; el.className = 'msg' + (tipo ? ' ' + tipo : ''); el.hidden = !texto; }
function hora(iso) { return iso ? new Date(iso).toLocaleString('pt-BR') : ''; }
async function corpo(resp) { try { return await resp.json(); } catch { return {}; } }

function bloquear() {
  for (const b of [$('validar'), $('escolher')]) if (b) b.disabled = rodando;
  document.body.classList.toggle('validando', rodando);  // barra de status fixa no topo enquanto valida
  document.querySelectorAll('.excluir, .revalidar').forEach(b => b.disabled = rodando);
}

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

async function revalidar(nome) {
  if (rodando) return;
  let r, d;
  try { r = await fetch('/validar?arquivo=' + encodeURIComponent(nome), { method: 'POST' }); d = await corpo(r); }
  catch { msg($('status-msg'), 'Sem conexão com o servidor; tente de novo', 'erro'); return; }
  if (r.ok || d.status === 'ocupado') { estavaRodando = true; atualizarStatus(); $('status-msg').scrollIntoView({ block: 'center' }); }
  else msg($('status-msg'), d.mensagem || d.erro || 'Não foi possível revalidar', 'erro');
}

// Botões ↻ dos cards (dashboard) e da lista de PDFs (administração); o do card fica dentro do <summary>.
document.addEventListener('click', e => {
  const b = e.target.closest('.revalidar');
  if (!b) return;
  e.preventDefault(); e.stopPropagation();
  revalidar(b.dataset.arquivo);
});

async function validarTodos() {
  $('validar').disabled = true;
  let r, d;
  try { r = await fetch('/validar', { method: 'POST' }); d = await corpo(r); }
  catch { msg($('status-msg'), 'Sem conexão com o servidor; tente de novo', 'erro'); $('validar').disabled = false; return; }
  if (r.ok || d.status === 'ocupado') { estavaRodando = true; atualizarStatus(); }
  else { msg($('status-msg'), d.mensagem || 'Não foi possível iniciar', 'erro'); $('validar').disabled = false; }
}

if (ADMIN && $('validar')) $('validar').onclick = validarTodos;
atualizarStatus();
