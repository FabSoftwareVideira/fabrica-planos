import csv
from datetime import datetime, timedelta, timezone

from app import csvsaida, lock
from app.pipeline import nome_valido
from app.prompt import build_prompt
from app.secoes import analisar_texto


def test_lock_recente_ocupa(tmp_path):
    caminho = tmp_path / 'validacao.lock'
    agora = datetime.now(timezone.utc)
    caminho.write_text((agora - timedelta(minutes=2)).isoformat())
    assert lock.ocupado(str(caminho), agora)


def test_lock_antigo_nao_ocupa(tmp_path):
    caminho = tmp_path / 'validacao.lock'
    agora = datetime.now(timezone.utc)
    caminho.write_text((agora - timedelta(minutes=40)).isoformat())
    assert not lock.ocupado(str(caminho), agora)


def test_lock_ausente_ou_vazio_nao_ocupa(tmp_path):
    caminho = tmp_path / 'validacao.lock'
    assert not lock.ocupado(str(caminho))
    caminho.write_text('')
    assert not lock.ocupado(str(caminho))


def test_lock_aceita_formato_z_do_n8n(tmp_path):
    caminho = tmp_path / 'validacao.lock'
    agora = datetime.now(timezone.utc)
    recente = (agora - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    caminho.write_text(recente)
    assert lock.ocupado(str(caminho), agora)


def test_liberar_deixa_livre(tmp_path):
    caminho = tmp_path / 'validacao.lock'
    lock.atualizar(str(caminho))
    assert lock.ocupado(str(caminho))
    lock.liberar(str(caminho))
    assert not lock.ocupado(str(caminho))


def test_csv_usa_ponto_e_virgula_e_bom(tmp_path):
    caminho = tmp_path / 'saida.csv'
    validacao = {'status_geral': 'OK', 'obs_geral': 'tudo; certo', 'ementa': {'status': 'OK', 'obs': 'a "b"'}}
    linha = csvsaida.linha_resultado('plano.pdf', '/x/plano.pdf', validacao, datetime(2026, 10, 30, 5, 0))
    csvsaida.escrever_csv(str(caminho), [linha])
    bruto = caminho.read_bytes()
    assert bruto.startswith(b'\xef\xbb\xbf')
    lido = csvsaida.ler_csv(str(caminho))
    assert lido[0]['Arquivo'] == 'plano.pdf'
    assert lido[0]['Observação Geral'] == 'tudo; certo'
    assert lido[0]['Ementa Obs'] == 'a "b"'
    assert lido[0]['Data Validação'] == '30/10/2026, 05:00:00'
    with open(caminho, encoding='utf-8-sig', newline='') as arq:
        assert next(csv.reader(arq, delimiter=';'))[0] == 'Arquivo'


def test_linha_sem_resposta_marca_erro():
    linha = csvsaida.linha_resultado('x.pdf', '/x.pdf', {'status_geral': 'ERRO', 'obs_geral': 'falhou'})
    assert linha['Ementa'] == 'ERRO'
    assert linha['Status Geral'] == 'ERRO'


def test_nome_pdf_valido():
    assert nome_valido('plano.pdf')
    assert nome_valido('Plano.PDF')
    assert not nome_valido('../x.pdf')
    assert not nome_valido('sub/x.pdf')
    assert not nome_valido('x.txt')
    assert not nome_valido('')


def test_prompt_inclui_contagem_e_secoes():
    sec = analisar_texto('Ementa: texto da ementa com algumas palavras para o teste.\nReferências Básicas\nLivro A.\n')
    prompt = build_prompt(sec)
    assert 'EMENTA:\ntexto da ementa' in prompt
    assert 'referência(s) básica(s)' in prompt
    assert prompt.rstrip().endswith('complementar(es).')
