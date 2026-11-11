import logging
import os
import unicodedata
from datetime import datetime

from ..armazenamento import assinaturas, csvsaida, detalhes, donos, historico, ocultos
from ..avaliacao import identificacao, pipeline
from ..avaliacao.extrator import PdfIlegivel, extrair_texto

log = logging.getLogger(__name__)


class Ocupado(Exception):
    """Há uma validação em andamento que impede a operação."""


class NaoEncontrado(Exception):
    pass


class Proibido(Exception):
    pass


class PastaDePlanos:
    """Os PDFs da pasta de planos: envio (conferido), listagem e exclusão, pelo administrador ou pelo
    próprio professor ("Meus planos"), com o registro de quem enviou cada um.

    Cada um só exclui (e substitui) os planos que enviou; o administrador também os sem dono (copiados
    direto para a pasta ou enviados antes do registro de dono). Excluir tira o plano também da validação
    atual e apaga a revisão dele. Os planos de outras pessoas o administrador só pode ocultar do painel.

    Usa a trava do validador para não mexer nos PDFs enquanto um lote é validado.
    """

    def __init__(self, cfg, validador, revisoes=None):
        self.cfg = cfg
        self.validador = validador
        self.revisoes = revisoes

    def caminho(self, nome):
        return os.path.join(self.cfg.planos_dir, nome)

    def existe(self, nome):
        return os.path.isfile(self.caminho(nome))

    def dono(self, nome):
        return donos.ler(self.cfg.resultados_dir).get(nome, {}).get('email', '')

    def pode_excluir(self, nome, email):
        """O administrador exclui os planos que enviou e os sem dono."""
        dono = self.dono(nome)
        return not dono or dono == email

    def nomes_ocultos(self):
        return set(ocultos.ler(self.cfg.resultados_dir))

    def listar(self):
        """PDFs da pasta e, depois deles, os planos que só restaram na validação atual (PDF já excluído),
        para o administrador poder limpá-los ou ocultá-los."""
        dono_de = donos.ler(self.cfg.resultados_dir)
        oculto = self.nomes_ocultos()
        planos = []
        na_pasta = pipeline.listar_pdfs(self.cfg.planos_dir)
        for nome in na_pasta:
            info = os.stat(self.caminho(nome))
            planos.append({
                'nome': nome,
                'dono': dono_de.get(nome, {}).get('email', ''),
                'tamanho': info.st_size,
                'modificado': datetime.fromtimestamp(info.st_mtime).isoformat(timespec='seconds'),
                'na_pasta': True,
                'oculto': nome in oculto,
            })
        for nome in sorted(set(pipeline.nomes_na_validacao(self.cfg)) - set(na_pasta)):
            planos.append({'nome': nome, 'dono': dono_de.get(nome, {}).get('email', ''), 'tamanho': None,
                           'modificado': None, 'na_pasta': False, 'oculto': nome in oculto})
        return planos

    # Envio --------------------------------------------------------------------------------------

    def enviar(self, arquivos, email=''):
        """Envio pelo administrador: grava os PDFs válidos, registrando-o como dono, e substitui só os de
        mesmo nome que ele enviou ou sem dono. Devolve (salvos, recusados). Levanta Ocupado durante a
        validação."""
        salvos, recusados = [], []
        with self.validador.trava:
            if self.validador.andamento.rodando:
                raise Ocupado
            for arquivo in arquivos:
                nome = nome_enviado(arquivo)
                substituido = self.existe(nome)
                motivo = self._motivo_recusa(nome, arquivo)
                if not motivo and substituido and not self.pode_excluir(nome, email):
                    motivo = 'Já existe na pasta um plano com esse nome, enviado por outra pessoa; renomeie o arquivo'
                texto = None
                if not motivo:
                    motivo, texto = self._salvar(arquivo, nome)
                if motivo:
                    recusados.append({'nome': nome, 'motivo': motivo})
                    continue
                donos.definir(self.cfg.resultados_dir, nome, email, identificacao.extrair(texto))
                ocultos.mostrar(self.cfg.resultados_dir, [nome])  # versão nova volta a aparecer no painel
                salvos.append({'nome': nome, 'substituido': substituido})
        log.info('Upload: %d salvo(s), %d recusado(s)', len(salvos), len(recusados))
        return salvos, recusados

    def enviar_do_professor(self, arquivos, email):
        """Entrega pelo professor: aceita mesmo durante a validação; só substitui os PDFs que ele mesmo
        enviou. Cada PDF salvo entra na fila de avaliação (`posicao`, 0 se já começou)."""
        salvos, recusados = [], []
        with self.validador.trava:
            dono_de = donos.ler(self.cfg.resultados_dir)
            for arquivo in arquivos:
                nome = nome_enviado(arquivo)
                motivo = self._motivo_recusa(nome, arquivo)
                existe = not motivo and self.existe(nome)
                if existe and dono_de.get(nome, {}).get('email') != email:
                    motivo = ('Já existe na pasta um plano com esse nome, enviado por outra pessoa; renomeie o '
                              'arquivo (ex.: 2026-1 - Disciplina - Seu nome.pdf)')
                texto = None
                if not motivo:
                    motivo, texto = self._salvar(arquivo, nome)
                if motivo:
                    recusados.append({'nome': nome, 'motivo': motivo})
                    continue
                # Curso e período já no envio: o plano aparece no grupo certo antes de ser avaliado.
                donos.definir(self.cfg.resultados_dir, nome, email, identificacao.extrair(texto))
                ocultos.mostrar(self.cfg.resultados_dir, [nome])  # versão nova volta a aparecer no painel
                salvos.append({'nome': nome, 'substituido': existe})
        for salvo in salvos:  # a avaliação começa já, ou espera a vez na fila
            salvo['posicao'] = self.validador.enfileirar(salvo['nome'])
        log.info('Meus planos (%s): %d salvo(s), %d recusado(s)', email, len(salvos), len(recusados))
        return salvos, recusados

    def _motivo_recusa(self, nome, arquivo):
        """Checagens que não precisam gravar o arquivo; devolve o motivo da recusa ou None."""
        if not pipeline.nome_valido(nome) or nome.startswith('.'):
            return 'Apenas arquivos .pdf são aceitos'
        if _tamanho(arquivo) > self.cfg.pdf_max_mb * 1024 * 1024:
            return f'Arquivo maior que {self.cfg.pdf_max_mb} MB'
        if arquivo.stream.read(5) != b'%PDF-':
            return 'O conteúdo não é um PDF'
        arquivo.stream.seek(0)
        return None

    def _salvar(self, arquivo, nome):
        """Grava o PDF na pasta de planos; devolve (motivo da recusa ou None, texto extraído)."""
        destino = self.caminho(nome)
        temporario = destino + '.enviando'
        arquivo.save(temporario)
        # Só entra na pasta o PDF que abre e tem texto; digitalizados precisam de OCR antes.
        try:
            texto = extrair_texto(temporario)
        except PdfIlegivel as erro:
            os.remove(temporario)
            return str(erro), None
        os.replace(temporario, destino)
        return None, texto

    # Exclusão -----------------------------------------------------------------------------------

    def _conhecido(self, nome):
        """Na pasta ou com avaliação na validação atual."""
        return self.existe(nome) or nome in pipeline.nomes_na_validacao(self.cfg)

    def _apagar(self, nome):
        """Com a trava: o PDF, o registro de dono, a marca de oculto, a avaliação na validação atual, a
        revisão e o PDF assinado pelo professor. Excluir é definitivo; para só tirar do painel existe ocultar."""
        if self.existe(nome):
            os.remove(self.caminho(nome))
        donos.remover(self.cfg.resultados_dir, [nome])
        ocultos.mostrar(self.cfg.resultados_dir, [nome])
        pipeline.remover_da_validacao(self.cfg, [nome])
        if self.revisoes is not None:
            self.revisoes.remover(nome)
        assinaturas.remover(self.cfg.resultados_dir, [nome])

    def excluir(self, nome, email=''):
        """Exclusão pelo administrador: só os planos que ele enviou ou sem dono (Proibido nos demais)."""
        with self.validador.trava:
            if self.validador.andamento.rodando:
                raise Ocupado
            if not self._conhecido(nome):
                raise NaoEncontrado
            if not self.pode_excluir(nome, email):
                raise Proibido
            self._apagar(nome)
        log.info('Plano excluído (%s): %s', email, nome)

    def excluir_do_professor(self, nome, email):
        with self.validador.trava:
            if self.dono(nome) != email:
                raise Proibido
            if self.validador.em_avaliacao(nome):
                raise Ocupado
            self._apagar(nome)
            self.validador.remover_da_fila(nome)
        log.info('Meus planos (%s): excluído %s', email, nome)

    # Ocultar do painel -----------------------------------------------------------------------------

    def ocultar(self, nome, email):
        """Tira o plano do dashboard e da visão da coordenação, sem apagar o PDF nem a avaliação."""
        if not self._conhecido(nome):
            raise NaoEncontrado
        ocultos.ocultar(self.cfg.resultados_dir, nome, email)
        log.info('Plano ocultado do painel (%s): %s', email, nome)

    def mostrar(self, nome, email):
        ocultos.mostrar(self.cfg.resultados_dir, [nome])
        log.info('Plano de volta ao painel (%s): %s', email, nome)

    def cursos(self):
        """{sigla: nome} dos cursos conhecidos: os de identificacao.CURSOS e os dos planos na pasta e na
        validação atual (para escolher o curso de um papel na administração)."""
        cursos = dict(identificacao.CURSOS)
        idents = [d.get('identificacao') for d in donos.ler(self.cfg.resultados_dir).values()]
        execucoes = historico.listar(self.cfg.historico_dir)
        if execucoes:
            for linha in csvsaida.ler_csv(execucoes[0].csv_path):
                idents.append(identificacao.de_detalhes(detalhes.ler(execucoes[0].detalhes_dir, linha.get('Arquivo'))))
        for ident in idents:
            if ident:
                cursos.setdefault(ident['sigla_curso'], ident['curso'])
        return dict(sorted(cursos.items()))

    # Situação dos planos do professor -----------------------------------------------------------

    def do_professor(self, email):
        """Planos que o professor enviou, com a situação de cada um (na fila, com a posição; sendo avaliado;
        avaliado, com o resultado; ou aguardando a próxima validação geral) e o grupo de curso e período,
        na ordem dos grupos (o período mais recente primeiro)."""
        meus = {n: d for n, d in donos.ler(self.cfg.resultados_dir).items()
                if d.get('email') == email and self.existe(n)}
        execucoes = historico.listar(self.cfg.historico_dir)
        ultima = execucoes[0] if execucoes else None
        linhas = {l.get('Arquivo'): l for l in csvsaida.ler_csv(ultima.csv_path)} if ultima else {}
        estado = self.validador.andamento.resumo()
        fila = self.validador.fila()
        planos = []
        for nome, dono in meus.items():
            det = detalhes.ler(ultima.detalhes_dir, nome) if ultima and nome in linhas else None
            atual = det and det.get('validado_em', '') >= dono['enviado_em']  # avaliação do PDF enviado agora
            # Curso e período: do texto avaliado, se for do PDF atual; senão, os lidos no envio.
            ident = ((identificacao.de_detalhes(det) if atual else None) or dono.get('identificacao')
                     or identificacao.de_detalhes(det))
            chave, titulo, ordem = identificacao.grupo_curso_periodo(ident)
            item = {'nome': nome, 'enviado_em': dono['enviado_em'], 'grupo': chave, 'grupo_titulo': titulo,
                    'ordem': ordem, 'componente': _descricao(ident)}
            if nome in fila:
                item.update(situacao='na_fila', posicao=fila.index(nome) + 1)
            elif estado['rodando'] and nome in (estado['atual'], estado['unico']):
                item['situacao'] = 'validando'
            else:
                linha = linhas.get(nome)
                if atual:  # o resultado só vale se for do PDF atual, validado depois do envio
                    item.update(situacao='avaliado', status=linha.get('Status Geral', ''),
                                obs=linha.get('Observação Geral', ''),
                                problemas=[r for r, _ in csvsaida.CAMPOS_COLUNA if linha.get(r) != 'OK'])
                else:
                    item['situacao'] = 'aguardando'
            planos.append(item)
        planos.sort(key=lambda p: (p['ordem'], p['grupo_titulo'], p['nome']))
        return planos


def _descricao(ident):
    """'CCC0723 · Desenvolvimento Web I · Turma 01', ou vazio sem identificação."""
    if not ident:
        return ''
    return ' · '.join([ident['codigo'], ident['disciplina']] + (['Turma ' + ident['turma']] if ident['turma'] else []))


def nome_enviado(arquivo):
    # Navegadores antigos mandam o caminho completo; o macOS manda acentos decompostos (NFD).
    nome = (arquivo.filename or '').replace('\\', '/').rsplit('/', 1)[-1].strip()
    return unicodedata.normalize('NFC', nome)


def _tamanho(arquivo):
    arquivo.stream.seek(0, os.SEEK_END)
    tamanho = arquivo.stream.tell()
    arquivo.stream.seek(0)
    return tamanho
