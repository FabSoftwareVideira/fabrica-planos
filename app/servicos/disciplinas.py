import logging
import re
from datetime import date, datetime

from ..armazenamento import ppc
from ..armazenamento.ofertas import PERIODO

log = logging.getLogger(__name__)

EMAIL = re.compile(r'^[^@\s]+@[^@\s]+$')


class Invalido(Exception):
    """Pedido com dado inválido; a mensagem diz o que corrigir."""


class ComPlano(Exception):
    """A oferta (ou o planejamento) já tem plano enviado e não pode ser removida."""


class JaExiste(Exception):
    """Já há um planejamento do curso para esse período."""


class Disciplinas:
    """Grade de disciplinas de cada período letivo, montada pela coordenação do curso a partir da matriz do PPC.

    Cada curso e período tem um planejamento, montado em etapas (rotas/disciplinas.py): o período (o próximo
    é sugerido, semestral ou anual conforme o curso), as fases (no semestral, geralmente as ímpares no 1º
    semestre e as pares no 2º), as disciplinas (renomear, outra turma, avulsas) e os docentes de cada uma,
    pelo e-mail institucional. Enquanto é rascunho, só a coordenação o vê; publicado, os docentes veem as
    disciplinas em "Meus planos" e enviam os planos. O plano fica ligado à oferta: é dela que vêm curso,
    período, disciplina e docentes.
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

    # Planejamento do período ----------------------------------------------------------------------

    def tipo(self, curso):
        return ppc.TIPOS.get(curso, 'semestral')

    def periodo_valido(self, curso, periodo):
        if self.tipo(curso) == 'anual':
            return bool(re.fullmatch(r'(19|20)\d{2}', periodo or ''))
        return bool(re.fullmatch(r'(19|20)\d{2}\.[12]', periodo or ''))

    def sugerir_periodo(self, curso, hoje=None):
        """O próximo período a planejar: no semestral, o próximo semestre (o 2º, durante o 1º; o 1º do ano
        seguinte, durante o 2º); no anual, o ano seguinte a partir de julho. Pula os já planejados."""
        hoje = hoje or date.today()
        existentes = {p['periodo'] for p in self.ofertas.planejamentos(curso)}
        if self.tipo(curso) == 'anual':
            ano = hoje.year + (1 if hoje.month >= 7 else 0)
            while str(ano) in existentes:
                ano += 1
            return str(ano)
        ano, semestre = (hoje.year, 2) if hoje.month <= 6 else (hoje.year + 1, 1)
        while f'{ano}.{semestre}' in existentes:
            ano, semestre = (ano, 2) if semestre == 1 else (ano + 1, 1)
        return f'{ano}.{semestre}'

    def fases_sugeridas(self, curso, periodo):
        """No semestral, as ímpares no 1º semestre e as pares no 2º; no anual, todas."""
        fases = [f for f, _ in self.matriz_por_fase(curso)]
        if self.tipo(curso) == 'anual' or '.' not in periodo:
            return fases
        impar = periodo.endswith('.1')
        return [f for f in fases if (f % 2 == 1) == impar]

    def planejamentos(self, curso):
        return self.ofertas.planejamentos(curso)

    def planejamento(self, curso, periodo):
        p = self.ofertas.planejamento(curso, periodo)
        if p:
            p['fases_lista'] = [int(f) for f in p['fases'].split(',') if f]
        return p

    def criar_planejamento(self, curso, periodo, email):
        """Começa o planejamento (rascunho) do período. JaExiste se já houver um."""
        self._validar(curso, periodo)
        if not self.ofertas.criar_planejamento(curso, periodo, email):
            raise JaExiste
        log.info('Disciplinas (%s): planejamento de %s %s iniciado', email, curso, periodo)

    def definir_fases(self, curso, periodo, fases, email):
        """Fases do período: abre as disciplinas da matriz das fases marcadas e tira as das desmarcadas
        (as que vieram da matriz e ainda não têm plano). Devolve (incluídas, retiradas, mantidas com plano)."""
        self._validar(curso, periodo)
        fases = {int(f) for f in fases}
        if not fases:
            raise Invalido('Escolha pelo menos uma fase.')
        incluidas = self.adicionar_fases(curso, periodo, fases, email)
        retiradas = mantidas = 0
        for o in self.ofertas.listar(curso=curso, periodo=periodo):
            if o['componente_id'] and o['fase'] not in fases:
                if o['enviado_em']:
                    mantidas += 1
                else:
                    self.ofertas.remover(o['id'])
                    retiradas += 1
        self.ofertas.alterar_planejamento(curso, periodo, fases=','.join(str(f) for f in sorted(fases)))
        return incluidas, retiradas, mantidas

    def definir_docentes_em_lote(self, curso, periodo, textos):
        """Docentes de várias disciplinas do período de uma vez ({id da oferta: texto com os e-mails}).
        Confere todos antes de gravar: com algum e-mail inválido, nada é gravado (Invalido diz quais)."""
        ofertas = {o['id']: o for o in self.ofertas.listar(curso=curso, periodo=periodo)}
        dominio = '@' + self.cfg.email_dominio
        listas, erros = {}, []
        for id_, texto in textos.items():
            if id_ not in ofertas:
                continue
            emails = _emails(texto)
            invalidos = [e for e in emails if not EMAIL.match(e) or not e.endswith(dominio)]
            if invalidos:
                erros.append(f"{ofertas[id_]['nome']}: {', '.join(invalidos)}")
            listas[id_] = emails
        if erros:
            raise Invalido(f'E-mail inválido (use o institucional, {dominio}) em ' + '; '.join(erros))
        for id_, emails in listas.items():
            if sorted(set(emails)) != ofertas[id_]['docentes']:
                self.ofertas.definir_docentes(id_, emails)
        return len(listas)

    def publicar(self, curso, periodo, email):
        """Libera o planejamento: os docentes passam a ver as disciplinas e a enviar os planos."""
        p = self.ofertas.planejamento(curso, periodo)
        if not p:
            raise Invalido('Planejamento não encontrado.')
        if not p['disciplinas']:
            raise Invalido('Inclua pelo menos uma disciplina antes de publicar.')
        self.ofertas.alterar_planejamento(curso, periodo, situacao='publicado', publicado_por=email,
                                          publicado_em=datetime.now().isoformat(timespec='seconds'))
        log.info('Disciplinas (%s): planejamento de %s %s publicado', email, curso, periodo)

    def voltar_a_rascunho(self, curso, periodo, email):
        """Tira o planejamento do ar (os docentes deixam de ver as disciplinas): só sem planos enviados."""
        p = self.ofertas.planejamento(curso, periodo)
        if not p:
            raise Invalido('Planejamento não encontrado.')
        if p['enviados']:
            raise ComPlano
        self.ofertas.alterar_planejamento(curso, periodo, situacao='rascunho', publicado_em=None, publicado_por=None)
        log.info('Disciplinas (%s): planejamento de %s %s de volta a rascunho', email, curso, periodo)

    def excluir_planejamento(self, curso, periodo, email):
        """Descarta o rascunho e as disciplinas dele (publicado ou com planos enviados, não)."""
        p = self.ofertas.planejamento(curso, periodo)
        if not p:
            raise Invalido('Planejamento não encontrado.')
        if p['situacao'] == 'publicado' or p['enviados']:
            raise ComPlano
        self.ofertas.excluir_planejamento(curso, periodo)
        log.info('Disciplinas (%s): rascunho de %s %s excluído', email, curso, periodo)

    def publicado(self, oferta):
        return bool(oferta) and (oferta['curso'], oferta['periodo']) in self.ofertas.publicados()

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

    def _garantir_planejamento(self, curso, periodo, email):
        """Disciplina incluída num período sem planejamento: ele começa como rascunho."""
        self._validar(curso, periodo)
        self.ofertas.criar_planejamento(curso, periodo, email)

    def _validar(self, curso, periodo):
        if curso not in self.cursos():
            raise Invalido('Curso desconhecido.')
        if not PERIODO.match(periodo or '') or not self.periodo_valido(curso, periodo):
            if self.tipo(curso) == 'anual':
                raise Invalido('Período inválido: este curso é anual; use o ano, como 2027.')
            raise Invalido('Período inválido: use ano e semestre, como 2027.1.')

    def adicionar_fases(self, curso, periodo, fases, email):
        """Abre no semestre as disciplinas da matriz dessas fases (as que ainda não estão nele). Devolve
        quantas entraram."""
        self._garantir_planejamento(curso, periodo, email)
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
        self._garantir_planejamento(curso, periodo, email)
        c = self.ofertas.componente(componente_id)
        if not c or c['curso'] != curso:
            raise Invalido('Disciplina não encontrada na matriz do curso.')
        turma = self._proxima_turma(curso, periodo, c['codigo'], c['nome'])
        return self.ofertas.criar(curso, periodo, c['nome'], c['codigo'], c['carga_horaria'], c['fase'], turma,
                                  componente_id=c['id'], criado_por=email)

    def adicionar_avulsa(self, curso, periodo, nome, codigo, carga_horaria, fase, email):
        """Disciplina que não está na matriz, só neste semestre."""
        self._garantir_planejamento(curso, periodo, email)
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
        emails = _emails(texto)
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
        """As disciplinas do professor nos planejamentos publicados (os rascunhos ele não vê)."""
        publicados = self.ofertas.publicados()
        return [o for o in self.ofertas.listar(docente=email) if (o['curso'], o['periodo']) in publicados]


def _emails(texto):
    return [e.strip().lower() for e in re.split(r'[\s,;]+', texto or '') if e.strip()]


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
