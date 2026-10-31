// Relatório: atalhos de teclado e revalidação do plano.

// Atalhos: Esc volta ao dashboard, ← e → passam para o plano anterior/próximo.
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.target.closest('input,textarea,select')) return;
  const a = document.querySelector('.nav a[data-tecla="' + e.key + '"]');
  if (a) location.href = a.href;
});

// Revalida o plano (atualiza a validação atual), acompanha /status e recarrega o relatório ao terminar.
const botao = document.getElementById('revalidar');
const rotuloRevalidar = botao && botao.innerHTML;
if (botao) botao.onclick = async () => {
  botao.disabled = true; botao.textContent = 'Revalidando…';
  let r, d = {};
  try { r = await fetch('/validar?arquivo=' + encodeURIComponent(botao.dataset.arquivo), { method: 'POST' }); d = await r.json(); }
  catch { r = { ok: false }; d = { mensagem: 'Sem conexão com o servidor' }; }
  if (!r.ok) { alert(d.mensagem || d.erro || 'Não foi possível revalidar'); botao.disabled = false; botao.innerHTML = rotuloRevalidar; return; }
  const esperar = async () => {
    try { const s = await (await fetch('/status')).json(); if (!s.rodando) { location.reload(); return; } } catch {}
    setTimeout(esperar, 2000);
  };
  esperar();
};
