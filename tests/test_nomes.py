"""Testes unitários da conferência de nomes: o docente do PDF precisa ter o nome do professor que o envia
(app/avaliacao/identificacao.py: nomes_parecidos) e a recusa do envio (app/servicos/planos.py)."""
import pytest

from app.avaliacao import identificacao
from app.servicos.planos import _motivo_docente


@pytest.mark.parametrize('nome, partes', [
    ('Fulano de Tal', {'FULANO', 'TAL'}),
    ('  JOÃO  da  Silva e Souza ', {'JOAO', 'SILVA', 'SOUZA'}),
    ('Maria Dos Anjos', {'MARIA', 'ANJOS'}),
    ("Ana-Paula D'Ávila", {'ANA', 'PAULA', 'D', 'AVILA'}),
    ('', set()),
    (None, set()),
])
def test_partes_do_nome_sem_acentos_nem_particulas(nome, partes):
    assert identificacao.partes_do_nome(nome) == partes


@pytest.mark.parametrize('cadastro, pdf', [
    ('Fulano de Tal', 'FULANO DE TAL'),               # mesmo nome, outra caixa
    ('Fulano de Tal', 'FULANO DE TAL SILVA'),         # sobrenome a mais no PDF
    ('Fulano Silva de Tal', 'Fulano Tal'),            # sobrenome a mais no cadastro
    ('José Antônio Pereira', 'JOSE ANTONIO PEREIRA'),  # acentos
    ('Luis Carlos Souza', 'LUIZ CARLOS SOUZA'),       # uma letra diferente
    ('Fulano de Tal', 'FULANU DE TAL'),               # erro de digitação
    ('Ana Paula Rocha', 'A. PAULA ROCHA'),            # abreviação
    ('Ana Paula Rocha', 'ANA P ROCHA'),               # inicial
])
def test_nomes_parecidos(cadastro, pdf):
    assert identificacao.nomes_parecidos(cadastro, pdf)
    assert identificacao.nomes_parecidos(pdf, cadastro)  # a ordem não importa


@pytest.mark.parametrize('cadastro, pdf', [
    ('Fulano de Tal', 'BELTRANO PEREIRA'),   # outra pessoa
    ('Marcos Silva', 'MARCIO SILVA'),        # duas letras diferentes
    ('Fulano de Tal', 'FULANO SOUZA'),       # só o primeiro nome igual
    ('Fulano', 'FULANO DE TAL'),             # um nome só não basta para identificar
    ('', 'FULANO DE TAL'),
    ('Ana Paula Rocha', 'ANA PAULA ROSA'),   # sobrenomes curtos com letra trocada
])
def test_nomes_diferentes(cadastro, pdf):
    assert not identificacao.nomes_parecidos(cadastro, pdf)


@pytest.mark.parametrize('a, b, esperado', [
    ('SILVA', 'SILVA', True), ('SILVA', 'SILVO', True), ('SILVA', 'SILV', True), ('SILVA', 'SIILVA', True),
    ('SILVA', 'SOUZA', False), ('SILVA', 'SIL', False), ('ABCD', 'BADC', False),
])
def test_uma_letra_de_diferenca(a, b, esperado):
    assert identificacao._uma_letra(a, b) is esperado


TEXTO = 'Matrícula Docente(s)\n1234567 FULANO DE TAL SILVA - 60h\n7654321 BELTRANO PEREIRA - 30h\n'


def test_motivo_docente_aceita_qualquer_um_dos_docentes():
    assert _motivo_docente(TEXTO, 'Fulano de Tal') is None
    assert _motivo_docente(TEXTO, 'Beltrano Pereira') is None


def test_motivo_docente_recusa_quem_nao_e_docente():
    motivo = _motivo_docente(TEXTO, 'Ciclano Souza')
    assert 'Fulano de Tal Silva' in motivo and 'Beltrano Pereira' in motivo and 'Ciclano Souza' in motivo


def test_motivo_docente_sem_o_que_conferir():
    assert _motivo_docente('Plano sem o bloco de docentes', 'Ciclano Souza') is None
    assert _motivo_docente(TEXTO, '') is None
