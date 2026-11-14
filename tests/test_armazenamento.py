"""Testes da camada de armazenamento (app/armazenamento e app/banco.py).

Os arquivos JSON (liberações, ocultos) são testados como unidade, em pasta temporária. Usuários,
vínculos com o gov.br e revisões são testes de integração com o PostgreSQL de TEST_DATABASE_URL (cada
teste num esquema próprio; ver conftest.py)."""
import json
import os

import psycopg
import pytest

from app import banco as modulo_banco
from app.armazenamento import liberacoes, ocultos
from app.armazenamento.revisoes import Revisoes
from app.armazenamento.usuarios import Usuarios
from app.banco import Banco

com_banco = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='precisa de TEST_DATABASE_URL')


# Arquivos JSON ---------------------------------------------------------------------------------------

@pytest.mark.parametrize('modulo, arquivo', [(liberacoes, 'liberacoes.json'), (ocultos, 'ocultos.json')])
def test_json_ausente_ou_corrompido_vale_vazio(tmp_path, modulo, arquivo):
    assert modulo.ler(str(tmp_path)) == {}
    (tmp_path / arquivo).write_text('{ isto não é json', encoding='utf-8')
    assert modulo.ler(str(tmp_path)) == {}


def test_remover_sem_nada_a_remover_nao_regrava(tmp_path, monkeypatch):
    liberacoes.liberar(str(tmp_path), 'a.pdf', 'x@ifc.edu.br')
    monkeypatch.setattr(liberacoes, '_gravar', lambda *a: pytest.fail('não devia regravar'))
    liberacoes.remover(str(tmp_path), ['b.pdf'])


def test_liberacoes(tmp_path):
    pasta = str(tmp_path)
    assert not liberacoes.liberado(pasta, 'a.pdf')
    liberacoes.liberar(pasta, 'a.pdf', 'coord@ifc.edu.br')
    liberacoes.liberar(pasta, 'b.pdf', 'coord@ifc.edu.br')
    assert liberacoes.liberado(pasta, 'a.pdf') and liberacoes.ler(pasta)['a.pdf']['por'] == 'coord@ifc.edu.br'
    liberacoes.cancelar(pasta, 'a.pdf')
    assert not liberacoes.liberado(pasta, 'a.pdf') and liberacoes.liberado(pasta, 'b.pdf')
    liberacoes.remover(pasta, ['b.pdf'])
    assert liberacoes.ler(pasta) == {}


def test_ocultos(tmp_path):
    pasta = str(tmp_path)
    ocultos.ocultar(pasta, 'a.pdf', 'admin@ifc.edu.br')
    ocultos.ocultar(pasta, 'b.pdf', 'admin@ifc.edu.br')
    assert set(ocultos.ler(pasta)) == {'a.pdf', 'b.pdf'}
    ocultos.mostrar(pasta, ['a.pdf'])
    dados = json.loads((tmp_path / 'ocultos.json').read_text(encoding='utf-8'))
    assert list(dados) == ['b.pdf'] and dados['b.pdf']['por'] == 'admin@ifc.edu.br'


# Banco -------------------------------------------------------------------------------------------------

def test_banco_exige_url():
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        Banco('')


def test_banco_recusa_esquema_com_nome_invalido():
    with pytest.raises(ValueError, match='esquema'):
        Banco('postgresql://x@y/z', esquema='public; DROP TABLE usuarios')


def test_banco_desiste_depois_da_espera():
    tentativas = []

    def conectar(*args, **kwargs):
        tentativas.append(1)
        raise psycopg.OperationalError('recusada')
    # Só neste bloco: a limpeza do esquema (conftest.py) também usa psycopg.connect
    with pytest.MonkeyPatch.context() as m:
        m.setattr(modulo_banco.psycopg, 'connect', conectar)
        m.setattr(modulo_banco.time, 'sleep', lambda s: None)
        with pytest.raises(psycopg.OperationalError):
            Banco('postgresql://x@y/z', esquema='teste', espera=0)
    assert len(tentativas) == 1


@pytest.fixture
def banco():
    return Banco(os.environ['TEST_DATABASE_URL'])


@com_banco
def test_banco_cria_o_esquema_e_isola_as_tabelas(banco):
    with banco.conexao() as con:
        assert con.execute('SELECT current_schema() AS s').fetchone()['s'] == os.environ['DB_ESQUEMA']


# Usuários ----------------------------------------------------------------------------------------------

@com_banco
def test_registrar_acesso_cadastra_e_atualiza_o_nome(banco):
    u = Usuarios(banco)
    novo = u.registrar_acesso('fulano@ifc.edu.br', 'Fulano')
    assert novo['ativo'] == 1 and novo['primeiro_acesso'] == novo['ultimo_acesso']
    assert u.registrar_acesso('fulano@ifc.edu.br')['nome'] == 'Fulano'  # sem nome, mantém o guardado
    assert u.registrar_acesso('fulano@ifc.edu.br', 'Fulano de Tal')['nome'] == 'Fulano de Tal'
    assert u.obter('fulano@ifc.edu.br')['nome'] == 'Fulano de Tal' and u.obter('ninguem@ifc.edu.br') is None


@com_banco
def test_ativar_desativar_e_contar(banco):
    u = Usuarios(banco)
    u.registrar_acesso('a@ifc.edu.br')
    u.registrar_acesso('b@ifc.edu.br')
    assert u.definir_ativo('b@ifc.edu.br', False) and not u.definir_ativo('x@ifc.edu.br', False)
    assert u.contar() == {'total': 2, 'ativos': 1, 'inativos': 1}


@com_banco
def test_listar_filtra_ordena_e_pagina(banco):
    u = Usuarios(banco)
    u.registrar_acesso('ana@ifc.edu.br', 'Ana Souza')
    u.registrar_acesso('bia@ifc.edu.br', 'Bia Lima')
    u.registrar_acesso('sem.nome@ifc.edu.br')
    u.definir_ativo('bia@ifc.edu.br', False)
    u.adicionar_papel('ana@ifc.edu.br', 'CC', 'nde')
    admins = ('bia@ifc.edu.br',)

    def emails(**filtros):
        linhas, total = u.listar(admins=admins, **filtros)
        return [l['email'] for l in linhas], total
    assert emails(ordem='nome') == (['ana@ifc.edu.br', 'bia@ifc.edu.br', 'sem.nome@ifc.edu.br'], 3)
    assert emails(ordem='email', busca='SOUZA') == (['ana@ifc.edu.br'], 1)
    assert emails(busca='100%_')[1] == 0  # curingas do LIKE não valem como curinga
    assert emails(ordem='email', situacao='inativos') == (['bia@ifc.edu.br'], 1)
    assert emails(ordem='email', situacao='ativos')[1] == 2
    assert emails(papel='admin') == (['bia@ifc.edu.br'], 1)
    assert emails(papel='consulta', ordem='email')[0] == ['ana@ifc.edu.br', 'sem.nome@ifc.edu.br']
    assert emails(papel='revisor') == (['ana@ifc.edu.br'], 1)
    assert emails(ordem='email', por_pagina=2, pagina=2) == (['sem.nome@ifc.edu.br'], 3)
    assert emails(ordem='qualquer')[1] == 3  # ordem desconhecida vale a padrão
    assert u.listar(papel='admin')[1] == 0  # sem administradores na lista


@com_banco
def test_papeis_em_cursos(banco):
    u = Usuarios(banco)
    assert not u.adicionar_papel('ninguem@ifc.edu.br', 'CC', 'nde')  # só quem já entrou
    u.registrar_acesso('ana@ifc.edu.br')
    u.registrar_acesso('bia@ifc.edu.br')
    assert u.adicionar_papel('ana@ifc.edu.br', 'SI', 'coordenador')
    assert u.adicionar_papel('ana@ifc.edu.br', 'CC', 'nde')
    assert u.adicionar_papel('ana@ifc.edu.br', 'CC', 'nde')  # repetido: não duplica
    u.adicionar_papel('bia@ifc.edu.br', 'CC', 'ndb')
    assert u.papeis('ana@ifc.edu.br') == [('CC', 'nde'), ('SI', 'coordenador')]
    assert u.papeis_de(['ana@ifc.edu.br', 'bia@ifc.edu.br', 'x@ifc.edu.br']) == {
        'ana@ifc.edu.br': [('CC', 'nde'), ('SI', 'coordenador')], 'bia@ifc.edu.br': [('CC', 'ndb')], 'x@ifc.edu.br': []}
    assert u.papeis_de([]) == {}
    assert u.cursos_com_papel() == ['CC', 'SI']
    assert u.remover_papel('ana@ifc.edu.br', 'SI', 'coordenador')
    assert not u.remover_papel('ana@ifc.edu.br', 'SI', 'coordenador')
    assert u.cursos_com_papel() == ['CC']


@com_banco
def test_vinculos_govbr(banco):
    u = Usuarios(banco)
    assert u.email_do_govbr('chave-1') is None and not u.tem_govbr('ana@ifc.edu.br')
    u.vincular_govbr('chave-1', 'ana@ifc.edu.br')
    assert u.email_do_govbr('chave-1') == 'ana@ifc.edu.br' and u.tem_govbr('ana@ifc.edu.br')
    # Outra conta gov.br para o mesmo usuário substitui a anterior
    u.vincular_govbr('chave-2', 'ana@ifc.edu.br')
    assert u.email_do_govbr('chave-1') is None and u.email_do_govbr('chave-2') == 'ana@ifc.edu.br'
    # A mesma conta gov.br vinculada a outro usuário sai do primeiro
    u.vincular_govbr('chave-2', 'bia@ifc.edu.br')
    assert u.email_do_govbr('chave-2') == 'bia@ifc.edu.br' and not u.tem_govbr('ana@ifc.edu.br')
    assert u.desvincular_govbr('bia@ifc.edu.br') and not u.desvincular_govbr('bia@ifc.edu.br')
    assert u.email_do_govbr('chave-2') is None


# Revisões ----------------------------------------------------------------------------------------------

@com_banco
def test_revisoes_salvar_substituir_e_remover(banco):
    r = Revisoes(banco)
    assert r.obter('a.pdf') is None and r.todas() == {}
    r.salvar('a.pdf', '10-1', 'AJUSTES', 'OK', 'falta bibliografia', 'CC', 'nde@ifc.edu.br', 'Nina', 'nde')
    r.salvar('b.pdf', '20-2', 'OK', 'OK', '', 'CC', 'nde@ifc.edu.br', 'Nina', 'nde')
    nova = r.salvar('a.pdf', '11-1', 'OK', 'OK', '', 'CC', 'coord@ifc.edu.br', 'Cora', 'coordenador')
    lida = r.obter('a.pdf')
    assert lida == nova and lida['revisor_email'] == 'coord@ifc.edu.br' and lida['assinatura'] == '11-1'
    assert set(r.todas()) == {'a.pdf', 'b.pdf'}
    assert r.remover('a.pdf') and not r.remover('a.pdf')
    assert list(r.todas()) == ['b.pdf']
