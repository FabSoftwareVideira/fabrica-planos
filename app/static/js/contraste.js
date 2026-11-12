// Alto contraste: o tema salvo é aplicado no <head>, antes do CSS, para a página não piscar no tema claro.
// O botão da barra de utilidades alterna o tema e a escolha fica guardada neste navegador (chave `contraste`).
(() => {
  const raiz = document.documentElement;
  try { if (localStorage.getItem('contraste') === '1') raiz.classList.add('alto-contraste'); } catch (e) { /* sem armazenamento */ }
  const ligar = () => {
    document.querySelectorAll('[data-contraste]').forEach(botao => {
      botao.setAttribute('aria-pressed', String(raiz.classList.contains('alto-contraste')));
      botao.addEventListener('click', () => {
        const ligado = raiz.classList.toggle('alto-contraste');
        botao.setAttribute('aria-pressed', String(ligado));
        try { localStorage.setItem('contraste', ligado ? '1' : '0'); } catch (e) { /* sem armazenamento */ }
      });
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ligar);
  else ligar();
})();
