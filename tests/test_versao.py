import json

from app import versao

SHA = 'a' * 40
OUTRO = 'b' * 40
OBJ_TAG = 'c' * 40


def _git(tmp_path, head='ref: refs/heads/master', soltas=None, packed=''):
    pasta = tmp_path / '.git'
    pasta.mkdir()
    (pasta / 'HEAD').write_text(head + '\n')
    for ref, sha in (soltas or {}).items():
        (pasta / ref).parent.mkdir(parents=True, exist_ok=True)
        (pasta / ref).write_text(sha + '\n')
    if packed:
        (pasta / 'packed-refs').write_text(packed)
    return str(pasta)


def test_commit_do_branch_sem_tag(tmp_path):
    assert versao.ler_git(_git(tmp_path, soltas={'refs/heads/master': SHA})) == {'commit': SHA, 'tag': None}


def test_tag_anotada_no_packed_refs_aponta_para_o_commit(tmp_path):
    packed = (f'# pack-refs with: peeled fully-peeled sorted\n{SHA} refs/heads/master\n'
              f'{OBJ_TAG} refs/tags/v1.0.1\n^{SHA}\n{OUTRO} refs/tags/v1.0.0\n')
    assert versao.ler_git(_git(tmp_path, packed=packed)) == {'commit': SHA, 'tag': 'v1.0.1'}


def test_head_destacado_com_tag_leve(tmp_path):
    pasta = _git(tmp_path, head=SHA, soltas={'refs/tags/v2.0.0': SHA})
    assert versao.ler_git(pasta) == {'commit': SHA, 'tag': 'v2.0.0'}


def test_sem_repositorio(tmp_path):
    assert versao.ler_git(str(tmp_path / 'nada')) is None
    dados = versao.gravar(str(tmp_path / 'nada'), str(tmp_path / 'v.json'))
    assert dados['commit'] is None and dados['build']


def test_arquivo_do_build_define_o_rotulo(tmp_path, monkeypatch):
    arquivo = tmp_path / 'versao.json'
    versao.gravar(_git(tmp_path, soltas={'refs/heads/master': SHA}), str(arquivo))
    monkeypatch.setattr(versao, 'ARQUIVO', str(arquivo))
    versao.atual.cache_clear()
    try:
        v = versao.atual()
        assert v['rotulo'] == 'aaaaaaa' and v['commit'] == SHA and v['build']
        arquivo.write_text(json.dumps({'commit': SHA, 'tag': 'v1.0.1', 'build': 'x'}))
        versao.atual.cache_clear()
        assert versao.atual()['rotulo'] == 'v1.0.1'
    finally:
        versao.atual.cache_clear()


def test_health_e_rodape_mostram_a_versao(fabrica):
    c, _ = fabrica()
    v = versao.atual()
    dados = c.get('/health').get_json()
    assert dados['status'] == 'ok' and dados['versao'] == v['rotulo']
    assert f'Versão <span' in c.get('/privacidade').get_data(as_text=True)
