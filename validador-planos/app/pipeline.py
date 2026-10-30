import logging
import os
import time
from datetime import datetime

from . import csvsaida, detalhes
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
    det = {'arquivo': nome, 'modelo': cfg.modelo, 'validado_em': datetime.now().isoformat(timespec='seconds')}
    try:
        det['texto'] = texto = extrair_texto(caminho)
        det['secoes'] = sec = analisar_texto(texto)
        det['prompt'] = prompt = build_prompt(sec)
        payload = montar_payload(cfg.modelo, prompt, cfg.num_ctx)
        det['resposta_ia'] = raw = chamar_ollama(cfg.ollama_url, payload)
        validacao = aplicar_regras(extrair_json(raw), {
            'refBasicas': sec['ref_basicas'],
            'refComplementares': sec['ref_complementares'],
            'temObjGeral': bool((sec.get('objetivos_geral') or '').strip()),
            'temObjEspecificos': bool((sec.get('objetivos_especificos') or '').strip()),
            'temHorarioAtendimento': sec['temHorarioAtendimento'],
        })
    except Exception as erro:  # um plano com problema não derruba o lote
        log.exception('Falha ao validar %s', nome)
        det['erro'] = str(erro)
        validacao = {'status_geral': 'ERRO', 'obs_geral': 'Falha ao processar resposta da IA: ' + str(erro)}
    try:
        detalhes.salvar(cfg.detalhes_dir, nome, det)
    except OSError:
        log.exception('Falha ao gravar os detalhes de %s', nome)
    return csvsaida.linha_resultado(nome, caminho, validacao)


def executar(cfg, andamento, nomes):
    """Valida os PDFs em `nomes`. O chamador já marcou o início em `andamento` (ver Andamento.iniciar)."""
    erro = ''
    try:
        log.info('Validação iniciada: %d plano(s), modelo %s em %s', len(nomes), cfg.modelo, cfg.ollama_url)
        linhas = []
        for i, nome in enumerate(nomes, start=1):
            log.info('[%d/%d] Validando %s', i, len(nomes), nome)
            andamento.validando(nome)
            inicio = time.monotonic()
            linha = validar_plano(cfg, nome)
            log.info('[%d/%d] %s: %s (%.0f s)', i, len(nomes), nome, linha['Status Geral'], time.monotonic() - inicio)
            linhas.append(linha)
            andamento.plano_concluido()
        csvsaida.escrever_csv(cfg.csv_path, linhas)
        detalhes.manter_somente(cfg.detalhes_dir, nomes)
        log.info('Validação concluída: %d plano(s)', len(linhas))
    except Exception as e:
        log.exception('Validação interrompida por erro inesperado')
        erro = str(e) or e.__class__.__name__
        raise
    finally:
        andamento.finalizar(erro)
