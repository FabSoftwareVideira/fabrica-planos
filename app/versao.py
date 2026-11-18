"""Versão do código em execução: a tag (ex.: v1.0.1) quando o commit tem uma, senão o commit curto.

Lida direto dos arquivos do .git (HEAD, refs e packed-refs), sem o programa git, que a imagem não tem:
- produção: o Dockerfile roda `python -m app.versao <pasta .git> <arquivo>` no build e grava app/versao.json
  (o .dockerignore deixa entrar no build só esses arquivos do .git);
- desenvolvimento: sem o arquivo, lê o .git do projeto montado em /app.
"""
import json
import os
import sys
from datetime import datetime, timezone
from functools import lru_cache

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO = os.path.join(RAIZ, 'app', 'versao.json')


def _ler(caminho):
    try:
        with open(caminho, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def _refs(pasta):
    """{nome da ref: commit} das refs soltas e do packed-refs. Numa tag anotada, a linha "^<sha>" do
    packed-refs é o commit para onde ela aponta e substitui o sha do objeto da tag."""
    refs, ultima = {}, None
    for linha in _ler(os.path.join(pasta, 'packed-refs')).splitlines():
        if linha.startswith('^') and ultima:
            refs[ultima] = linha[1:].strip()
        elif linha and not linha.startswith('#') and ' ' in linha:
            sha, ultima = linha.split(' ', 1)
            refs[ultima] = sha
    for base, _, arquivos in os.walk(os.path.join(pasta, 'refs')):
        for nome in arquivos:
            caminho = os.path.join(base, nome)
            ref = os.path.relpath(caminho, pasta).replace(os.sep, '/')
            sha = _ler(caminho)
            # Uma tag anotada solta aponta para o objeto da tag; vale a do packed-refs, se já peelada lá
            if sha and not (ref.startswith('refs/tags/') and ref in refs):
                refs[ref] = sha
    return refs


def ler_git(pasta):
    """{'commit', 'tag'} do HEAD da pasta .git; None se não houver repositório legível."""
    head = _ler(os.path.join(pasta, 'HEAD'))
    if not head:
        return None
    refs = _refs(pasta)
    commit = refs.get(head[5:].strip()) if head.startswith('ref:') else head
    if not commit:
        return None
    tags = sorted(r[10:] for r, sha in refs.items() if r.startswith('refs/tags/') and sha == commit)
    return {'commit': commit, 'tag': tags[-1] if tags else None}


def gravar(pasta_git, destino):
    dados = ler_git(pasta_git) or {'commit': None, 'tag': None}
    dados['build'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(destino, 'w', encoding='utf-8') as f:
        json.dump(dados, f)
    return dados


@lru_cache(maxsize=1)
def atual():
    """{'commit', 'tag', 'build', 'rotulo'}; o rótulo é o que a tela mostra."""
    try:
        with open(ARQUIVO, encoding='utf-8') as f:
            dados = json.load(f)
    except (OSError, ValueError):
        dados = ler_git(os.path.join(RAIZ, '.git')) or {}
    commit = dados.get('commit') or None
    rotulo = dados.get('tag') or (commit[:7] if commit else 'desconhecida')
    return {'commit': commit, 'tag': dados.get('tag'), 'build': dados.get('build'), 'rotulo': rotulo}


if __name__ == '__main__':  # python -m app.versao <pasta .git> <arquivo de saída>
    print(json.dumps(gravar(sys.argv[1], sys.argv[2])))
