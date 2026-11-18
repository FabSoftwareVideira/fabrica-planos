"""Confere a configuração do gov.br (login e assinatura) e se o servidor alcança os endereços dele. Não mostra
segredos: só diz se estão preenchidos. Rode dentro do contêiner do app:

    docker compose exec app python -m app.diagnostico_govbr

Um "sem resposta" aqui explica o "Falha na troca do código com o gov.br" (ConnectTimeout) do log: o servidor
não chega ao gov.br (firewall, IPv6 sem rota ou bloqueio de IP fora do Brasil)."""
import sys

import requests

from . import config


def _alcanca(url):
    """'responde (HTTP n)' ou 'sem resposta (motivo)'. Qualquer código HTTP prova que a rede chega lá."""
    try:
        r = requests.get(url, timeout=10, allow_redirects=False)
        return True, f'responde (HTTP {r.status_code})'
    except requests.RequestException as erro:
        return False, f'sem resposta ({type(erro).__name__})'


def linhas(cfg, alcanca=_alcanca):
    """[(ok, texto)] do diagnóstico."""
    def preenchido(nome, valor):
        return bool(valor), f'{nome}: {"preenchido" if valor else "VAZIO"}'

    saida = [(True, f'Login gov.br: {cfg.govbr_url}'),
             preenchido('GOVBR_CLIENT_ID', cfg.govbr_client_id),
             preenchido('GOVBR_CLIENT_SECRET', cfg.govbr_client_secret),
             preenchido('SEGREDO_SESSAO', cfg.segredo_sessao)]
    ok, texto = alcanca(cfg.govbr_url + '/.well-known/openid-configuration')
    saida.append((ok, f'{cfg.govbr_url}: {texto}'))

    saida.append((True, f'Assinatura gov.br: ambiente {cfg.assinatura_ambiente}'))
    if cfg.govbr_ativo and cfg.assinatura_ambiente in ('homologacao', 'producao'):
        login = 'homologacao' if 'staging' in cfg.govbr_url else 'producao'
        saida.append((login == cfg.assinatura_ambiente,
                      f'Login gov.br ({login}) e assinatura ({cfg.assinatura_ambiente}) no mesmo ambiente'
                      + ('' if login == cfg.assinatura_ambiente else
                         ': NÃO. O nível conferido no login é de uma conta do outro ambiente, e uma conta bronze '
                         'da assinatura chegaria à autorização. Para homologar, use GOVBR_AMBIENTE=homologacao '
                         '(credencial de teste do Login Único).')))
    if cfg.assinatura_ambiente == 'simulada':
        saida.append((cfg.login_simulado, 'Assinatura simulada (só com LOGIN_SIMULADO=1, em desenvolvimento)'))
        return saida
    saida += [preenchido('GOVBR_ASSINATURA_CLIENT_ID', cfg.assinatura_client_id),
              preenchido('GOVBR_ASSINATURA_CLIENT_SECRET', cfg.assinatura_client_secret),
              (True, 'GOVBR_ASSINATURA_REDIRECT_URI: ' + (cfg.assinatura_redirect_uri or
                                                          '(vazio: o endereço do pedido + /assinatura/govbr/callback)'))]
    for url in (cfg.assinatura_oauth_url + '/authorize', cfg.assinatura_api_url + '/certificadoPublico'):
        ok, texto = alcanca(url)
        saida.append((ok, f'{url}: {texto}'))
    saida.append((cfg.assinatura_api_ativa, 'Botão "Assinar com gov.br": ' +
                  ('ativo' if cfg.assinatura_api_ativa else 'desligado (falta cliente, segredo ou SEGREDO_SESSAO)')))
    return saida


def main(cfg=None, alcanca=_alcanca):
    resultado = linhas(cfg or config.carregar(), alcanca)
    for ok, texto in resultado:
        print(('  ok  ' if ok else ' FALHA ') + texto)
    return 0 if all(ok for ok, _ in resultado) else 1


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
