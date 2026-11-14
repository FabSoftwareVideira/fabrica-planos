"""Testes unitários do serviço de backup (app/servicos/backup.py), sem o app nem o PostgreSQL: o pg_dump e o
psql são trocados por falsos. Os testes de ponta a ponta (com o banco e as rotas) ficam em test_backup.py."""
import json
import os
import stat
import subprocess
import zipfile
from datetime import datetime

import pytest

from app.config import Config
from app.servicos import backup as modulo
from app.servicos.backup import FORMATO, Backup, BackupInvalido, BackupOcupado, _tamanho
from app.servicos.validador import Validador


@pytest.fixture
def pastas(tmp_path):
    planos, res = tmp_path / 'planos', tmp_path / 'res'
    planos.mkdir()
    res.mkdir()
    return tmp_path, planos, res


def _backup(pastas, validador=False, **opcoes):
    tmp_path, planos, res = pastas
    opcoes.setdefault('backups_dir', str(tmp_path / 'backups'))
    cfg = Config(planos_dir=str(planos), resultados_dir=str(res), ollama_url='', modelo='m', num_ctx=1,
                 hora_agendada=5, agendar=False, **opcoes)
    b = Backup(cfg, Validador(cfg, lambda t: t()) if validador else None)
    b.restaurados = []
    b._dump = lambda: b'-- dump de teste\n'
    b._restaurar_banco = lambda arquivo: b.restaurados.append(open(arquivo, 'rb').read())
    return b


def _zip(b, nome, arquivos):
    """Grava em backups/ um ZIP com estes {caminho: conteúdo} (ou ZipInfo: conteúdo)."""
    caminho = os.path.join(b.dir, nome)
    with zipfile.ZipFile(caminho, 'w') as z:
        for arco, conteudo in arquivos.items():
            z.writestr(arco, conteudo)
    return caminho


MANIFESTO = json.dumps({'formato': FORMATO})


# Criação ----------------------------------------------------------------------------------------------

def test_cria_zip_com_planos_resultados_banco_e_manifesto(pastas):
    _, planos, res = pastas
    (planos / 'a.pdf').write_bytes(b'%PDF-a')
    (res / 'donos.json').write_text('{}')
    (res / 'historico').mkdir()
    (res / 'historico' / 'meta.json').write_text('{}')
    (res / 'enviando.pdf.tmp').write_text('temporário')  # fica de fora
    (res / 'x.parcial').write_text('temporário')
    b = _backup(pastas)
    item = b.criar('manual')
    assert item['origem'] == 'manual' and item['rotulo'] == 'Manual' and item['valido']
    assert item['planos'] == 1 and item['resultados'] == 2
    with zipfile.ZipFile(os.path.join(b.dir, item['nome'])) as z:
        assert sorted(z.namelist()) == ['banco.sql', 'manifesto.json', 'planos/a.pdf', 'resultados/donos.json',
                                        'resultados/historico/meta.json']
        assert json.loads(z.read('manifesto.json'))['banco'] == {'bytes': len(b'-- dump de teste\n')}
    assert not b.criando and b.ultimo_erro == ''


def test_backups_dentro_de_resultados_nao_entram_no_proprio_zip(pastas):
    _, _, res = pastas
    b = _backup(pastas, backups_dir=str(res / 'backups'))
    primeiro = b.criar('manual')
    segundo = b.criar('manual')
    with zipfile.ZipFile(os.path.join(b.dir, segundo['nome'])) as z:
        assert not any('backups' in n for n in z.namelist())
    assert primeiro['nome'] != segundo['nome']


def test_nomes_no_mesmo_segundo_ganham_numero(pastas):
    b = _backup(pastas)
    agora = datetime(2026, 11, 14, 10, 0, 0)
    assert b._nome(agora, 'manual') == '20261114-100000-manual.zip'
    open(os.path.join(b.dir, '20261114-100000-manual.zip'), 'w').close()
    open(os.path.join(b.dir, '20261114-100000-manual-2.zip'), 'w').close()
    assert b._nome(agora, 'manual') == '20261114-100000-manual-3.zip'


def test_origem_invalida(pastas):
    with pytest.raises(ValueError):
        _backup(pastas).criar('qualquer')


def test_falha_no_dump_nao_deixa_zip_parcial(pastas):
    b = _backup(pastas)

    def falha():
        raise RuntimeError('pg_dump falhou: sem conexão')
    b._dump = falha
    with pytest.raises(RuntimeError):
        b.criar('manual')
    assert os.listdir(b.dir) == [] and not b.criando


def test_backups_dir_igual_a_pasta_de_dados_e_trocado(pastas, caplog):
    _, planos, res = pastas
    b = _backup(pastas, backups_dir=str(planos))
    assert b.dir == os.path.join(str(res), 'backups') and 'BACKUPS_DIR não pode ser' in caplog.text


def test_pasta_de_backups_indisponivel_nao_impede_o_app(pastas, monkeypatch, caplog):
    def falha(*a, **k):
        raise PermissionError('sem permissão')
    monkeypatch.setattr(modulo.os, 'makedirs', falha)
    _backup(pastas)
    assert 'Pasta de backups indisponível' in caplog.text


def test_ocupado_durante_outro_backup_ou_validacao(pastas):
    b = _backup(pastas, validador=True)
    b._em_andamento = True
    with pytest.raises(BackupOcupado):
        b.criar('manual')
    assert not b.iniciar('manual') and not b.excluir('qualquer.zip')
    b._em_andamento = False
    b.validador.andamento.iniciar(1)
    with pytest.raises(BackupOcupado, match='validação'):
        b.criar('manual')


def test_iniciar_em_thread_registra_o_erro(pastas, monkeypatch):
    b = _backup(pastas)

    class ThreadNaHora:
        def __init__(self, target, args, daemon):
            self.alvo, self.args = target, args

        def start(self):
            self.alvo(*self.args)
    monkeypatch.setattr(modulo.threading, 'Thread', ThreadNaHora)

    def falha():
        raise RuntimeError('pg_dump não encontrado')
    b._dump = falha
    assert b.iniciar('manual')
    assert b.ultimo_erro == 'pg_dump não encontrado' and not b.criando
    b._dump = lambda: b''
    assert b.iniciar('manual') and b.ultimo_erro == '' and len(b.listar()) == 1


# Retenção, listagem e exclusão -------------------------------------------------------------------------

def test_poda_mantem_so_os_ultimos_automaticos(pastas):
    b = _backup(pastas, backup_manter=2)
    for dia in (1, 2, 3):
        _zip(b, f'2026110{dia}-030000-automatico.zip', {'manifesto.json': MANIFESTO})
    _zip(b, '20261101-020000-manual.zip', {'manifesto.json': MANIFESTO})
    b._podar()
    assert [i['nome'] for i in b.listar()] == ['20261103-030000-automatico.zip', '20261102-030000-automatico.zip',
                                              '20261101-020000-manual.zip']


def test_listar_ignora_o_que_nao_e_backup_e_marca_os_invalidos(pastas):
    b = _backup(pastas)
    _zip(b, '20261101-030000-manual.zip', {'manifesto.json': MANIFESTO})
    _zip(b, '20261102-030000-manual.zip', {'manifesto.json': json.dumps({'formato': 999})})
    with open(os.path.join(b.dir, '20261103-030000-manual.zip'), 'wb') as arq:
        arq.write(b'nao e zip')
    _zip(b, '20261104-030000-manual.zip', {'manifesto.json': '[1, 2]'})
    _zip(b, 'outro-nome.zip', {'manifesto.json': MANIFESTO})
    os.mkdir(os.path.join(b.dir, '20261105-030000-manual.zip'))  # pasta com nome de backup
    _zip(b, '20261399-030000-manual.zip', {'manifesto.json': MANIFESTO})  # data impossível
    itens = {i['nome']: i for i in b.listar()}
    assert list(itens) == ['20261104-030000-manual.zip', '20261103-030000-manual.zip',
                           '20261102-030000-manual.zip', '20261101-030000-manual.zip']
    assert [i['valido'] for i in itens.values()] == [False, False, False, True]
    assert itens['20261101-030000-manual.zip']['quando'] == '01/11/2026 às 03:00'


def test_listar_sem_a_pasta(pastas):
    b = _backup(pastas)
    os.rmdir(b.dir)
    assert b.listar() == []


def test_caminho_e_exclusao_so_de_backups(pastas):
    b = _backup(pastas)
    _zip(b, '20261101-030000-manual.zip', {'manifesto.json': MANIFESTO})
    for nome in ('', '../res/donos.json', 'qualquer.zip', '20261101-030000-manual.zip/..'):
        assert b.caminho(nome) is None and not b.excluir(nome)
    assert b.excluir('20261101-030000-manual.zip') and b.listar() == []


@pytest.mark.parametrize('bytes_, texto', [(0, '0 B'), (1023, '1023 B'), (1536, '1.5 KB'),
                                           (5 * 1024 ** 2, '5.0 MB'), (3 * 1024 ** 5, '3072.0 TB')])
def test_tamanho_legivel(bytes_, texto):
    assert _tamanho(bytes_) == texto


# Restauração -------------------------------------------------------------------------------------------

def test_restaura_substituindo_os_dados_e_guarda_o_estado_anterior(pastas):
    _, planos, res = pastas
    b = _backup(pastas, validador=True)
    nome = '20261101-030000-manual.zip'
    _zip(b, nome, {'manifesto.json': MANIFESTO, 'banco.sql': b'-- restaurar\n',
                   'planos/novo.pdf': b'%PDF-novo', 'resultados/historico/meta.json': '{}'})
    (planos / 'velho.pdf').write_bytes(b'%PDF-velho')
    (res / 'velho').mkdir()
    resumo = b.restaurar(nome)
    assert resumo == {'planos': 1, 'resultados': 1, 'banco': True}
    assert os.listdir(planos) == ['novo.pdf'] and os.listdir(res) == ['historico']
    assert b.restaurados == [b'-- restaurar\n']
    anteriores = [i for i in b.listar() if i['origem'] == 'antes-restauracao']
    assert len(anteriores) == 1 and anteriores[0]['planos'] == 1  # tinha velho.pdf
    assert not [n for n in os.listdir(b.dir) if n.startswith('.restaurando-')]  # sem sobra da extração


def test_restauracao_preserva_backups_dentro_de_resultados(pastas):
    _, _, res = pastas
    b = _backup(pastas, backups_dir=str(res / 'backups'))
    nome = '20261101-030000-manual.zip'
    _zip(b, nome, {'manifesto.json': MANIFESTO, 'resultados/donos.json': '{}'})
    b.restaurar(nome)
    assert sorted(os.listdir(res)) == ['backups', 'donos.json']
    assert os.path.exists(os.path.join(b.dir, nome))


def _link(arco):
    info = zipfile.ZipInfo(arco)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


@pytest.mark.parametrize('arquivos, motivo', [
    ({'manifesto.json': MANIFESTO, '../fora.txt': 'x'}, 'caminhos inválidos'),
    ({'manifesto.json': MANIFESTO, '/etc/passwd': 'x'}, 'caminhos inválidos'),
    ({'manifesto.json': MANIFESTO, 'outra/coisa.txt': 'x'}, 'formato esperado'),
    ({'manifesto.json/dentro': 'x'}, 'formato esperado'),
    ({'planos/a.pdf': b'%PDF-'}, 'manifesto válido'),
    ({'manifesto.json': '{ruim'}, 'manifesto válido'),
    ({'manifesto.json': json.dumps({'formato': 0})}, 'versão incompatível'),
])
def test_restauracao_recusa_zip_perigoso_ou_incompativel(pastas, arquivos, motivo):
    b = _backup(pastas)
    _zip(b, '20261101-030000-manual.zip', arquivos)
    with pytest.raises(BackupInvalido, match=motivo):
        b.restaurar('20261101-030000-manual.zip')
    assert not b.criando and [i['origem'] for i in b.listar()] == ['manual']  # nada foi feito


def test_restauracao_recusa_link_simbolico(pastas):
    b = _backup(pastas)
    caminho = os.path.join(b.dir, '20261101-030000-manual.zip')
    with zipfile.ZipFile(caminho, 'w') as z:
        z.writestr('manifesto.json', MANIFESTO)
        z.writestr(_link('planos/a.pdf'), '/etc/passwd')
    with pytest.raises(BackupInvalido, match='links simbólicos'):
        b.restaurar('20261101-030000-manual.zip')


def test_restauracao_recusa_sobrescrever_a_pasta_de_backups(pastas):
    _, _, res = pastas
    b = _backup(pastas, backups_dir=str(res / 'backups'))
    _zip(b, '20261101-030000-manual.zip', {'manifesto.json': MANIFESTO, 'resultados/backups/x.zip': 'x'})
    with pytest.raises(BackupInvalido, match='pasta de backups'):
        b.restaurar('20261101-030000-manual.zip')


def test_restauracao_recusa_arquivo_que_nao_e_zip(pastas):
    b = _backup(pastas)
    with open(os.path.join(b.dir, '20261101-030000-manual.zip'), 'wb') as arq:
        arq.write(b'qualquer coisa')
    with pytest.raises(BackupInvalido, match='não é um backup válido'):
        b.restaurar('20261101-030000-manual.zip')


def test_restauracao_de_backup_inexistente_ou_ocupado(pastas):
    b = _backup(pastas, validador=True)
    with pytest.raises(BackupInvalido, match='não encontrado'):
        b.restaurar('20261101-030000-manual.zip')
    _zip(b, '20261101-030000-manual.zip', {'manifesto.json': MANIFESTO})
    b.validador.andamento.iniciar(1)
    with pytest.raises(BackupOcupado):
        b.restaurar('20261101-030000-manual.zip')
    b.validador.andamento.finalizar()
    b._em_andamento = True
    with pytest.raises(BackupOcupado):
        b.restaurar('20261101-030000-manual.zip')


# pg_dump / psql -----------------------------------------------------------------------------------------

def test_sem_banco_configurado(pastas):
    cfg = _backup(pastas).cfg
    with pytest.raises(BackupInvalido, match='banco de dados'):
        Backup(cfg)._env_banco()


class _BancoFalso:
    url = 'postgresql://planos:s3nh4@postgres:5433/planos?sslmode=disable'
    esquema = 'teste_x'


def test_senha_do_banco_vai_por_variavel_de_ambiente(pastas):
    env = Backup(_backup(pastas).cfg, banco=_BancoFalso())._env_banco()
    assert (env['PGHOST'], env['PGPORT'], env['PGUSER'], env['PGPASSWORD'], env['PGDATABASE'], env['PGSSLMODE']) == (
        'postgres', '5433', 'planos', 's3nh4', 'planos', 'disable')


def test_dump_das_tabelas_do_esquema(pastas, monkeypatch):
    chamadas = []

    def rodar(comando, **opcoes):
        chamadas.append((comando, opcoes))
        return subprocess.CompletedProcess(comando, 0, stdout=b'SQL', stderr=b'')
    monkeypatch.setattr(modulo.subprocess, 'run', rodar)
    b = Backup(_backup(pastas).cfg, banco=_BancoFalso())
    assert b._dump() == b'SQL'
    comando, opcoes = chamadas[0]
    assert comando[0] == 'pg_dump' and '--table' in comando and 'teste_x.usuarios' in comando
    assert 'teste_x.vinculos_govbr' in comando and 's3nh4' not in ' '.join(comando)
    assert opcoes['env']['PGPASSWORD'] == 's3nh4' and opcoes['check']
    b._restaurar_banco('/tmp/banco.sql')
    assert chamadas[1][0][:2] == ['psql', '--quiet'] and chamadas[1][0][-1] == '/tmp/banco.sql'


def test_erros_do_pg_dump_viram_mensagens(pastas, monkeypatch):
    b = Backup(_backup(pastas).cfg, banco=_BancoFalso())

    def sem_programa(comando, **opcoes):
        raise FileNotFoundError(comando[0])
    monkeypatch.setattr(modulo.subprocess, 'run', sem_programa)
    with pytest.raises(RuntimeError, match='postgresql-client'):
        b._dump()

    def falha(comando, **opcoes):
        raise subprocess.CalledProcessError(1, comando, stderr='conexão recusada'.encode())
    monkeypatch.setattr(modulo.subprocess, 'run', falha)
    with pytest.raises(RuntimeError, match='pg_dump falhou: conexão recusada'):
        b._dump()


# Agendamento --------------------------------------------------------------------------------------------

def test_backup_automatico_tenta_de_novo_quando_ocupado(pastas, monkeypatch):
    b = _backup(pastas)
    esperas, tentativas = [], []
    criar = b.criar

    def ocupado_duas_vezes(origem):
        tentativas.append(origem)
        if len(tentativas) <= 2:
            raise BackupOcupado('validação')
        return criar(origem)
    b.criar = ocupado_duas_vezes
    monkeypatch.setattr(modulo.time, 'sleep', esperas.append)
    b._tentar_automatico()
    assert esperas == [1800, 1800] and b._automatico_hoje()


def test_backup_automatico_desiste_no_fim_do_dia_ou_em_erro(pastas, monkeypatch, caplog):
    b = _backup(pastas)
    monkeypatch.setattr(modulo.time, 'sleep', lambda s: None)

    def sempre_ocupado(origem):
        raise BackupOcupado('x')
    b.criar = sempre_ocupado
    b._tentar_automatico()
    assert 'não pôde ser feito hoje' in caplog.text

    def quebra(origem):
        raise OSError('disco cheio')
    b.criar = quebra
    b._tentar_automatico()
    assert 'Falha no backup automático' in caplog.text


class _Fim(Exception):
    pass


def test_agendador_faz_o_do_dia_ao_subir_depois_da_hora(pastas, monkeypatch):
    b = _backup(pastas, backup_hora=3)
    feitos, esperas = [], []

    class Relogio(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 14, 9, 0)
    monkeypatch.setattr(modulo, 'datetime', Relogio)
    b._tentar_automatico = lambda: feitos.append('automatico')

    def dormir(segundos):
        esperas.append(segundos)
        raise _Fim
    monkeypatch.setattr(modulo.time, 'sleep', dormir)
    with pytest.raises(_Fim):
        b._agendador()
    assert feitos == ['automatico'] and esperas == [18 * 3600]  # até as 3h de amanhã
