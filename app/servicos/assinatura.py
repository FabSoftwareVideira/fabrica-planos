import glob
import io
import logging
import os
import re
import unicodedata
from collections import Counter

# No topo (e não dentro das funções): sem o pyHanko instalado, o app nem sobe, em vez de falhar só no envio
from asn1crypto import cms, pem, x509
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.diff_analysis import ModificationLevel
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.sign.validation.settings import KeyUsageConstraints
from pyhanko.sign.validation.status import SignatureCoverageLevel
from pyhanko_certvalidator import ValidationContext

from ..armazenamento import assinaturas, donos
from ..avaliacao import identificacao
from ..avaliacao.extrator import PdfIlegivel, extrair_texto

log = logging.getLogger(__name__)

# Assinatura do plano pelo professor, com a assinatura eletrônica do gov.br, depois que a coordenação, o
# NDE ou o NDB aprovou o plano na revisão. Por enquanto o professor assina o PDF em assinador.iti.br e
# envia de volta o arquivo assinado; aqui ele é conferido (`verificar`) e guardado ao lado do original.
# Quando houver as credenciais da API de Assinatura do gov.br (ITI), o PDF assinado pela API passa pelo
# mesmo `Assinaturas.registrar`: só muda de onde ele vem.

ASSINADOR = 'https://assinador.iti.br'

# Palavras que o assinador pode acrescentar ao PDF (o carimbo "Documento assinado digitalmente ...").
# Mais que isso deixa de ser o mesmo plano.
PALAVRAS_EXTRAS = 60

# Partículas que não contam ao comparar nomes ("Maria da Silva" = "MARIA SILVA")
PARTICULAS = {'DA', 'DAS', 'DE', 'DO', 'DOS', 'E'}


class AssinaturaInvalida(Exception):
    """O PDF enviado não serve como plano assinado; a mensagem diz por quê, para o professor."""


class NaoLiberado(Exception):
    """O plano ainda não pode ser assinado (não é de quem pediu ou não foi aprovado na revisão)."""


# Certificados das autoridades aceitas ------------------------------------------------------------------

def carregar_raizes(pasta):
    """Certificados aceitos como âncora (a cadeia do gov.br, Cadeia_GovBr-der.p7b do ITI, e as que mais
    forem postas na pasta): arquivos .crt, .cer, .pem ou .der (PEM ou DER) e pacotes .p7b/.p7c. Raiz e
    intermediárias podem vir juntas: assinaturas emitidas abaixo de qualquer uma delas são aceitas."""
    raizes = []
    for caminho in sorted(glob.glob(os.path.join(pasta, '*'))):
        extensao = os.path.splitext(caminho)[1].lower()
        if extensao not in ('.crt', '.cer', '.pem', '.der', '.p7b', '.p7c'):
            continue
        with open(caminho, 'rb') as arq:
            dados = arq.read()
        try:
            blocos = [b for _, _, b in pem.unarmor(dados, multiple=True)] if pem.detect(dados) else [dados]
            for bloco in blocos:
                if extensao in ('.p7b', '.p7c'):
                    certs = cms.ContentInfo.load(bloco)['content']['certificates']
                    raizes += [c.chosen for c in certs if c.name == 'certificate']
                else:
                    raizes.append(x509.Certificate.load(bloco))
        except (ValueError, KeyError, TypeError):
            log.warning('Certificado ilegível ignorado: %s', caminho)
    return raizes


# Conferência do PDF assinado ---------------------------------------------------------------------------

def verificar(pdf_assinado, pdf_original, raizes):
    """Confere o PDF assinado (bytes) contra o plano aprovado (bytes). Devolve {'signatario', 'cpf',
    'assinado_em'} ou levanta AssinaturaInvalida.

    Exige: uma assinatura digital íntegra, de um certificado emitido por uma das `raizes`, cobrindo o
    arquivo inteiro (nada mudou depois de assinar); e que o conteúdo seja o do plano aprovado: o original
    sem mudanças antes da assinatura (o caso do assinador do gov.br, que acrescenta ao final do arquivo)
    ou, se o PDF foi regravado, o mesmo texto em cada página, admitindo só o carimbo da assinatura.
    """
    if not raizes:
        raise AssinaturaInvalida('A conferência de assinaturas ainda não foi configurada no servidor; '
                                 'avise a administração.')
    try:
        leitor = PdfFileReader(io.BytesIO(pdf_assinado), strict=False)
        assinaturas_pdf = leitor.embedded_regular_signatures
    except Exception as erro:  # o leitor levanta vários tipos de erro para arquivos quebrados
        raise AssinaturaInvalida('O arquivo não pôde ser aberto como PDF.') from erro
    if not assinaturas_pdf:
        raise AssinaturaInvalida(f'O PDF não tem assinatura digital. Assine-o em {ASSINADOR} e envie o '
                                 'arquivo que o assinador devolve.')
    assinatura = assinaturas_pdf[-1]  # a última cobre todas as anteriores
    momento = assinatura.self_reported_timestamp
    # Validado na data da assinatura: os certificados do gov.br valem por pouco tempo.
    contexto = ValidationContext(trust_roots=raizes, moment=momento, best_signature_time=momento,
                                 allow_fetching=False)
    uso = KeyUsageConstraints(key_usage={'digital_signature', 'non_repudiation'}, match_all_key_usages=False)
    try:
        status = validate_pdf_signature(assinatura, contexto, key_usage_settings=uso)
    except Exception as erro:  # estrutura de assinatura quebrada ou desconhecida
        log.info('Assinatura ilegível: %s', erro)
        raise AssinaturaInvalida('A assinatura do PDF não pôde ser lida.') from erro
    if not status.intact or not status.valid:
        raise AssinaturaInvalida('A assinatura não confere: o PDF foi alterado depois de assinado.')
    if not status.trusted:
        raise AssinaturaInvalida(f'A assinatura não é do gov.br. Assine o plano em {ASSINADOR}, com a sua '
                                 'conta gov.br.')
    inteira = (status.coverage == SignatureCoverageLevel.ENTIRE_FILE or (
        status.coverage == SignatureCoverageLevel.ENTIRE_REVISION
        and status.modification_level in (ModificationLevel.NONE, ModificationLevel.LTA_UPDATES)))
    if not inteira or not status.docmdp_ok:
        raise AssinaturaInvalida('O PDF foi alterado depois de assinado. Envie o arquivo exatamente como o '
                                 'assinador o devolveu.')
    if not mesmo_conteudo(pdf_assinado, pdf_original):
        raise AssinaturaInvalida('O PDF assinado não é o plano aprovado. Baixe o PDF do plano em "Meus planos", '
                                 'assine esse arquivo e envie o resultado.')
    nome, cpf = signatario(status.signing_cert)
    return {'signatario': nome, 'cpf': cpf, 'assinado_em': momento.astimezone().isoformat(timespec='seconds') if momento else ''}


def signatario(certificado):
    """(nome, CPF) do titular do certificado. Nos certificados do gov.br o nome comum é 'NOME:CPF'."""
    nome = certificado.subject.native.get('common_name', '') or ''
    if isinstance(nome, list):
        nome = nome[0]
    nome, _, resto = nome.partition(':')
    cpf = re.sub(r'\D', '', resto)
    return ' '.join(nome.split()), cpf if len(cpf) == 11 else ''


def mesmo_conteudo(pdf_assinado, pdf_original):
    if pdf_assinado.startswith(pdf_original):  # assinatura acrescentada ao final, original intacto
        return True
    original, assinado = _palavras_por_pagina(pdf_original), _palavras_por_pagina(pdf_assinado)
    if original is None or assinado is None or len(original) != len(assinado):
        return False
    extras = 0
    for antes, depois in zip(original, assinado):
        if antes - depois:  # alguma palavra do plano sumiu
            return False
        extras += sum((depois - antes).values())
    return extras <= PALAVRAS_EXTRAS


def _palavras_por_pagina(pdf):
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            return [Counter((pagina.extract_text() or '').split()) for pagina in doc.pages]
    except Exception:  # PDF que o pdfplumber não abre: não dá para comparar
        return None


def _partes_do_nome(nome):
    sem_acento = unicodedata.normalize('NFKD', nome or '').encode('ascii', 'ignore').decode()
    return {p for p in re.findall(r'[A-Z]+', sem_acento.upper()) if p not in PARTICULAS}


def mesma_pessoa(nome_certificado, nome):
    """Os nomes batem quando um contém todas as partes do outro (o nome completo do gov.br contra o do
    plano ou o da conta Google, que pode omitir sobrenomes), com pelo menos duas partes em comum."""
    a, b = _partes_do_nome(nome_certificado), _partes_do_nome(nome)
    return len(a & b) >= 2 and (a <= b or b <= a)


# Serviço ----------------------------------------------------------------------------------------------

class Assinaturas:
    """Planos assinados pelos professores. Um plano pode ser assinado por quem o enviou ("Meus planos")
    depois de aprovado na revisão da coordenação/NDE/NDB. A assinatura vale enquanto aquela aprovação
    valer: um PDF novo do plano, ou a aprovação desfeita ou trocada por outro parecer, pede outra assinatura."""

    def __init__(self, cfg, revisao):
        self.cfg = cfg
        self.revisao = revisao
        self._raizes = None

    @property
    def raizes(self):
        if self._raizes is None:
            self._raizes = carregar_raizes(self.cfg.certificados_dir)
            log.info('Assinaturas: %d certificado(s) raiz aceito(s)', len(self._raizes))
        return self._raizes

    def aprovacao(self, nome):
        """A revisão vigente do plano, se aprovou; senão None."""
        r = self.revisao.vigente(nome)
        return r if r and r['status'] == 'OK' else None

    def liberado(self, nome, email):
        dono = donos.ler(self.cfg.resultados_dir).get(nome, {}).get('email')
        return bool(dono) and dono == email and self.aprovacao(nome) is not None

    def vigente(self, nome):
        """Registro da assinatura do plano, se ainda vale (mesmo PDF e aprovação de quando foi assinado)."""
        registro = assinaturas.ler(self.cfg.resultados_dir).get(nome)
        aprovacao = self.aprovacao(nome)
        if not registro or not aprovacao or registro.get('versao') != aprovacao['assinatura']:
            return None
        if not os.path.isfile(assinaturas.caminho_pdf(self.cfg.resultados_dir, nome)):
            return None
        return registro

    def vigentes(self, nomes):
        return {n: r for n in nomes if (r := self.vigente(n))}

    def registrar(self, nome, email, nome_usuario, pdf_assinado):
        """Confere e guarda o PDF assinado (bytes) do plano `nome`. Devolve o registro gravado."""
        if not self.liberado(nome, email):
            raise NaoLiberado
        aprovacao = self.aprovacao(nome)
        original_path = os.path.join(self.cfg.planos_dir, nome)
        with open(original_path, 'rb') as arq:
            original = arq.read()
        dados = verificar(pdf_assinado, original, self.raizes)
        # Quem assinou precisa ser um dos docentes do plano ou, sem eles no texto, o dono da conta.
        try:
            docentes = identificacao.docentes(extrair_texto(original_path))
        except PdfIlegivel:
            docentes = []
        conferir = docentes or [n for n in [nome_usuario] if n]
        if conferir and not any(mesma_pessoa(dados['signatario'], n) for n in conferir):
            raise AssinaturaInvalida(f'O PDF foi assinado por {dados["signatario"] or "outra pessoa"}, que não é '
                                     'docente deste plano. Assine com a sua conta gov.br.')
        registro = assinaturas.gravar(self.cfg.resultados_dir, nome, pdf_assinado, {
            'email': email, 'signatario': dados['signatario'], 'assinado_em': dados['assinado_em'],
            'versao': aprovacao['assinatura'], 'aprovado_em': aprovacao['revisado_em'],
        })
        log.info('Plano assinado (%s): %s, por %s', email, nome, dados['signatario'])
        return registro

    def caminho(self, nome):
        """PDF assinado do plano, se a assinatura ainda vale; senão None."""
        return assinaturas.caminho_pdf(self.cfg.resultados_dir, nome) if self.vigente(nome) else None


def resumo(registro):
    if not registro:
        return None
    return {'signatario': registro['signatario'], 'assinado_em': registro['assinado_em'],
            'enviado_em': registro['enviado_em']}
