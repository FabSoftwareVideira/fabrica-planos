from html import escape

from ..armazenamento.csvsaida import CAMPOS_COLUNA

# Página pública (sem login): apresenta o projeto e leva ao login com a conta Google institucional.
ESTILO = (
    '*{box-sizing:border-box}'
    'body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f3f4f6;color:#111827;line-height:1.5}'
    '.pagina{max-width:880px;margin:0 auto;padding:48px 16px}'
    '.topo{text-align:center;margin-bottom:40px}'
    '.topo h1{margin:0 0 12px;font-size:clamp(28px,5vw,40px)}'
    '.topo p{margin:0 auto 28px;max-width:620px;color:#4b5563;font-size:18px}'
    '.google{display:inline-flex;align-items:center;gap:12px;background:#fff;color:#1f1f1f;text-decoration:none;'
    'border:1px solid #747775;border-radius:999px;padding:12px 24px;font-weight:600;font-size:16px;'
    'box-shadow:0 1px 3px rgba(0,0,0,.08);transition:box-shadow .2s}'
    '.google:hover{box-shadow:0 2px 8px rgba(0,0,0,.18)}'
    '.google svg{width:20px;height:20px}'
    '.topo .restrito{margin:14px auto 0;font-size:14px;color:#6b7280}'
    '.painel{background:#fff;border-radius:12px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:16px}'
    '.painel h2{margin:0 0 16px;font-size:20px}'
    '.passos{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:0;padding:0;'
    'list-style:none;counter-reset:passo}'
    '.passos li{counter-increment:passo;font-size:14px;color:#4b5563}'
    '.passos li::before{content:counter(passo);display:flex;align-items:center;justify-content:center;width:28px;'
    'height:28px;border-radius:50%;background:#eef2ff;color:#2563eb;font-weight:700;margin-bottom:8px}'
    '.passos strong{display:block;color:#111827;font-size:15px;margin-bottom:2px}'
    '.campos{display:flex;flex-wrap:wrap;gap:8px}'
    '.campos span{background:#f3f4f6;border-radius:999px;padding:4px 12px;font-size:13px}'
    '.status{display:flex;flex-wrap:wrap;gap:16px;margin-top:16px;font-size:14px;color:#4b5563}'
    '.status b{color:#fff;border-radius:10px;padding:2px 8px;font-size:11px;margin-right:6px}'
    '.rodape{text-align:center;font-size:13px;color:#9ca3af;margin-top:32px}'
)

# Marca "G" do Google, como pedem as diretrizes do botão "Fazer login com o Google".
LOGO_GOOGLE = (
    '<svg viewBox="0 0 48 48" aria-hidden="true">'
    '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 '
    '13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
    '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 '
    '6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
    '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 '
    '24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
    '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 '
    '0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>'
    '</svg>'
)

PASSOS = [
    ('Envio dos PDFs', 'Os planos de ensino exportados do SIGAA são enviados pela coordenação.'),
    ('Leitura', 'O texto de cada PDF é extraído e separado nas seções do plano.'),
    ('Avaliação', 'Uma IA executada no servidor do campus confere se cada seção está completa.'),
    ('Resultado', 'O painel mostra a situação de cada plano, com relatório campo a campo.'),
]

STATUS = [('OK', '#22c55e', 'campo completo'), ('INCOMPLETO', '#eab308', 'falta informação'),
          ('AUSENTE', '#ef4444', 'campo vazio ou não encontrado')]


def gerar_html():
    passos = ''.join('<li><strong>' + escape(t) + '</strong>' + escape(d) + '</li>' for t, d in PASSOS)
    campos = ''.join('<span>' + escape(rotulo) + '</span>' for rotulo, _ in CAMPOS_COLUNA)
    status = ''.join('<span><b style="background:' + cor + '">' + s + '</b>' + escape(d) + '</span>'
                     for s, cor, d in STATUS)
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Validação de Planos de Ensino</title><style>' + ESTILO + '</style></head><body>'
        '<main class="pagina">'
        '<header class="topo"><h1>📋 Validação de Planos de Ensino</h1>'
        '<p>Conferência automática dos planos de ensino do IFC: cada plano é lido e avaliado seção por seção, '
        'apontando o que está completo e o que precisa de ajuste antes da publicação.</p>'
        # /dashboard exige login: sem sessão, o proxy leva ao Google e volta para o painel.
        '<a class="google" href="/dashboard">' + LOGO_GOOGLE + 'Entrar com Google</a>'
        '<p class="restrito">Acesso restrito a servidores, com a conta institucional @ifc.edu.br.</p></header>'
        '<section class="painel"><h2>Como funciona</h2><ol class="passos">' + passos + '</ol></section>'
        '<section class="painel"><h2>O que é verificado</h2><div class="campos">' + campos + '</div>'
        '<div class="status">' + status + '</div></section>'
        '<section class="painel"><h2>Privacidade</h2><p style="margin:0;color:#4b5563">A IA roda no próprio servidor '
        'do campus: o conteúdo dos planos não é enviado a serviços externos. O login com Google serve apenas para '
        'confirmar que quem acessa é servidor da instituição.</p></section>'
        '<p class="rodape">Instituto Federal Catarinense</p>'
        '</main></body></html>'
    )
