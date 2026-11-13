import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from app.config import Config
from app.fabrica import criar_app
from app.servicos.backup import BackupInvalido, BackupOcupado
from conftest import PDF_COM_TEXTO

PDF = PDF_COM_TEXTO
ADMIN = {'X-Usuario-Email': 'admin@ifc.edu.br'}
SERVIDOR = {'X-Usuario-Email': 'fulano@ifc.edu.br'}


def _criar_app(tmp_path, **opcoes):
    planos = tmp_path / 'planos'
    planos.mkdir(exist_ok=True)
    opcoes.setdefault('backups_dir', str(tmp_path / 'backups'))
    cfg = Config(
        planos_dir=str(planos), resultados_dir=str(tmp_path / 'res'), ollama_url='http://ollama:11434',
        modelo='m', num_ctx=1, hora_agendada=5, agendar=False, pdf_max_mb=1, **opcoes,
    )
    return criar_app(cfg, executar=lambda tarefa: tarefa()).test_client(), planos


def _servicos(c):
    return c.application.extensions['servicos']


def _dados(c, planos):
    """Grava um exemplo de cada tipo de dado que o backup precisa guardar."""
    s = _servicos(c)
    res = Path(s.cfg.resultados_dir)
    (planos / 'a.pdf').write_bytes(PDF)
    (planos / 'Plano Á.pdf').write_bytes(PDF)
    (res / 'donos.json').write_text('{"a.pdf": {"email": "fulano@ifc.edu.br"}}', encoding='utf-8')
    (res / 'ocultos.json').write_text('{}', encoding='utf-8')
    (res / 'liberacoes.json').write_text('{}', encoding='utf-8')
    (res / 'assinaturas.json').write_text('{"a.pdf": {"email": "fulano@ifc.edu.br"}}', encoding='utf-8')
    (res / 'validacao_planos.csv').write_text('Arquivo;Status Geral\na.pdf;OK\n', encoding='utf-8')
    (res / 'historico' / '20260101-000000' / 'detalhes').mkdir(parents=True)
    (res / 'historico' / '20260101-000000' / 'meta.json').write_text('{"id": "20260101-000000"}', encoding='utf-8')
    (res / 'historico' / '20260101-000000' / 'detalhes' / 'a.pdf.json').write_text('{}', encoding='utf-8')
    (res / 'assinados').mkdir()
    (res / 'assinados' / 'a.pdf').write_bytes(PDF)
    s.usuarios.registrar_acesso('fulano@ifc.edu.br', 'Fulano de Tal')
    s.revisao.revisoes.salvar('a.pdf', 'assinatura', 'aprovado', 'OK', 'ok', 'CC',
                              'coord@ifc.edu.br', 'Coord', 'coordenador')
    return s, res


def test_backup_guarda_e_restaura_todos_os_dados(tmp_path):
    c, planos = _criar_app(tmp_path)
    s, res = _dados(c, planos)
    item = s.backup.criar('manual')
    nome = item['nome']
    caminho = Path(s.backup.dir) / nome

    assert item['origem'] == 'manual' and item['planos'] == 2 and item['valido']
    with zipfile.ZipFile(caminho) as z:
        nomes = set(z.namelist())
        assert {'manifesto.json', 'planos/a.pdf', 'planos/Plano Á.pdf', 'resultados/donos.json',
                'resultados/ocultos.json', 'resultados/liberacoes.json', 'resultados/assinaturas.json',
                'resultados/validacao_planos.csv', 'resultados/historico/20260101-000000/meta.json',
                'resultados/validacao_planos.csv', 'resultados/historico/20260101-000000/meta.json',
                'resultados/historico/20260101-000000/detalhes/a.pdf.json', 'resultados/assinados/a.pdf',
                'banco.sql'} <= nomes
        assert b'usuarios' in z.read('banco.sql') and b'fulano@ifc.edu.br' in z.read('banco.sql')
        manifesto = json.loads(z.read('manifesto.json'))
        assert manifesto['formato'] == 1 and manifesto['planos']['arquivos'] == 2

    # Muda tudo e restaura: os dados voltam ao estado do backup.
    (planos / 'a.pdf').write_bytes(b'outro')
    (planos / 'Plano Á.pdf').unlink()
    (res / 'donos.json').write_text('{}', encoding='utf-8')
    (res / 'assinados' / 'a.pdf').unlink()
    (res / 'historico' / '20260101-000000' / 'meta.json').unlink()
    s.usuarios.definir_ativo('fulano@ifc.edu.br', False)
    s.revisao.revisoes.remover('a.pdf')

    resumo = s.backup.restaurar(nome)
    assert resumo == {'planos': 2, 'resultados': 7, 'banco': True}
    assert (planos / 'a.pdf').read_bytes() == PDF
    assert (planos / 'Plano Á.pdf').read_bytes() == PDF
    assert json.loads((res / 'donos.json').read_text(encoding='utf-8'))['a.pdf']['email'] == 'fulano@ifc.edu.br'
    assert (res / 'assinados' / 'a.pdf').read_bytes() == PDF
    assert (res / 'historico' / '20260101-000000' / 'meta.json').exists()
    assert s.usuarios.obter('fulano@ifc.edu.br')['ativo'] == 1
    assert s.revisao.revisoes.obter('a.pdf')['status'] == 'aprovado'
    assert c.get('/dashboard').status_code == 200

    # A restauração deixa um backup do estado anterior, para desfazer.
    origens = [b['origem'] for b in s.backup.listar()]
    assert origens.count('antes-restauracao') == 1 and 'manual' in origens


def test_backup_em_resultados_nao_se_inclui_e_sobrevive_a_restauracao(tmp_path):
    c, planos = _criar_app(tmp_path, backups_dir='')
    s, res = _dados(c, planos)
    assert Path(s.backup.dir) == res / 'backups'
    item = s.backup.criar('manual')
    with zipfile.ZipFile(Path(s.backup.dir) / item['nome']) as z:
        assert not any(n.startswith('resultados/backups') for n in z.namelist())

    s.backup.restaurar(item['nome'])
    # A pasta de backups fica dentro de resultados: a restauração não pode apagá-la.
    assert (res / 'backups' / item['nome']).exists()
    assert any(b['origem'] == 'antes-restauracao' for b in s.backup.listar())
    assert (planos / 'a.pdf').read_bytes() == PDF


def test_restauracao_recusa_backup_invalido_ou_caminho_fora(tmp_path):
    c, planos = _criar_app(tmp_path)
    s, _ = _dados(c, planos)
    pasta = Path(s.backup.dir)

    incompativel = pasta / '20260101-000000-manual.zip'
    with zipfile.ZipFile(incompativel, 'w') as z:
        z.writestr('manifesto.json', json.dumps({'formato': 99}))
    with pytest.raises(BackupInvalido):
        s.backup.restaurar(incompativel.name)

    fora = pasta / '20260101-000001-manual.zip'
    with zipfile.ZipFile(fora, 'w') as z:
        z.writestr('manifesto.json', json.dumps({'formato': 1}))
        z.writestr('../fora.txt', 'x')
    with pytest.raises(BackupInvalido):
        s.backup.restaurar(fora.name)
    assert not (tmp_path / 'fora.txt').exists()

    with pytest.raises(BackupInvalido):
        s.backup.restaurar('../../etc/passwd')


def test_backup_e_restauracao_recusam_com_validacao_em_andamento(tmp_path):
    c, planos = _criar_app(tmp_path)
    s, _ = _dados(c, planos)
    nome = s.backup.criar('manual')['nome']
    s.validador.andamento.iniciar(1)
    try:
        with pytest.raises(BackupOcupado):
            s.backup.criar('manual')
        with pytest.raises(BackupOcupado):
            s.backup.restaurar(nome)
    finally:
        s.validador.andamento.finalizar()


def test_backup_automatico_respeita_a_retencao(tmp_path):
    c, planos = _criar_app(tmp_path, backup_manter=2)
    s, _ = _dados(c, planos)
    for _ in range(3):
        s.backup.criar('automatico')
    automaticos = [b for b in s.backup.listar() if b['origem'] == 'automatico']
    assert len(automaticos) == 2
    s.backup.criar('manual')
    assert len([b for b in s.backup.listar() if b['origem'] == 'manual']) == 1


@pytest.fixture
def admin(tmp_path):
    c, _ = _criar_app(tmp_path, exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}))
    return c


def _esperar_backup(s):
    for _ in range(500):
        if not s.backup.criando:
            return
        time.sleep(0.01)
    raise AssertionError('o backup não terminou')


def test_tela_de_backup_e_so_da_administracao(admin):
    assert admin.get('/administracao/backup').status_code == 401
    r = admin.get('/administracao/backup', headers=SERVIDOR)
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')
    assert admin.post('/administracao/backup', headers=SERVIDOR).status_code == 302

    html = admin.get('/administracao/backup', headers=ADMIN).get_data(as_text=True)
    assert 'Backup dos dados' in html and 'Fazer backup agora' in html
    assert 'Nenhum backup ainda' in html
    assert 'Usuários' in html and 'href="/administracao/backup"' in html


def test_rotas_criam_baixam_restauram_e_excluem_backup(admin):
    s = _servicos(admin)
    r = admin.post('/administracao/backup', headers=ADMIN)
    assert r.status_code == 303 and 'aviso=iniciado' in r.headers['Location']
    _esperar_backup(s)
    itens = s.backup.listar()
    assert len(itens) == 1
    nome = itens[0]['nome']

    r = admin.get(f'/administracao/backup/{nome}', headers=ADMIN)
    assert r.status_code == 200
    assert 'attachment' in r.headers['Content-Disposition'] and r.data.startswith(b'PK')

    r = admin.post(f'/administracao/backup/{nome}/restaurar', headers=ADMIN)
    assert r.status_code == 303 and 'aviso=restaurado' in r.headers['Location']
    assert len(s.backup.listar()) == 2  # o original e o de antes de restaurar

    r = admin.post(f'/administracao/backup/{nome}/excluir', headers=ADMIN)
    assert r.status_code == 303 and 'aviso=excluido' in r.headers['Location']
    assert s.backup.caminho(nome) is None
    assert admin.get(f'/administracao/backup/{nome}', headers=ADMIN).status_code == 404
