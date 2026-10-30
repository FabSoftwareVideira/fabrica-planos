import logging
import os
import time

from . import csvsaida, lock
from .extrator import extrair_texto
from .ollama import chamar_ollama, extrair_json, montar_payload
from .prompt import build_prompt
from .regras import aplicar_regras
from .secoes import analisar_texto

log = logging.getLogger(__name__)


def listar_pdfs(pasta):
    if not os.path.isdir(pasta):
        return []
    return sorted(
        nome for nome in os.listdir(pasta)
        if nome.lower().endswith('.pdf') and os.path.isfile(os.path.join(pasta, nome))
    )


def nome_valido(nome):
    if not nome or not nome.lower().endswith('.pdf'):
        return False
    return '/' not in nome and '\\' not in nome and '..' not in nome


def validar_plano(cfg, nome):
    caminho = os.path.join(cfg.planos_dir, nome)
    try:
        texto = extrair_texto(caminho)
        sec = analisar_texto(texto)
        payload = montar_payload(cfg.modelo, build_prompt(sec), cfg.num_ctx)
        raw = chamar_ollama(cfg.ollama_url, payload)
        validacao = aplicar_regras(extrair_json(raw), {
            'refBasicas': sec['ref_basicas'],
            'refComplementares': sec['ref_complementares'],
            'temObjGeral': bool((sec.get('objetivos_geral') or '').strip()),
            'temObjEspecificos': bool((sec.get('objetivos_especificos') or '').strip()),
            'temHorarioAtendimento': sec['temHorarioAtendimento'],
        })
    except Exception as erro:  # um plano com problema não derruba o lote
        log.exception('Falha ao validar %s', nome)
        validacao = {'status_geral': 'ERRO', 'obs_geral': 'Falha ao processar resposta da IA: ' + str(erro)}
    return csvsaida.linha_resultado(nome, caminho, validacao)


def executar(cfg):
    """Roda a validação de todos os PDFs. Espera que o lock já tenha sido gravado pelo chamador."""
    try:
        nomes = listar_pdfs(cfg.planos_dir)
        log.info('Validação iniciada: %d plano(s), modelo %s em %s', len(nomes), cfg.modelo, cfg.ollama_url)
        linhas = []
        for i, nome in enumerate(nomes, start=1):
            log.info('[%d/%d] Validando %s', i, len(nomes), nome)
            inicio = time.monotonic()
            linha = validar_plano(cfg, nome)
            log.info('[%d/%d] %s: %s (%.0f s)', i, len(nomes), nome, linha['Status Geral'], time.monotonic() - inicio)
            linhas.append(linha)
            lock.atualizar(cfg.lock_path)
        csvsaida.escrever_csv(cfg.csv_path, linhas)
        log.info('Validação concluída: %d plano(s)', len(linhas))
    except Exception:
        log.exception('Validação interrompida por erro inesperado')
        raise
    finally:
        lock.liberar(cfg.lock_path)
