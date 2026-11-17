import os
import unicodedata

from ..armazenamento import assinaturas as registro_assinaturas, ppc

# Área de transparência (rotas/transparencia.py): os planos assinados, públicos, para qualquer um consultar por
# período, curso, fase, docente ou disciplina. Cada plano tem uma URL fixa (/transparencia/<id da oferta>), que
# mostra sempre a versão assinada vigente; cada versão assinada tem também a sua (/transparencia/<id>/v<n>).
#
# Publicada é a última versão assinada do plano: a atual, se a assinatura dela vale (Assinaturas.vigente), ou,
# enquanto o professor atualiza o plano e a versão nova ainda não foi assinada, a última assinada do histórico
# (marcada "em atualização"). Só entram as disciplinas de planejamentos publicados. Os e-mails dos docentes
# nunca aparecem: só os nomes do cadastro (ou, sem cadastro, o nome de quem assinou).


def _norm(texto):
    return unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().lower()


class Transparencia:
    def __init__(self, cfg, ofertas, usuarios, assinaturas, versoes):
        self.cfg = cfg
        self.ofertas = ofertas
        self.usuarios = usuarios
        self.assinaturas = assinaturas
        self.versoes = versoes

    # Publicações ---------------------------------------------------------------------------------------

    def _assinadas(self, oferta, vigente, arquivadas, ultimo):
        """Versões assinadas do plano, da mais recente para a mais antiga: [{'numero', 'signatario',
        'assinado_em', 'atual'}]. `atual`: é a versão que está na pasta de planos (não a do histórico)."""
        saida = []
        if vigente:
            saida.append({'numero': ultimo + 1, 'signatario': vigente.get('signatario', ''),
                          # Sem a data no certificado, a do registro da assinatura no sistema
                          'assinado_em': vigente.get('assinado_em') or vigente.get('enviado_em', ''), 'atual': True})
        for v in arquivadas:
            if v.get('tem_assinado') and os.path.isfile(self.versoes.caminho(oferta['arquivo'], v['numero'], True)):
                saida.append({'numero': v['numero'], 'signatario': v.get('signatario') or '',
                              'assinado_em': v.get('assinado_em') or '', 'atual': False})
        return saida

    def _publicacao(self, oferta, assinadas, ultimo):
        """O plano como aparece na transparência, ou None se ele não tem versão assinada."""
        if not assinadas:
            return None
        publicada = assinadas[0]
        nomes = [n for n in (self._nome(e) for e in oferta['docentes']) if n] or [publicada['signatario']]
        return {
            'id': oferta['id'], 'disciplina': oferta['nome'], 'codigo': oferta['codigo'], 'turma': oferta['turma'],
            'fase': oferta['fase'], 'carga_horaria': oferta['carga_horaria'], 'periodo': oferta['periodo'],
            'curso': oferta['curso'], 'curso_nome': ppc.CURSOS.get(oferta['curso'], oferta['curso']),
            'docentes': nomes, 'versao': publicada['numero'], 'signatario': publicada['signatario'],
            'assinado_em': publicada['assinado_em'],
            # Há uma versão mais nova que a publicada, ainda sem assinatura
            'em_atualizacao': ultimo + 1 > publicada['numero'] and self._tem_plano(oferta),
            'assinadas': assinadas,
        }

    def _tem_plano(self, oferta):
        return os.path.isfile(os.path.join(self.cfg.planos_dir, oferta['arquivo']))

    def _nome(self, email):
        if email not in self._nomes:
            self._nomes[email] = ((self.usuarios.obter(email) or {}).get('nome') or '').strip()
        return self._nomes[email]

    def _publicacoes(self, ofertas):
        self._nomes = {}
        publicados = self.ofertas.publicados()
        ofertas = [o for o in ofertas if (o['curso'], o['periodo']) in publicados]
        arquivos = [o['arquivo'] for o in ofertas]
        arquivadas = self.versoes.de_varios(arquivos) if self.versoes else {}
        ultimos = self.versoes.ultimos_numeros(arquivos) if self.versoes else {}
        registros = registro_assinaturas.ler(self.cfg.resultados_dir)
        saida = []
        for o in ofertas:
            ultimo = ultimos.get(o['arquivo'], 0)
            vigente = self.assinaturas.vigente(o['arquivo']) if o['arquivo'] in registros else None
            publicacao = self._publicacao(o, self._assinadas(o, vigente, arquivadas.get(o['arquivo'], []), ultimo),
                                          ultimo)
            if publicacao:
                saida.append(publicacao)
        return saida

    # Consulta ------------------------------------------------------------------------------------------

    def listar(self, periodo='', curso='', fase='', docente='', busca=''):
        """Planos publicados com os filtros, e as opções de cada filtro (dos planos publicados)."""
        todos = self._publicacoes(self.ofertas.listar())
        opcoes = {
            'periodos': sorted({p['periodo'] for p in todos}, reverse=True),
            'cursos': sorted({(p['curso'], p['curso_nome']) for p in todos}, key=lambda c: c[1]),
            'fases': sorted({p['fase'] for p in todos if p['fase']}),
            'docentes': sorted({d for p in todos for d in p['docentes']}, key=_norm),
        }
        planos = todos
        if periodo:
            planos = [p for p in planos if p['periodo'] == periodo]
        if curso:
            planos = [p for p in planos if p['curso'] == curso]
        if fase:
            planos = [p for p in planos if str(p['fase'] or '') == str(fase)]
        if docente:
            planos = [p for p in planos if any(_norm(docente) in _norm(d) for d in p['docentes'])]
        if busca:
            planos = [p for p in planos if _norm(busca) in _norm(f"{p['disciplina']} {p['codigo']}")]
        return planos, opcoes

    def plano(self, oferta_id):
        """O plano publicado da oferta (com todas as versões assinadas), ou None."""
        oferta = self.ofertas.obter(oferta_id)
        if not oferta:
            return None
        publicados = self._publicacoes([oferta])
        return publicados[0] if publicados else None

    def caminho_pdf(self, plano, numero):
        """Arquivo do PDF assinado da versão `numero` do plano publicado, ou None."""
        versao = next((v for v in plano['assinadas'] if v['numero'] == numero), None)
        if not versao:
            return None
        arquivo = self.ofertas.obter(plano['id'])['arquivo']
        if versao['atual']:
            return registro_assinaturas.caminho_pdf(self.cfg.resultados_dir, arquivo)
        return self.versoes.caminho(arquivo, numero, True)
