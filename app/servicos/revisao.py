import logging
import os

from ..armazenamento import donos, historico
from ..armazenamento.usuarios import PAPEIS_CURSO

log = logging.getLogger(__name__)

# Parecer da revisão manual. O status do revisor passa a ser o oficial do plano (dashboard e "Meus planos").
STATUS_REVISAO = {'OK': 'Aprovado', 'PENDENTE': 'Ajustes necessários', 'REPROVADO': 'Reprovado'}


class Proibido(Exception):
    """Quem pediu não é da coordenação, do NDE ou do NDB do curso do plano."""


class Invalido(Exception):
    """Parecer incompleto (status desconhecido ou falta o comentário)."""


class Revisao:
    """Revisão manual da avaliação da IA por quem tem papel no curso do plano (coordenação, NDE ou NDB).

    Uma revisão vale enquanto o PDF for o mesmo que foi revisado: a assinatura (tamanho e data de
    modificação) é guardada junto e conferida a cada leitura, então um PDF novo com o mesmo nome,
    enviado pelo professor, pelo administrador ou copiado direto para a pasta, reabre a revisão.
    """

    def __init__(self, cfg, revisoes, usuarios):
        self.cfg = cfg
        self.revisoes = revisoes
        self.usuarios = usuarios

    def assinatura(self, nome):
        """Tamanho e data do PDF atual do plano: o da pasta de planos ou, sem ele, a cópia da validação."""
        caminhos = [os.path.join(self.cfg.planos_dir, nome)]
        execucoes = historico.listar(self.cfg.historico_dir)
        if execucoes:
            caminhos.append(os.path.join(execucoes[0].pdfs_dir, nome))
        for caminho in caminhos:
            try:
                info = os.stat(caminho)
            except OSError:
                continue
            return f'{info.st_size}-{int(info.st_mtime)}'
        return ''

    def vigentes(self):
        """{arquivo: revisão} das revisões que ainda valem (feitas sobre o PDF atual)."""
        return {nome: r for nome, r in self.revisoes.todas().items() if r['assinatura'] == self.assinatura(nome)}

    def vigente(self, nome):
        r = self.revisoes.obter(nome)
        return r if r and r['assinatura'] == self.assinatura(nome) else None

    def eh_autor(self, email, nome):
        """Quem enviou o plano (em "Meus planos" ou pela administração) não pode revisá-lo nem desfazer a
        revisão dele: o parecer fica com outro membro da coordenação, do NDE ou do NDB. Só com login exigido."""
        if not self.cfg.exigir_login or not email:
            return False
        return donos.ler(self.cfg.resultados_dir).get(nome, {}).get('email') == email

    def papel(self, email, ident, nome=None):
        """Rótulo do papel do usuário no curso do plano ('Coordenação', 'NDE'…), ou '' se não pode revisar.
        Sem login exigido (uso local), todo acesso pode revisar. Com `nome`, quem enviou aquele plano não o
        revisa (ver eh_autor)."""
        if not self.cfg.exigir_login:
            return 'Administração local'
        if not email or not ident:
            return ''
        if nome is not None and self.eh_autor(email, nome):
            return ''
        papeis = [p for curso, p in self.usuarios.papeis(email) if curso == ident['sigla_curso']]
        for chave in PAPEIS_CURSO:  # coordenação primeiro
            if chave in papeis:
                return PAPEIS_CURSO[chave]
        return ''

    def registrar(self, nome, email, nome_revisor, ident, status, comentario, status_ia):
        """Grava o parecer. O comentário é obrigatório quando o plano não é aprovado ou quando o parecer
        discorda da IA (o professor precisa saber o que mudar)."""
        papel = self.papel(email, ident, nome)
        if not papel:
            raise Proibido
        comentario = (comentario or '').strip()[:2000]
        if status not in STATUS_REVISAO:
            raise Invalido('Escolha o parecer.')
        if not comentario and (status != 'OK' or status != status_ia):
            raise Invalido('Explique no comentário o que precisa mudar ou por que o parecer difere da IA.')
        revisao = self.revisoes.salvar(nome, self.assinatura(nome), status, status_ia, comentario,
                                       (ident or {}).get('sigla_curso', ''), email, nome_revisor, papel)
        log.info('Revisão de %s por %s (%s): %s', nome, email, papel, status)
        return revisao

    def desfazer(self, nome, email, ident):
        if not self.papel(email, ident, nome):
            raise Proibido
        self.revisoes.remover(nome)
        log.info('Revisão de %s desfeita por %s', nome, email)


def resumo(revisao):
    """Dados da revisão para as páginas: parecer, quem revisou e quando."""
    if not revisao:
        return None
    return {
        'status': revisao['status'],
        'parecer': STATUS_REVISAO.get(revisao['status'], revisao['status']),
        'comentario': revisao['comentario'],
        'revisor': revisao['revisor_nome'] or revisao['revisor_email'],
        'papel': revisao['papel'],
        'revisado_em': revisao['revisado_em'],
        'concorda': revisao['status'] == revisao['status_ia'],
        'status_ia': revisao['status_ia'],
    }
