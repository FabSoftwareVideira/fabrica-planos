import logging
import os
import time
from datetime import datetime

from ..armazenamento import csvsaida, detalhes, historico
from . import identificacao
from .extrator import PdfIlegivel, extrair_texto
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


def validar_plano(cfg, nome, detalhes_dir):
    caminho = os.path.join(cfg.planos_dir, nome)
    det = {'arquivo': nome, 'modelo': cfg.modelo, 'validado_em': datetime.now().isoformat(timespec='seconds')}
    try:
        det['texto'] = texto = extrair_texto(caminho)
        det['identificacao_plano'] = identificacao.extrair(texto)  # curso e período, para agrupar
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
            'textoHorario': sec.get('horario_atendimento', ''),
        })
    except PdfIlegivel as erro:  # não adianta chamar a IA sem texto
        log.warning('%s: %s', nome, erro)
        det['erro'] = str(erro)
        validacao = {'status_geral': 'ERRO', 'obs_geral': str(erro)}
    except Exception as erro:  # um plano com problema não derruba o lote
        log.exception('Falha ao validar %s', nome)
        det['erro'] = str(erro)
        validacao = {'status_geral': 'ERRO', 'obs_geral': 'Falha ao processar resposta da IA: ' + str(erro)}
    try:
        detalhes.salvar(detalhes_dir, nome, det)
    except OSError:
        log.exception('Falha ao gravar os detalhes de %s', nome)
    return csvsaida.linha_resultado(nome, caminho, validacao)


def executar(cfg, andamento, nomes):
    """Valida os PDFs em `nomes`. O chamador já marcou o início em `andamento` (ver Andamento.iniciar)."""
    erro = ''
    linhas = []
    iniciado_em = datetime.now()
    execucao = None
    try:
        execucao = historico.criar(cfg.historico_dir, iniciado_em)
        log.info('Validação %s iniciada: %d plano(s), modelo %s em %s',
                 execucao.id, len(nomes), cfg.modelo, cfg.ollama_url)
        for i, nome in enumerate(nomes, start=1):
            log.info('[%d/%d] Validando %s', i, len(nomes), nome)
            andamento.validando(nome)
            inicio = time.monotonic()
            historico.guardar_pdf(execucao, os.path.join(cfg.planos_dir, nome))
            linha = validar_plano(cfg, nome, execucao.detalhes_dir)
            log.info('[%d/%d] %s: %s (%.0f s)', i, len(nomes), nome, linha['Status Geral'], time.monotonic() - inicio)
            linhas.append(linha)
            andamento.plano_concluido()
        csvsaida.escrever_csv(execucao.csv_path, linhas)
        csvsaida.escrever_csv(cfg.csv_path, linhas)
        log.info('Validação concluída: %d plano(s)', len(linhas))
    except Exception as e:
        log.exception('Validação interrompida por erro inesperado')
        erro = str(e) or e.__class__.__name__
        raise
    finally:
        if execucao is not None:
            _registrar(cfg, execucao, linhas, nomes, iniciado_em, erro)
        andamento.finalizar(erro)


def revalidar(cfg, andamento, nome):
    """Valida de novo um plano e atualiza a última validação do histórico (substitui a linha dele ou a
    acrescenta, se for novo). Sem histórico, cria uma validação só com ele. O chamador já chamou
    andamento.iniciar(1, unico=nome)."""
    erro = ''
    try:
        execucoes = historico.listar(cfg.historico_dir)
        execucao = execucoes[0] if execucoes else historico.criar(cfg.historico_dir)
        meta = (execucao.meta() or {'iniciado_em': datetime.now().isoformat(timespec='seconds'), 'erro': ''})
        log.info('Revalidando %s na validação %s', nome, execucao.id)
        andamento.validando(nome)
        historico.guardar_pdf(execucao, os.path.join(cfg.planos_dir, nome))
        linha = validar_plano(cfg, nome, execucao.detalhes_dir)
        linhas = [l for l in csvsaida.ler_csv(execucao.csv_path) if l.get('Arquivo') != nome] + [linha]
        linhas.sort(key=lambda l: l.get('Arquivo', ''))  # mesma ordem de listar_pdfs
        csvsaida.escrever_csv(execucao.csv_path, linhas)
        csvsaida.escrever_csv(cfg.csv_path, linhas)
        agora = datetime.now().isoformat(timespec='seconds')
        meta.update(total=len(linhas), processados=len(linhas), modelo=cfg.modelo, revalidado_em=agora,
                    **historico.contar(linhas))
        meta.setdefault('finalizado_em', agora)
        historico.gravar_meta(execucao, meta)
        andamento.plano_concluido()
        log.info('%s revalidado: %s', nome, linha['Status Geral'])
    except Exception as e:
        log.exception('Revalidação de %s interrompida por erro inesperado', nome)
        erro = str(e) or e.__class__.__name__
        raise
    finally:
        andamento.finalizar(erro)


def _registrar(cfg, execucao, linhas, nomes, iniciado_em, erro):
    """Fecha a execução no histórico (mesmo interrompida, com o que foi validado) e poda as antigas."""
    try:
        if erro and not os.path.exists(execucao.csv_path):
            csvsaida.escrever_csv(execucao.csv_path, linhas)
        historico.gravar_meta(execucao, {
            'iniciado_em': iniciado_em.isoformat(timespec='seconds'),
            'finalizado_em': datetime.now().isoformat(timespec='seconds'),
            'modelo': cfg.modelo, 'total': len(nomes), 'processados': len(linhas), 'erro': erro,
            **historico.contar(linhas),
        })
        historico.podar(cfg.historico_dir)  # fica só a validação atual
    except Exception:
        log.exception('Falha ao registrar a validação %s no histórico', execucao.id)
