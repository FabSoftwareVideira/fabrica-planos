import logging
import os
import unicodedata
from datetime import datetime

from ..armazenamento import csvsaida, detalhes, donos, historico
from ..avaliacao import pipeline
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

    Usa a trava do validador para não mexer nos PDFs enquanto um lote é validado.
    """

    def __init__(self, cfg, validador):
        self.cfg = cfg
        self.validador = validador

    def caminho(self, nome):
        return os.path.join(self.cfg.planos_dir, nome)

    def existe(self, nome):
        return os.path.isfile(self.caminho(nome))

    def listar(self):
        dono_de = donos.ler(self.cfg.resultados_dir)
        planos = []
        for nome in pipeline.listar_pdfs(self.cfg.planos_dir):
            info = os.stat(self.caminho(nome))
            planos.append({
                'nome': nome,
                'dono': dono_de.get(nome, {}).get('email', ''),
                'tamanho': info.st_size,
                'modificado': datetime.fromtimestamp(info.st_mtime).isoformat(timespec='seconds'),
            })
        return planos

    # Envio --------------------------------------------------------------------------------------

    def enviar(self, arquivos):
        """Envio pelo administrador: grava os PDFs válidos, substituindo os de mesmo nome. Devolve
        (salvos, recusados). Levanta Ocupado durante a validação."""
        salvos, recusados = [], []
        with self.validador.trava:
            if self.validador.andamento.rodando:
                raise Ocupado
            for arquivo in arquivos:
                nome = nome_enviado(arquivo)
                substituido = self.existe(nome)
                motivo = self._motivo_recusa(nome, arquivo) or self._salvar(arquivo, nome)
                if motivo:
                    recusados.append({'nome': nome, 'motivo': motivo})
                    continue
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
                motivo = motivo or self._salvar(arquivo, nome)
                if motivo:
                    recusados.append({'nome': nome, 'motivo': motivo})
                    continue
                donos.definir(self.cfg.resultados_dir, nome, email)
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
        """Grava o PDF na pasta de planos; devolve o motivo da recusa ou None."""
        destino = self.caminho(nome)
        temporario = destino + '.enviando'
        arquivo.save(temporario)
        # Só entra na pasta o PDF que abre e tem texto; digitalizados precisam de OCR antes.
        try:
            extrair_texto(temporario)
        except PdfIlegivel as erro:
            os.remove(temporario)
            return str(erro)
        os.replace(temporario, destino)
        return None

    # Exclusão -----------------------------------------------------------------------------------

    def excluir(self, nome):
        with self.validador.trava:
            if self.validador.andamento.rodando:
                raise Ocupado
            if not self.existe(nome):
                raise NaoEncontrado
            os.remove(self.caminho(nome))
            donos.remover(self.cfg.resultados_dir, [nome])
        log.info('Plano excluído: %s', nome)

    def excluir_todos(self):
        """Esvazia a pasta de planos. O histórico (e os PDFs da última validação, para o zip) continuam."""
        with self.validador.trava:
            if self.validador.andamento.rodando:
                raise Ocupado
            nomes = pipeline.listar_pdfs(self.cfg.planos_dir)
            for nome in nomes:
                os.remove(self.caminho(nome))
            donos.remover(self.cfg.resultados_dir, nomes)
        log.info('Todos os planos excluídos: %d arquivo(s)', len(nomes))
        return len(nomes)

    def excluir_do_professor(self, nome, email):
        with self.validador.trava:
            if donos.ler(self.cfg.resultados_dir).get(nome, {}).get('email') != email:
                raise Proibido
            if self.validador.em_avaliacao(nome):
                raise Ocupado
            if self.existe(nome):
                os.remove(self.caminho(nome))
            donos.remover(self.cfg.resultados_dir, [nome])
            self.validador.remover_da_fila(nome)
        log.info('Meus planos (%s): excluído %s', email, nome)

    # Situação dos planos do professor -----------------------------------------------------------

    def do_professor(self, email):
        """Planos que o professor enviou, com a situação de cada um: na fila (com a posição), sendo
        avaliado, avaliado (com o resultado) ou aguardando a próxima validação geral."""
        meus = {n: d for n, d in donos.ler(self.cfg.resultados_dir).items()
                if d.get('email') == email and self.existe(n)}
        execucoes = historico.listar(self.cfg.historico_dir)
        ultima = execucoes[0] if execucoes else None
        linhas = {l.get('Arquivo'): l for l in csvsaida.ler_csv(ultima.csv_path)} if ultima else {}
        estado = self.validador.andamento.resumo()
        fila = self.validador.fila()
        planos = []
        for nome, dono in sorted(meus.items()):
            item = {'nome': nome, 'enviado_em': dono['enviado_em']}
            if nome in fila:
                item.update(situacao='na_fila', posicao=fila.index(nome) + 1)
            elif estado['rodando'] and nome in (estado['atual'], estado['unico']):
                item['situacao'] = 'validando'
            else:
                linha = linhas.get(nome)
                det = detalhes.ler(ultima.detalhes_dir, nome) if linha else None
                # O resultado só vale se for do PDF atual, validado depois do envio.
                if det and det.get('validado_em', '') >= dono['enviado_em']:
                    item.update(situacao='avaliado', status=linha.get('Status Geral', ''),
                                obs=linha.get('Observação Geral', ''),
                                problemas=[r for r, _ in csvsaida.CAMPOS_COLUNA if linha.get(r) != 'OK'])
                else:
                    item['situacao'] = 'aguardando'
            planos.append(item)
        return planos


def nome_enviado(arquivo):
    # Navegadores antigos mandam o caminho completo; o macOS manda acentos decompostos (NFD).
    nome = (arquivo.filename or '').replace('\\', '/').rsplit('/', 1)[-1].strip()
    return unicodedata.normalize('NFC', nome)


def _tamanho(arquivo):
    arquivo.stream.seek(0, os.SEEK_END)
    tamanho = arquivo.stream.tell()
    arquivo.stream.seek(0)
    return tamanho
