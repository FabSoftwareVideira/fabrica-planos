import logging
import re

from ..armazenamento import ppc
from ..armazenamento.ofertas import PERIODO

log = logging.getLogger(__name__)

EMAIL = re.compile(r'^[^@\s]+@[^@\s]+$')


class Invalido(Exception):
    """Pedido com dado inválido; a mensagem diz o que corrigir."""


class ComPlano(Exception):
    """A oferta já tem plano enviado e não pode ser removida."""


class Disciplinas:
    """Grade de disciplinas de cada semestre, montada pela coordenação do curso a partir da matriz do PPC.

    A coordenação escolhe as fases do semestre (geralmente as pares num semestre e as ímpares no outro), tira
    ou acrescenta disciplinas, renomeia (as optativas, principalmente), abre outra turma e vincula os
    docentes de cada uma pelo e-mail institucional. O professor só envia plano para as disciplinas em que é
    docente, e o plano fica ligado à oferta: é dela que vêm curso, período, disciplina e docentes.
    """

    def __init__(self, cfg, ofertas, usuarios):
        self.cfg = cfg
        self.ofertas = ofertas
        self.usuarios = usuarios

    # Quem gerencia ---------------------------------------------------------------------------------

    def cursos(self):
        """{sigla: nome} dos cursos com matriz ou ofertas."""
        siglas = set(ppc.CURSOS) | set(self.ofertas.cursos())
        return {s: ppc.CURSOS.get(s, s) for s in sorted(siglas)}

    def cursos_gerenciaveis(self, email, admin):
        """Cursos cuja grade a pessoa monta: todos, para o administrador; os que coordena, para os demais."""
        if admin or not self.cfg.exigir_login:
            return self.cursos()
        coordena = {c for c, papel in self.usuarios.papeis(email) if papel == 'coordenador'}
        return {s: n for s, n in self.cursos().items() if s in coordena}

    def pode_gerenciar(self, email, admin, curso):
        return curso in self.cursos_gerenciaveis(email, admin)

    # Identificação do plano pela oferta ------------------------------------------------------------

    def identificacao(self, oferta):
        """Dados de identificação do plano no formato de avaliacao/identificacao.py: extrair(), para o
        painel agrupar e a revisão saber o curso. Vêm da oferta, não do texto do PDF."""
        if not oferta:
            return None
        ano, _, semestre = oferta['periodo'].partition('.')
        return {
            'codigo': oferta['codigo'], 'disciplina': oferta['nome'], 'carga_horaria': oferta['carga_horaria'],
            'turma': oferta['turma'], 'sigla_curso': oferta['curso'],
            'curso': ppc.CURSOS.get(oferta['curso'], oferta['curso']), 'ano': ano,
            'semestre': int(semestre) if semestre else None, 'periodo': oferta['periodo'],
            'oferta': 'semestral' if semestre else 'anual', 'fase': oferta['fase'], 'oferta_id': oferta['id'],
        }

    def do_arquivo(self, arquivo):
        return self.ofertas.do_arquivo(arquivo)

    def docentes_do_arquivo(self, arquivo):
        """E-mails dos docentes da oferta dona do plano ([] se o PDF não é de nenhuma oferta)."""
        oferta = self.ofertas.do_arquivo(arquivo)
        return oferta['docentes'] if oferta else []

    def nomes(self, emails):
        """[{'email', 'nome', 'cadastrado'}]: o nome vem do cadastro de quem já entrou no sistema."""
        saida = []
        for e in emails:
            u = self.usuarios.obter(e)
            saida.append({'email': e, 'nome': (u or {}).get('nome') or '', 'cadastrado': u is not None})
        return saida

    # Semestre -----------------------------------------------------------------------------------------

    def periodos(self, curso):
        return self.ofertas.periodos(curso)

    def semestre(self, curso, periodo):
        """Ofertas do semestre agrupadas por fase ([(fase ou None, [ofertas])]), com os docentes nomeados."""
        grupos = {}
        for o in self.ofertas.listar(curso=curso, periodo=periodo):
            o['docentes_info'] = self.nomes(o['docentes'])
            grupos.setdefault(o['fase'], []).append(o)
        return sorted(grupos.items(), key=lambda par: (par[0] is None, par[0] or 0))

    def matriz_por_fase(self, curso):
        fases = {}
        for c in self.ofertas.matriz(curso):
            fases.setdefault(c['fase'], []).append(c)
        return sorted(fases.items())

    def _validar(self, curso, periodo):
        if curso not in self.cursos():
            raise Invalido('Curso desconhecido.')
        if not PERIODO.match(periodo or ''):
            raise Invalido('Período inválido: use ano e semestre, como 2026.2.')

    def adicionar_fases(self, curso, periodo, fases, email):
        """Abre no semestre as disciplinas da matriz dessas fases (as que ainda não estão nele). Devolve
        quantas entraram."""
        self._validar(curso, periodo)
        fases = {int(f) for f in fases}
        if not fases:
            raise Invalido('Escolha pelo menos uma fase.')
        ja = {o['componente_id'] for o in self.ofertas.listar(curso=curso, periodo=periodo)}
        novas = 0
        for c in self.ofertas.matriz(curso):
            if c['fase'] in fases and c['id'] not in ja:
                self.ofertas.criar(curso, periodo, c['nome'], c['codigo'], c['carga_horaria'], c['fase'],
                                   componente_id=c['id'], criado_por=email)
                novas += 1
        log.info('Disciplinas (%s): %d disciplina(s) das fases %s em %s %s', email, novas, sorted(fases), curso, periodo)
        return novas

    def adicionar_componente(self, curso, periodo, componente_id, email):
        """Abre no semestre uma disciplina da matriz (de qualquer fase)."""
        self._validar(curso, periodo)
        c = self.ofertas.componente(componente_id)
        if not c or c['curso'] != curso:
            raise Invalido('Disciplina não encontrada na matriz do curso.')
        turma = self._proxima_turma(curso, periodo, c['codigo'], c['nome'])
        return self.ofertas.criar(curso, periodo, c['nome'], c['codigo'], c['carga_horaria'], c['fase'], turma,
                                  componente_id=c['id'], criado_por=email)

    def adicionar_avulsa(self, curso, periodo, nome, codigo, carga_horaria, fase, email):
        """Disciplina que não está na matriz, só neste semestre."""
        self._validar(curso, periodo)
        nome, codigo = _texto(nome, 200), _texto(codigo, 20).upper()
        if not nome:
            raise Invalido('Informe o nome da disciplina.')
        return self.ofertas.criar(curso, periodo, nome, codigo, _inteiro(carga_horaria), _fase(fase),
                                  self._proxima_turma(curso, periodo, codigo, nome), criado_por=email)

    def nova_turma(self, id_, email):
        """Outra turma da mesma disciplina (outra oferta, com o seu plano), sem docentes ainda."""
        o = self._oferta(id_)
        return self.ofertas.criar(o['curso'], o['periodo'], o['nome'], o['codigo'], o['carga_horaria'], o['fase'],
                                  self._proxima_turma(o['curso'], o['periodo'], o['codigo'], o['nome']),
                                  componente_id=o['componente_id'], criado_por=email)

    def _proxima_turma(self, curso, periodo, codigo, nome):
        usadas = {o['turma'] for o in self.ofertas.listar(curso=curso, periodo=periodo)
                  if o['codigo'] == codigo and o['nome'] == nome}
        n = 1
        while f'{n:02d}' in usadas:
            n += 1
        return f'{n:02d}'

    def alterar(self, id_, nome, codigo, carga_horaria, turma):
        """Renomeia (só nesta oferta; a matriz fica como está) e ajusta código, carga e turma."""
        self._oferta(id_)
        nome, turma = _texto(nome, 200), _texto(turma, 10)
        if not nome:
            raise Invalido('Informe o nome da disciplina.')
        if not re.fullmatch(r'[A-Za-z0-9]{1,10}', turma):
            raise Invalido('Turma inválida: use letras e números, como 01.')
        self.ofertas.alterar(id_, nome=nome, codigo=_texto(codigo, 20).upper(), carga_horaria=_inteiro(carga_horaria),
                             turma=turma)

    def remover(self, id_, tem_plano):
        o = self._oferta(id_)
        if tem_plano(o['arquivo']):
            raise ComPlano
        self.ofertas.remover(id_)

    def definir_docentes(self, id_, texto):
        """Docentes da oferta, pelos e-mails (separados por vírgula, espaço ou linha). Só e-mails do domínio
        da instituição; quem ainda não entrou no sistema vê a disciplina no primeiro acesso."""
        self._oferta(id_)
        emails = [e.strip().lower() for e in re.split(r'[\s,;]+', texto or '') if e.strip()]
        dominio = '@' + self.cfg.email_dominio
        invalidos = [e for e in emails if not EMAIL.match(e) or not e.endswith(dominio)]
        if invalidos:
            raise Invalido(f'E-mail inválido (use o institucional, {dominio}): {", ".join(invalidos)}')
        self.ofertas.definir_docentes(id_, emails)
        return emails

    def _oferta(self, id_):
        o = self.ofertas.obter(id_)
        if not o:
            raise Invalido('Disciplina não encontrada.')
        return o

    def oferta(self, id_):
        return self.ofertas.obter(id_)

    def do_professor(self, email):
        return self.ofertas.listar(docente=email)


def _texto(valor, limite):
    return ' '.join(str(valor or '').split())[:limite]


def _inteiro(valor):
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def _fase(valor):
    n = _inteiro(valor)
    return n if 1 <= n <= 20 else None
