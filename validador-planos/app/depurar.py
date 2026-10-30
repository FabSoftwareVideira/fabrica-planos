"""Mostra o que o validador extrai de um PDF, sem chamar o Ollama.

Uso: python -m app.depurar "nome do plano.pdf" [--prompt]
O nome é procurado em PLANOS_DIR; um caminho completo também serve.
"""
import os
import sys

from .config import carregar
from .extrator import extrair_texto
from .prompt import build_prompt
from .secoes import analisar_texto


def main(args):
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        return 1
    caminho = args[0]
    if not os.path.isfile(caminho):
        caminho = os.path.join(carregar().planos_dir, caminho)

    texto = extrair_texto(caminho)
    sec = analisar_texto(texto)
    print('#' * 20, 'TEXTO EXTRAÍDO', '#' * 20)
    print(texto)
    print()
    print('#' * 20, 'SEÇÕES', '#' * 20)
    for chave, valor in sec.items():
        print(f'===== {chave}')
        print(valor if valor not in ('', None) else '(vazio)')
    if '--prompt' in args:
        print()
        print('#' * 20, 'PROMPT', '#' * 20)
        print(build_prompt(sec))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
