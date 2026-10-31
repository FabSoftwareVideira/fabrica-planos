// Menu hambúrguer do cabeçalho (telas menores): abre e fecha o menu; fecha com Esc ou clicando fora.
(() => {
  const botao = document.querySelector('.menu-botao');
  const menu = document.getElementById('menu-principal');
  if (!botao || !menu) return;
  const abrir = aberto => {
    menu.classList.toggle('aberto', aberto);
    botao.setAttribute('aria-expanded', String(aberto));
    botao.setAttribute('aria-label', aberto ? 'Fechar menu' : 'Abrir menu');
    botao.querySelector('i').className = 'fas fa-' + (aberto ? 'times' : 'bars');
  };
  botao.addEventListener('click', () => abrir(!menu.classList.contains('aberto')));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') abrir(false); });
  document.addEventListener('click', e => { if (!e.target.closest('.cabecalho')) abrir(false); });
})();
