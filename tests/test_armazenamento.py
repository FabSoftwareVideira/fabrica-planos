"""Testes da camada de armazenamento (app/armazenamento e app/banco.py).

Os arquivos JSON (ocultos) são testados como unidade, em pasta temporária. Usuários, vínculos com o
gov.br, revisões e versões dos planos são testes de integração com o PostgreSQL de TEST_DATABASE_URL (cada
teste num esquema próprio; ver conftest.py)."""
import json
import os

import psycopg
import pytest

from app import banco as modulo_banco
from app.armazenamento import ocultos
from app.armazenamento.revisoes import Revisoes
from app.armazenamento.usuarios import Usuarios
from app.armazenamento.versoes import Versoes
from app.banco import Banco

com_banco = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='precisa de TEST_DATABASE_URL')


# Arquivos JSON ---------------------------------------------------------------------------------------

@pytest.mark.parametrize('modulo, arquivo', [(ocultos, 'ocultos.json')])
def test_json_ausente_ou_corrompido_vale_vazio(tmp_path, modulo, arquivo):
    assert modulo.ler(str(tmp_path)) == {}
    (tmp_path / arquivo).write_text('{ isto não é json', encoding='utf-8')
    assert modulo.ler(str(tmp_path)) == {}


def test_remover_sem_nada_a_remover_nao_regrava(tmp_path, monkeypatch):
    ocultos.ocultar(str(tmp_path), 'a.pdf', 'x@ifc.edu.br')
    monkeypatch.setattr(ocultos, '_gravar', lambda *a: pytest.fail('não devia regravar'))
    ocultos.mostrar(str(tmp_path), ['b.pdf'])


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


# Versões dos planos ------------------------------------------------------------------------------------

@com_banco
def test_versoes_arquivadas_com_pdf_e_assinado(banco, tmp_path):
    v = Versoes(banco, str(tmp_path / 'res'))
    pdf, assinado = tmp_path / 'plano.pdf', tmp_path / 'assinado.pdf'
    pdf.write_bytes(b'%PDF-v1')
    assinado.write_bytes(b'%PDF-v1-assinado')
    assert v.listar('a.pdf') == [] and v.de_varios([]) == {}
    assert v.arquivar('a.pdf', str(pdf), str(assinado), enviado_em='2026-08-01T10:00:00', enviado_por='fulano@ifc.edu.br',
                      revisao_status='OK', revisor='Nina', signatario='FULANO DE TAL', ignorado='x') == 1
    pdf.write_bytes(b'%PDF-v2')
    assert v.arquivar('a.pdf', str(pdf), None, status_ia='PENDENTE') == 2
    assert v.arquivar('outro.pdf', str(pdf)) == 1
    [v2, v1] = v.listar('a.pdf')
    assert (v2['numero'], v2['status_ia'], v2['tem_assinado'], v2['bytes']) == (2, 'PENDENTE', False, 7)
    assert (v1['enviado_por'], v1['revisao_status'], v1['signatario'], v1['tem_assinado']) == (
        'fulano@ifc.edu.br', 'OK', 'FULANO DE TAL', True)
    assert open(v.caminho('a.pdf', 1), 'rb').read() == b'%PDF-v1'
    assert open(v.caminho('a.pdf', 1, assinado=True), 'rb').read() == b'%PDF-v1-assinado'
    assert open(v.caminho('a.pdf', 2), 'rb').read() == b'%PDF-v2'
    assert [x['numero'] for x in v.de_varios(['a.pdf', 'b.pdf'])['a.pdf']] == [2, 1]
    assert v.de_varios(['b.pdf']) == {'b.pdf': []}
    assert v.obter('a.pdf', 1)['signatario'] == 'FULANO DE TAL' and v.obter('a.pdf', 9) is None
    assert v.caminho('../x/a b.pdf', 1).endswith('.._x_a_b.pdf' + os.sep + 'v1.pdf')  # sem sair da pasta


@com_banco
def test_versao_excluida_perde_os_pdfs_e_o_numero_nao_volta(banco, tmp_path):
    v = Versoes(banco, str(tmp_path / 'res'))
    pdf = tmp_path / 'plano.pdf'
    pdf.write_bytes(b'%PDF-x')
    v.arquivar('a.pdf', str(pdf), str(pdf))
    v.arquivar('a.pdf', str(pdf))
    assert v.remover('a.pdf', 2) and not v.remover('a.pdf', 2) and v.remover('a.pdf', 1)
    assert v.listar('a.pdf') == [] and v.obter('a.pdf', 1) is None and v.de_varios(['a.pdf']) == {'a.pdf': []}
    assert not os.path.exists(v.caminho('a.pdf', 1)) and not os.path.exists(v.caminho('a.pdf', 1, assinado=True))
    assert v.ultimos_numeros(['a.pdf', 'b.pdf']) == {'a.pdf': 2, 'b.pdf': 0} and v.ultimos_numeros([]) == {}
    assert v.arquivar('a.pdf', str(pdf)) == 3
    Versoes(banco, str(tmp_path / 'res'))  # o app subindo de novo (a migração da coluna não falha)
