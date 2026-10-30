import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    planos_dir: str
    resultados_dir: str
    ollama_url: str
    modelo: str
    num_ctx: int
    hora_agendada: int
    agendar: bool
    pdf_max_mb: int = 10
    historico_max: int = 3

    @property
    def historico_dir(self):
        return os.path.join(self.resultados_dir, 'historico')

    @property
    def csv_path(self):
        """Cópia do CSV da última validação, no caminho de sempre, para quem lê o arquivo direto."""
        return os.path.join(self.resultados_dir, 'validacao_planos.csv')


def carregar():
    return Config(
        planos_dir=os.environ.get('PLANOS_DIR', '/data/planos'),
        resultados_dir=os.environ.get('RESULTADOS_DIR', '/data/resultados'),
        ollama_url=os.environ.get('OLLAMA_URL', 'http://ollama:11434').rstrip('/'),
        modelo=os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b'),
        num_ctx=int(os.environ.get('OLLAMA_NUM_CTX', '8192')),
        hora_agendada=int(os.environ.get('AGENDAMENTO_HORA', '5')),
        agendar=os.environ.get('AGENDAR', '1') == '1',
        pdf_max_mb=int(os.environ.get('PDF_MAX_MB') or '10'),
        historico_max=max(1, int(os.environ.get('HISTORICO_MAX') or '3')),
    )
