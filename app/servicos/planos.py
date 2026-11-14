import logging
import os
from datetime import datetime

from ..armazenamento import assinaturas, csvsaida, detalhes, historico, liberacoes, ocultos
from ..avaliacao import identificacao, pipeline
from ..avaliacao.extrator import PdfIlegivel, extrair_texto

log = logging.getLogger(__name__)


class Ocupado(Exception):
    """Há uma validação em andamento que impede a operação."""


class NaoEncontrado(Exception):
    pass


class Proibido(Exception):
    pass


class Recusado(Exception):
    """O PDF enviado não foi aceito; a mensagem diz por quê."""


class PastaDePlanos:
    """Os PDFs da pasta de planos: envio (conferido), listagem e exclusão.

    Cada plano é de uma disciplina ofertada no semestre (servicos/disciplinas.py): o professor envia o PDF
    para uma das disciplinas em que é docente, e ele fica na pasta com o nome da oferta (o nome do arquivo
    enviado não importa). Os docentes da disciplina substituem e excluem o plano dela; o administrador
    exclui só os PDFs sem disciplina (copiados direto para a pasta) e oculta os demais do painel. Excluir
    tira o plano também da validação atual e apaga a revisão dele. Depois de assinado, o plano só é
    substituído se a coordenação do curso liberar o reenvio (resultados/liberacoes.json).

    Usa a trava do validador para não mexer nos PDFs enquanto um lote é validado.
    """

    def __init__(self, cfg, validador, revisoes=None, assinaturas=None, disciplinas=None):
        self.cfg = cfg
        self.validador = validador
        self.revisoes = revisoes
        self.assinaturas = assinaturas
        self.disciplinas = disciplinas

    def caminho(self, nome):
        return os.path.join(self.cfg.planos_dir, nome)

    def existe(self, nome):
        return os.path.isfile(self.caminho(nome))

    def docentes(self, nome):
        """E-mails dos docentes da disciplina do plano ([] se o PDF não é de nenhuma disciplina)."""
        return self.disciplinas.docentes_do_arquivo(nome) if self.disciplinas else []

    def eh_docente(self, nome, email):
        """Docente da disciplina do plano. Sem login exigido (uso local), todos são."""
        if not self.cfg.exigir_login:
            return bool(self.disciplinas and self.disciplinas.do_arquivo(nome))
        return bool(email) and email in self.docentes(nome)

    def pode_excluir(self, nome, email=''):
        """O administrador exclui só os PDFs sem disciplina; os das disciplinas ficam com os docentes."""
        return not (self.disciplinas and self.disciplinas.do_arquivo(nome))

    def assinado(self, nome):
        """O plano está assinado pelo professor e a assinatura ainda vale (ver servicos/assinatura.py)."""
        return bool(self.assinaturas and self.assinaturas.vigente(nome))

    def reenvio_liberado(self, nome):
        """A coordenação liberou o envio de uma nova versão deste plano assinado."""
        return self.assinado(nome) and liberacoes.liberado(self.cfg.resultados_dir, nome)

    def pode_reenviar(self, nome):
        """Plano assinado só é substituído depois de a coordenação do curso liberar o reenvio."""
        return not self.assinado(nome) or liberacoes.liberado(self.cfg.resultados_dir, nome)

    def nomes_ocultos(self):
        return set(ocultos.ler(self.cfg.resultados_dir))

    def listar(self):
        """PDFs da pasta e, depois deles, os planos que só restaram na validação atual (PDF já excluído),
        para o administrador poder limpá-los ou ocultá-los. `dono`: os docentes da disciplina."""
        ofertas = self.disciplinas.ofertas.por_arquivo() if self.disciplinas else {}
        oculto = self.nomes_ocultos()

        def docentes(nome):
            return ', '.join((ofertas.get(nome) or {}).get('docentes', []))
        planos = []
        na_pasta = pipeline.listar_pdfs(self.cfg.planos_dir)
        for nome in na_pasta:
            info = os.stat(self.caminho(nome))
            planos.append({
                'nome': nome,
                'dono': docentes(nome),
                'disciplina': _descricao(self.disciplinas.identificacao(ofertas.get(nome))) if ofertas.get(nome) else '',
                'tamanho': info.st_size,
                'modificado': datetime.fromtimestamp(info.st_mtime).isoformat(timespec='seconds'),
                'na_pasta': True,
                'oculto': nome in oculto,
            })
        for nome in sorted(set(pipeline.nomes_na_validacao(self.cfg)) - set(na_pasta)):
            planos.append({'nome': nome, 'dono': docentes(nome), 'disciplina': '', 'tamanho': None,
                           'modificado': None, 'na_pasta': False, 'oculto': nome in oculto})
        return planos

    def responsaveis(self, usuarios):
        """{arquivo: [nome dos docentes]} dos planos das disciplinas, pelo cadastro (o e-mail de quem ainda
        não entrou no sistema)."""
        nomes, saida = {}, {}
        ofertas = self.disciplinas.ofertas.por_arquivo() if self.disciplinas else {}
        for arquivo, oferta in ofertas.items():
            for email in oferta['docentes']:
                if email not in nomes:
                    nomes[email] = (usuarios.obter(email) or {}).get('nome') or email
            if oferta['docentes']:
                saida[arquivo] = [nomes[e] for e in oferta['docentes']]
        return saida

    # Envio --------------------------------------------------------------------------------------

    def enviar_para_oferta(self, oferta_id, arquivo, email, nomes_docentes=()):
        """Plano enviado pelo professor para uma disciplina em que é docente: grava o PDF com o nome da
        oferta e o põe na fila de avaliação. Aceita mesmo durante a validação. Devolve {'nome', 'substituido',
        'aviso', 'posicao'}; levanta Recusado. O código da disciplina e o nome do docente escritos no PDF são
        só conferidos: se não baterem com a disciplina, o plano entra com um aviso, que o professor e a
        coordenação veem (`nomes_docentes`: os nomes do cadastro dos docentes da disciplina)."""
        oferta = self.disciplinas.oferta(oferta_id) if self.disciplinas else None
        if not oferta or not self.disciplinas.publicado(oferta):
            raise Recusado('Disciplina não encontrada.')
        if self.cfg.exigir_login and email not in oferta['docentes']:
            raise Recusado('Você não é docente desta disciplina. Peça à coordenação do curso que vincule você a ela.')
        nome = oferta['arquivo']
        motivo = self._motivo_recusa(arquivo)
        with self.validador.trava:
            existe = self.existe(nome)
            if not motivo and existe and not self.pode_reenviar(nome):
                motivo = ('Este plano já está assinado; para enviar uma nova versão, peça à coordenação do '
                          'curso que libere o reenvio')
            texto = None
            if not motivo:
                motivo, texto = self._salvar(arquivo, nome)
            if motivo:
                raise Recusado(motivo)
            aviso = _aviso(texto, oferta, nomes_docentes)
            self.disciplinas.ofertas.registrar_envio(nome, email, aviso)
            ocultos.mostrar(self.cfg.resultados_dir, [nome])  # versão nova volta a aparecer no painel
            liberacoes.cancelar(self.cfg.resultados_dir, nome)  # a liberação vale para um envio
        posicao = self.validador.enfileirar(nome)  # a avaliação começa já, ou espera a vez na fila
        log.info('Meus planos (%s): plano de %s enviado (%s)%s', email, _descricao(self.disciplinas.identificacao(oferta)),
                 nome, ' com aviso' if aviso else '')
        return {'nome': nome, 'substituido': existe, 'aviso': aviso, 'posicao': posicao}

    def _motivo_recusa(self, arquivo):
        """Checagens que não precisam gravar o arquivo; devolve o motivo da recusa ou None."""
        if _tamanho(arquivo) > self.cfg.pdf_max_mb * 1024 * 1024:
            return f'Arquivo maior que {self.cfg.pdf_max_mb} MB'
        if arquivo.stream.read(5) != b'%PDF-':
            return 'O conteúdo não é um PDF'
        arquivo.stream.seek(0)
        return None

    def _salvar(self, arquivo, nome, conferir=None):
        """Grava o PDF na pasta de planos; devolve (motivo da recusa ou None, texto extraído). `conferir(texto)`
        pode recusá-lo antes de ele substituir o PDF anterior (devolve o motivo ou None)."""
        destino = self.caminho(nome)
        temporario = destino + '.enviando'
        arquivo.save(temporario)
        # Só entra na pasta o PDF que abre e tem texto; digitalizados precisam de OCR antes.
        try:
            texto = extrair_texto(temporario)
        except PdfIlegivel as erro:
            os.remove(temporario)
            return str(erro), None
        motivo = conferir(texto) if conferir else None
        if motivo:
            os.remove(temporario)
            return motivo, None
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
        if self.disciplinas:
            self.disciplinas.ofertas.limpar_envio(nome)
        ocultos.mostrar(self.cfg.resultados_dir, [nome])
        liberacoes.remover(self.cfg.resultados_dir, [nome])
        pipeline.remover_da_validacao(self.cfg, [nome])
        if self.revisoes is not None:
            self.revisoes.remover(nome)
        assinaturas.remover(self.cfg.resultados_dir, [nome])

    def excluir(self, nome, email=''):
        """Exclusão pelo administrador: só os PDFs sem disciplina (Proibido nos demais)."""
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
            if not self.eh_docente(nome, email) or not self.existe(nome):
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
        """{sigla: nome} dos cursos conhecidos: os com disciplinas e os dos planos da validação atual (para
        escolher o curso de um papel na administração)."""
        cursos = dict(identificacao.CURSOS)
        if self.disciplinas:
            cursos.update(self.disciplinas.cursos())
        idents = []
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
        """As disciplinas em que o professor é docente, cada uma com o seu plano e a situação dele (sem plano;
        na fila, com a posição; sendo avaliado; avaliado, com o resultado; ou aguardando a próxima validação
        geral), no grupo de curso e período, na ordem dos grupos (o período mais recente primeiro)."""
        ofertas = self.disciplinas.do_professor(email) if self.disciplinas else []
        execucoes = historico.listar(self.cfg.historico_dir)
        ultima = execucoes[0] if execucoes else None
        linhas = {l.get('Arquivo'): l for l in csvsaida.ler_csv(ultima.csv_path)} if ultima else {}
        estado = self.validador.andamento.resumo()
        fila = self.validador.fila()
        planos = []
        for oferta in ofertas:
            nome = oferta['arquivo']
            ident = self.disciplinas.identificacao(oferta)
            chave, titulo, ordem = identificacao.grupo_curso_periodo(ident)
            item = {'nome': nome, 'oferta_id': oferta['id'], 'disciplina': _titulo_disciplina(oferta),
                    'componente': _descricao(ident), 'docentes': self.disciplinas.nomes(oferta['docentes']),
                    'grupo': chave, 'grupo_titulo': titulo, 'ordem': ordem, 'fase': oferta['fase'],
                    'enviado_em': oferta['enviado_em'], 'aviso': oferta['aviso'], 'tem_plano': self.existe(nome)}
            if not item['tem_plano']:
                item['situacao'] = 'sem_plano'
            elif nome in fila:
                item.update(situacao='na_fila', posicao=fila.index(nome) + 1)
            elif estado['rodando'] and nome in (estado['atual'], estado['unico']):
                item['situacao'] = 'validando'
            else:
                det = detalhes.ler(ultima.detalhes_dir, nome) if ultima and nome in linhas else None
                # o resultado só vale se for do PDF atual, validado depois do envio
                atual = det and det.get('validado_em', '') >= (oferta['enviado_em'] or '')
                linha = linhas.get(nome)
                if atual:
                    item.update(situacao='avaliado', status=linha.get('Status Geral', ''),
                                obs=linha.get('Observação Geral', ''),
                                problemas=[r for r, _ in csvsaida.CAMPOS_COLUNA if linha.get(r) != 'OK'])
                else:
                    item['situacao'] = 'aguardando'
            planos.append(item)
        planos.sort(key=lambda p: (p['ordem'], p['grupo_titulo'], p['fase'] or 99, p['disciplina'], p['nome']))
        return planos


def _titulo_disciplina(oferta):
    return oferta['nome'] + (f" (Turma {oferta['turma']})" if oferta['turma'] else '')


def _descricao(ident):
    """'CCC0723 · Desenvolvimento Web I · Turma 01', ou vazio sem identificação."""
    if not ident:
        return ''
    return ' · '.join([ident['codigo'], ident['disciplina']] + (['Turma ' + ident['turma']] if ident['turma'] else []))


def _aviso(texto, oferta, nomes_docentes):
    """Avisos sobre o PDF enviado para a disciplina: código ou período diferentes dos da disciplina, ou
    docente do PDF que não é nenhum dos docentes dela. O plano é aceito mesmo assim ('' sem aviso)."""
    avisos = []
    ident = identificacao.extrair(texto)
    if ident:
        codigo_pdf = ident['codigo'].split('-')[0]
        if oferta['codigo'] and codigo_pdf != oferta['codigo']:
            avisos.append(f"o PDF é de {codigo_pdf} ({ident['disciplina']}), e a disciplina é {oferta['codigo']}")
        if ident['periodo'] and ident['periodo'] != oferta['periodo']:
            avisos.append(f"o PDF é do período {ident['periodo']}, e a disciplina é de {oferta['periodo']}")
    motivo = _motivo_docente(texto, nomes_docentes)
    if motivo:
        avisos.append(motivo)
    return ('Confira o plano: ' + '; '.join(avisos) + '.') if avisos else ''


def _motivo_docente(texto, nomes_docentes):
    """Docentes do PDF que não são nenhum dos docentes da disciplina (pelo nome do cadastro, ou parecido:
    identificacao.nomes_parecidos), ou None. Sem o bloco de docentes no PDF, ou sem nomes no cadastro, não
    há o que conferir."""
    if isinstance(nomes_docentes, str):
        nomes_docentes = [nomes_docentes]
    nomes_docentes = [n for n in nomes_docentes if n]
    docentes = identificacao.docentes(texto)
    if not docentes or not nomes_docentes:
        return None
    if any(identificacao.nomes_parecidos(n, d) for n in nomes_docentes for d in docentes):
        return None
    return f'o docente do PDF é {", ".join(docentes)}, e não {" ou ".join(nomes_docentes)}'


def _tamanho(arquivo):
    arquivo.stream.seek(0, os.SEEK_END)
    tamanho = arquivo.stream.tell()
    arquivo.stream.seek(0)
    return tamanho
