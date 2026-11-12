# Página de backup da administração (templates/backup.html): lista, criação, download, restauração
# e exclusão dos arquivos de backup.


def contexto(servico):
    return {
        'backups': servico.listar(),
        'criando': servico.criando,
        'erro': servico.ultimo_erro,
        'hora': servico.cfg.backup_hora,
        'manter': servico.cfg.backup_manter,
    }
