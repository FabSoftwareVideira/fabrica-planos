import json
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import PurePosixPath

import psycopg.conninfo

from ..banco import TABELAS

# Backup de tudo o que o app grava: os PDFs da pasta de planos, o conteúdo da pasta de resultados
# (JSONs, histórico das validações e PDFs assinados) e o PostgreSQL (usuários e revisões). Cada backup é um
# ZIP com:
#   manifesto.json           formato, data, origem e contagens
#   planos/...               cópia dos PDFs
#   resultados/...           cópia dos resultados
#   banco.sql                dump das tabelas do PostgreSQL (pg_dump; restaurado com psql)
#
# O backup automático roda todo dia na hora configurada (BACKUP_HORA) e mantém os últimos
# BACKUP_MANTER arquivos automáticos. Os backups manuais e os feitos antes de uma restauração não são
# apagados automaticamente. A restauração substitui os dados atuais e, antes disso, cria um backup do
# estado que será substituído. Backups antigos sem banco.sql restauram só os arquivos.

log = logging.getLogger(__name__)

FORMATO = 1
NOME = re.compile(r'^(?P<data>\d{8}-\d{6})-(?P<origem>automatico|manual|antes-restauracao)'
                  r'(?:-(?P<n>\d+))?\.zip$')
ROTULOS = {
    'automatico': 'Automático',
    'manual': 'Manual',
    'antes-restauracao': 'Antes de restaurar',
}
RAIZES = {'planos', 'resultados', 'manifesto.json', 'banco.sql'}
SUFIXOS_TEMPORARIOS = ('.tmp', '.enviando', '.parcial')


class BackupInvalido(Exception):
    """O arquivo não é um backup no formato esperado."""


class BackupOcupado(Exception):
    """Há uma validação, backup ou restauração em andamento."""


class Backup:
    def __init__(self, cfg, validador=None, banco=None):
        self.cfg = cfg
        self.validador = validador
        self.banco = banco
        self.dir = cfg.pasta_backups
        # BACKUPS_DIR apontando para a própria pasta de dados apagaria os backups na restauração.
        for dados in (cfg.planos_dir, cfg.resultados_dir):
            if os.path.normcase(os.path.abspath(self.dir)) == os.path.normcase(os.path.abspath(dados)):
                self.dir = os.path.join(cfg.resultados_dir, 'backups')
                log.error('BACKUPS_DIR não pode ser a pasta de dados (%s); usando %s', dados, self.dir)
                break
        self._estado = threading.Lock()
        self._em_andamento = False
        self._ultimo_erro = ''
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError:  # não impede o app de subir; o erro aparece ao tentar criar o backup
            log.warning('Pasta de backups indisponível: %s', self.dir, exc_info=True)

    @property
    def criando(self):
        with self._estado:
            return self._em_andamento

    @property
    def ultimo_erro(self):
        with self._estado:
            return self._ultimo_erro

    # Criação ------------------------------------------------------------------------------------

    def criar(self, origem='manual'):
        """Cria o backup agora e devolve a descrição dele. Levanta BackupOcupado se já houver um
        backup/restauração ou uma validação em andamento."""
        with self._estado:
            if self._em_andamento:
                raise BackupOcupado('Já existe um backup ou uma restauração em andamento')
            self._em_andamento = True
            self._ultimo_erro = ''
        try:
            return self._criar(origem)
        finally:
            with self._estado:
                self._em_andamento = False

    def iniciar(self, origem='manual'):
        """Começa o backup numa thread (para o POST da administração não esperar o ZIP). Devolve False
        se já houver outro em andamento."""
        with self._estado:
            if self._em_andamento:
                return False
            self._em_andamento = True
            self._ultimo_erro = ''
        threading.Thread(target=self._em_thread, args=(origem,), daemon=True).start()
        return True

    def _em_thread(self, origem):
        try:
            self._criar(origem)
        except Exception as erro:  # fica registrado para a tela de administração
            log.exception('Falha ao criar o backup %s', origem)
            with self._estado:
                self._ultimo_erro = str(erro) or erro.__class__.__name__
        finally:
            with self._estado:
                self._em_andamento = False

    def _criar(self, origem):
        if origem not in ROTULOS:
            raise ValueError(f'Origem de backup inválida: {origem}')
        if self.validador is None:
            return self._gravar(origem)
        # Com a trava do validador, nenhuma validação ou envio começa no meio do backup. Se uma já
        # estiver rodando, é melhor esperar: os arquivos do histórico estariam sendo escritos.
        with self.validador.trava:
            if self.validador.andamento.rodando:
                raise BackupOcupado('Há uma validação em andamento; tente de novo quando ela terminar')
            return self._gravar(origem)

    def _gravar(self, origem):
        os.makedirs(self.dir, exist_ok=True)
        agora = datetime.now()
        nome = self._nome(agora, origem)
        destino = os.path.join(self.dir, nome)
        parcial = destino + '.parcial'
        try:
            with zipfile.ZipFile(parcial, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                planos, bytes_planos = self._adicionar_pasta(z, self.cfg.planos_dir, 'planos')
                resultados, bytes_resultados = self._adicionar_pasta(z, self.cfg.resultados_dir, 'resultados')
                dump = self._dump()
                z.writestr('banco.sql', dump)
                manifesto = {
                    'formato': FORMATO,
                    'criado_em': agora.isoformat(timespec='seconds'),
                    'origem': origem,
                    'planos': {'arquivos': planos, 'bytes': bytes_planos},
                    'resultados': {'arquivos': resultados, 'bytes': bytes_resultados},
                    'banco': {'bytes': len(dump)},
                }
                z.writestr('manifesto.json', json.dumps(manifesto, ensure_ascii=False, indent=1))
            os.replace(parcial, destino)
        except Exception:
            try:
                os.remove(parcial)
            except OSError:
                pass
            raise
        self._podar()
        log.info('Backup criado (%s): %s (%d planos, %d arquivos de resultados)',
                 origem, nome, planos, resultados)
        return self._descrever(nome)

    def _nome(self, agora, origem):
        base = f'{agora:%Y%m%d-%H%M%S}-{origem}'
        nome = base + '.zip'
        n = 1
        while os.path.exists(os.path.join(self.dir, nome)):
            n += 1
            nome = f'{base}-{n}.zip'
        return nome

    def _adicionar_pasta(self, z, raiz, prefixo):
        """Acrescenta ao ZIP os arquivos de `raiz` (sem os temporários nem a própria pasta de backups)."""
        if not os.path.isdir(raiz):
            return 0, 0
        arquivos = bytes_ = 0
        for base, pastas, nomes in os.walk(raiz):
            pastas[:] = sorted(p for p in pastas if not self._ignorar(os.path.join(base, p)))
            for nome in sorted(nomes):
                caminho = os.path.join(base, nome)
                if self._ignorar(caminho):
                    continue
                arco = prefixo + '/' + os.path.relpath(caminho, raiz).replace(os.sep, '/')
                try:
                    z.write(caminho, arco)
                    arquivos += 1
                    bytes_ += os.stat(caminho).st_size
                except OSError:
                    log.warning('Arquivo fora do backup: %s', caminho, exc_info=True)
        return arquivos, bytes_

    # Banco de dados -----------------------------------------------------------------------------

    def _env_banco(self):
        """Variáveis PG* para o pg_dump/psql, para a senha não aparecer na linha de comando."""
        if self.banco is None:
            raise BackupInvalido('O banco de dados não está configurado')
        dados = psycopg.conninfo.conninfo_to_dict(self.banco.url)
        nomes = {'host': 'PGHOST', 'port': 'PGPORT', 'user': 'PGUSER', 'password': 'PGPASSWORD',
                 'dbname': 'PGDATABASE', 'sslmode': 'PGSSLMODE'}
        return {**os.environ, **{nomes[k]: str(v) for k, v in dados.items() if k in nomes}}

    def _executar(self, comando, **opcoes):
        try:
            return subprocess.run(comando, env=self._env_banco(), capture_output=True, check=True, timeout=600,
                                  **opcoes)
        except FileNotFoundError as erro:
            raise RuntimeError(f'{comando[0]} não encontrado (instale o postgresql-client)') from erro
        except subprocess.CalledProcessError as erro:
            detalhe = (erro.stderr or b'').decode('utf-8', 'replace').strip()
            raise RuntimeError(f'{comando[0]} falhou: {detalhe}') from erro

    def _dump(self):
        """SQL (bytes) que recria as tabelas do app, com os dados, no esquema em uso."""
        esquema = self.banco.esquema if self.banco else 'public'
        comando = ['pg_dump', '--clean', '--if-exists', '--no-owner', '--no-privileges']
        for tabela in TABELAS:
            comando += ['--table', f'{esquema}.{tabela}']
        return self._executar(comando).stdout

    def _restaurar_banco(self, arquivo):
        self._executar(['psql', '--quiet', '--single-transaction', '--set', 'ON_ERROR_STOP=1', '--file', arquivo])

    def _ignorar(self, caminho):
        nome = os.path.basename(caminho)
        if nome.endswith(SUFIXOS_TEMPORARIOS) or nome.endswith(('-wal', '-shm', '-journal')):
            return True
        return os.path.normcase(os.path.abspath(caminho)) == os.path.normcase(os.path.abspath(self.dir))

    def _podar(self):
        """Mantém só os últimos backups automáticos (BACKUP_MANTER). Os manuais e os de antes de
        restaurar ficam até serem excluídos pela administração."""
        manter = max(1, int(self.cfg.backup_manter))
        automaticos = [b for b in self.listar() if b['origem'] == 'automatico']
        for item in automaticos[manter:]:
            try:
                os.remove(os.path.join(self.dir, item['nome']))
                log.info('Backup automático antigo removido: %s', item['nome'])
            except OSError:
                log.warning('Não foi possível remover o backup antigo %s', item['nome'], exc_info=True)

    # Consulta -----------------------------------------------------------------------------------

    def listar(self):
        """Backups existentes, do mais recente para o mais antigo."""
        try:
            nomes = os.listdir(self.dir)
        except OSError:
            return []
        itens = [item for item in (self._descrever(nome) for nome in nomes) if item]
        itens.sort(key=lambda b: (b['data'], b['ordem']), reverse=True)
        return itens

    def _descrever(self, nome):
        achado = NOME.match(nome)
        if not achado:
            return None
        caminho = os.path.join(self.dir, nome)
        if not os.path.isfile(caminho):
            return None
        try:
            info = os.stat(caminho)
            data = datetime.strptime(achado.group('data'), '%Y%m%d-%H%M%S')
        except (OSError, ValueError):
            return None
        manifesto = self._manifesto(caminho)
        planos = manifesto.get('planos')
        resultados = manifesto.get('resultados')
        planos = planos if isinstance(planos, dict) else {}
        resultados = resultados if isinstance(resultados, dict) else {}
        return {
            'nome': nome,
            'data': data,
            'ordem': int(achado.group('n') or 0),
            'quando': data.strftime('%d/%m/%Y às %H:%M'),
            'origem': achado.group('origem'),
            'rotulo': ROTULOS.get(achado.group('origem'), achado.group('origem')),
            'bytes': info.st_size,
            'tamanho': _tamanho(info.st_size),
            'planos': planos.get('arquivos'),
            'resultados': resultados.get('arquivos'),
            'valido': manifesto.get('formato') == FORMATO,
        }

    def _manifesto(self, caminho):
        try:
            with zipfile.ZipFile(caminho) as z:
                manifesto = json.loads(z.read('manifesto.json'))
            return manifesto if isinstance(manifesto, dict) else {}
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            return {}

    def caminho(self, nome):
        """Caminho do backup, ou None se o nome não for de um backup existente."""
        if not nome or not NOME.match(nome):
            return None
        caminho = os.path.join(self.dir, nome)
        return caminho if os.path.isfile(caminho) else None

    def excluir(self, nome):
        if self.criando:
            return False
        caminho = self.caminho(nome)
        if not caminho:
            return False
        os.remove(caminho)
        log.info('Backup excluído: %s', nome)
        return True

    # Restauração --------------------------------------------------------------------------------

    def restaurar(self, nome):
        """Substitui os dados atuais pelo conteúdo do backup. Antes, cria um backup do estado atual
        (origem `antes-restauracao`). Levanta BackupInvalido ou BackupOcupado."""
        caminho = self.caminho(nome)
        if not caminho:
            raise BackupInvalido('Backup não encontrado')
        with self._estado:
            if self._em_andamento:
                raise BackupOcupado('Já existe um backup ou uma restauração em andamento')
            self._em_andamento = True
            self._ultimo_erro = ''
        staging = None
        try:
            if self._ocupado():
                raise BackupOcupado('Há uma validação em andamento; tente de novo quando ela terminar')
            staging = tempfile.mkdtemp(prefix='.restaurando-', dir=self.dir)
            self._extrair(caminho, staging)
            self._validar_manifesto(staging)
            # Se algo der errado na substituição, este backup permite voltar ao estado anterior.
            self._criar('antes-restauracao')
            if self.validador is None:
                resumo = self._substituir(staging)
            else:
                with self.validador.trava:
                    if self.validador.andamento.rodando:
                        raise BackupOcupado('Há uma validação em andamento; tente de novo quando ela terminar')
                    resumo = self._substituir(staging)
            log.info('Backup restaurado: %s', nome)
            return resumo
        finally:
            if staging:
                shutil.rmtree(staging, ignore_errors=True)
            with self._estado:
                self._em_andamento = False

    def _ocupado(self):
        return bool(self.validador and self.validador.andamento.resumo()['rodando'])

    def _extrair(self, caminho, staging):
        """Extrai o ZIP conferindo cada caminho: nada fora de planos/ e resultados/ e nada dentro da
        pasta de backups (que pode estar dentro de resultados/)."""
        try:
            with zipfile.ZipFile(caminho) as z:
                for info in z.infolist():
                    nome = info.filename.replace('\\', '/')
                    partes = PurePosixPath(nome)
                    if not partes.parts or partes.is_absolute() or '..' in partes.parts:
                        raise BackupInvalido('O backup contém caminhos inválidos')
                    if partes.parts[0] not in RAIZES:
                        raise BackupInvalido('O backup não tem o formato esperado')
                    if partes.parts[0] in ('manifesto.json', 'banco.sql') and len(partes.parts) != 1:
                        raise BackupInvalido('O backup não tem o formato esperado')
                    if stat.S_ISLNK(info.external_attr >> 16):
                        raise BackupInvalido('O backup contém links simbólicos')
                    if self._reservado(nome):
                        raise BackupInvalido('O backup tenta sobrescrever a pasta de backups')
                z.extractall(staging)
        except zipfile.BadZipFile as erro:
            raise BackupInvalido('O arquivo não é um backup válido') from erro

    def _validar_manifesto(self, staging):
        try:
            with open(os.path.join(staging, 'manifesto.json'), encoding='utf-8') as arq:
                manifesto = json.load(arq)
        except (OSError, ValueError) as erro:
            raise BackupInvalido('O backup não tem um manifesto válido') from erro
        if not isinstance(manifesto, dict) or manifesto.get('formato') != FORMATO:
            raise BackupInvalido('Este backup foi feito por uma versão incompatível do sistema')

    def _reservado(self, nome):
        """O caminho do ZIP cai dentro da pasta de backups (quando ela fica em planos/ ou resultados/)."""
        for raiz, prefixo in ((self.cfg.planos_dir, 'planos'), (self.cfg.resultados_dir, 'resultados')):
            try:
                rel = os.path.relpath(os.path.abspath(self.dir), os.path.abspath(raiz))
            except ValueError:
                continue
            if rel == os.pardir or rel.startswith(os.pardir + os.sep):
                continue
            alvo = prefixo + '/' + rel.replace(os.sep, '/')
            if nome == alvo or nome.startswith(alvo + '/'):
                return True
        return False

    def _substituir(self, staging):
        resumo = {}
        for prefixo, destino in (('planos', self.cfg.planos_dir), ('resultados', self.cfg.resultados_dir)):
            self._limpar(destino, self._preservar(destino))
            resumo[prefixo] = self._copiar(os.path.join(staging, prefixo), destino)
        dump = os.path.join(staging, 'banco.sql')
        if os.path.isfile(dump):
            self._restaurar_banco(dump)
            resumo['banco'] = True
        return resumo

    def _preservar(self, destino):
        """Primeiro nível da pasta de backups quando ela está dentro de `destino` (não apagar o
        próprio backup durante a restauração)."""
        try:
            rel = os.path.relpath(os.path.abspath(self.dir), os.path.abspath(destino))
        except ValueError:
            return set()
        if rel == os.curdir or rel == os.pardir or rel.startswith(os.pardir + os.sep):
            return set()
        return {rel.split(os.sep)[0]}

    def _limpar(self, destino, preservar):
        os.makedirs(destino, exist_ok=True)
        for nome in os.listdir(destino):
            if nome in preservar:
                continue
            caminho = os.path.join(destino, nome)
            try:
                if os.path.isdir(caminho) and not os.path.islink(caminho):
                    shutil.rmtree(caminho)
                else:
                    os.remove(caminho)
            except FileNotFoundError:
                pass

    def _copiar(self, origem, destino):
        if not os.path.isdir(origem):
            return 0
        preservar = self._preservar(destino)
        total = 0
        for nome in os.listdir(origem):
            if nome in preservar:
                continue
            src = os.path.join(origem, nome)
            dst = os.path.join(destino, nome)
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            total += 1
        return total

    # Agendamento --------------------------------------------------------------------------------

    def iniciar_agendador(self):
        threading.Thread(target=self._agendador, daemon=True).start()

    def _agendador(self):
        """Cria um backup por dia na hora configurada. Ao subir depois da hora, faz o do dia se ainda
        não houver nenhum (um deploy de manhã não deixa o dia sem backup)."""
        while True:
            agora = datetime.now()
            alvo = agora.replace(hour=self.cfg.backup_hora, minute=0, second=0, microsecond=0)
            if alvo <= agora:
                if not self._automatico_hoje():
                    self._tentar_automatico()
                alvo += timedelta(days=1)
            espera = (alvo - datetime.now()).total_seconds()
            if espera > 0:
                time.sleep(espera)
            self._tentar_automatico()

    def _automatico_hoje(self):
        hoje = datetime.now().date()
        return any(b['origem'] == 'automatico' and b['data'].date() == hoje for b in self.listar())

    def _tentar_automatico(self):
        # Se uma validação (ou outro backup) estiver rodando, tenta de novo a cada meia hora.
        for _ in range(12):
            try:
                item = self.criar('automatico')
                log.info('Backup automático criado: %s', item['nome'])
                return
            except BackupOcupado:
                log.info('Backup automático adiado: validação ou outro backup em andamento')
                time.sleep(1800)
            except Exception:
                log.exception('Falha no backup automático')
                return
        log.warning('Backup automático não pôde ser feito hoje')


def _tamanho(bytes_):
    valor = float(bytes_)
    for unidade in ('B', 'KB', 'MB', 'GB', 'TB'):
        if valor < 1024 or unidade == 'TB':
            return f'{valor:.0f} {unidade}' if unidade == 'B' else f'{valor:.1f} {unidade}'
        valor /= 1024
