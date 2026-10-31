import json
import os
import re
import shutil
from datetime import datetime

# Resultado das validações: cada execução fica em resultados/historico/<id>/ com
#   meta.json                resumo (datas, modelo, contagens, erro)
#   validacao_planos.csv     resultado, no mesmo formato de sempre
#   detalhes/<arquivo>.json  texto extraído, prompt e resposta da IA por plano
#   pdfs/                    cópia dos PDFs validados
# Só a execução mais recente é mantida (ver podar): uma validação geral nova substitui a anterior, e a
# anterior só é apagada depois que a nova termina. O id é a data/hora de início (AAAAMMDD-HHMMSS), então
# a ordem alfabética é a cronológica.

META = 'meta.json'
CSV = 'validacao_planos.csv'
ID_VALIDO = re.compile(r'^\d{8}-\d{6}(-\d+)?$')


class Execucao:
    def __init__(self, raiz, id_):
        self.id = id_
        self.pasta = os.path.join(raiz, id_)

    @property
    def csv_path(self):
        return os.path.join(self.pasta, CSV)

    @property
    def detalhes_dir(self):
        return os.path.join(self.pasta, 'detalhes')

    @property
    def pdfs_dir(self):
        return os.path.join(self.pasta, 'pdfs')

    def pdfs(self):
        if not os.path.isdir(self.pdfs_dir):
            return []
        return sorted(os.listdir(self.pdfs_dir))

    def meta(self):
        try:
            with open(os.path.join(self.pasta, META), encoding='utf-8') as arq:
                return json.load(arq)
        except (FileNotFoundError, ValueError):
            return None


def criar(raiz, agora=None):
    base = (agora or datetime.now()).strftime('%Y%m%d-%H%M%S')
    id_, n = base, 1
    while os.path.exists(os.path.join(raiz, id_)):
        n += 1
        id_ = f'{base}-{n}'
    execucao = Execucao(raiz, id_)
    os.makedirs(execucao.pdfs_dir)
    return execucao


def guardar_pdf(execucao, origem):
    os.makedirs(execucao.pdfs_dir, exist_ok=True)  # a migrada da versão antiga não tem pdfs/
    shutil.copy2(origem, os.path.join(execucao.pdfs_dir, os.path.basename(origem)))


def contar(linhas):
    ok = sum(1 for l in linhas if l.get('Status Geral') == 'OK')
    pendentes = sum(1 for l in linhas if l.get('Status Geral') == 'PENDENTE')
    return {'ok': ok, 'pendentes': pendentes, 'problemas': len(linhas) - ok - pendentes}


def gravar_meta(execucao, meta):
    temporario = os.path.join(execucao.pasta, META + '.tmp')
    with open(temporario, 'w', encoding='utf-8') as arq:
        json.dump({'id': execucao.id, **meta}, arq, ensure_ascii=False, indent=1)
    os.replace(temporario, os.path.join(execucao.pasta, META))


def obter(raiz, id_):
    """A execução concluída com esse id, ou None (id inválido, inexistente ou ainda em andamento)."""
    if not id_ or not ID_VALIDO.match(id_):
        return None
    execucao = Execucao(raiz, id_)
    return execucao if execucao.meta() is not None else None


def listar(raiz):
    """Execuções concluídas, da mais recente para a mais antiga."""
    if not os.path.isdir(raiz):
        return []
    ids = sorted((n for n in os.listdir(raiz) if ID_VALIDO.match(n)), reverse=True)
    return [e for e in (obter(raiz, i) for i in ids) if e is not None]


def podar(raiz, manter=1):
    """Mantém as `manter` execuções mais recentes (só a atual, por padrão) e os PDFs só da mais recente;
    apaga sobras de execuções interrompidas (sem meta.json). Chamar só sem validação em andamento."""
    if not os.path.isdir(raiz):
        return
    concluidas = listar(raiz)
    validas = {e.id for e in concluidas[:manter]}
    for nome in os.listdir(raiz):
        if nome not in validas and os.path.isdir(os.path.join(raiz, nome)):
            shutil.rmtree(os.path.join(raiz, nome), ignore_errors=True)
    for execucao in concluidas[1:manter]:
        shutil.rmtree(execucao.pdfs_dir, ignore_errors=True)


def migrar_legado(raiz, csv_antigo, detalhes_antigo, ler_csv):
    """Leva o resultado da versão sem histórico (CSV e detalhes/ soltos em resultados/) para o histórico."""
    if listar(raiz) or not os.path.exists(csv_antigo):
        return
    data = datetime.fromtimestamp(os.path.getmtime(csv_antigo))
    execucao = criar(raiz, data)
    shutil.rmtree(execucao.pdfs_dir)  # os PDFs daquela validação não foram guardados
    shutil.copy2(csv_antigo, execucao.csv_path)
    if os.path.isdir(detalhes_antigo):
        shutil.move(detalhes_antigo, execucao.detalhes_dir)
    linhas = ler_csv(execucao.csv_path)
    gravar_meta(execucao, {
        'iniciado_em': None, 'finalizado_em': data.isoformat(timespec='seconds'), 'modelo': '',
        'total': len(linhas), 'processados': len(linhas), 'erro': '', **contar(linhas),
    })
