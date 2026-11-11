# Certificados raiz aceitos nas assinaturas dos planos

Quando o professor envia o plano assinado, o app só aceita assinaturas de certificados emitidos por uma
das autoridades raiz desta pasta (arquivos `.crt`, `.cer`, `.pem` ou `.der`). Sem nenhum certificado aqui,
todo envio de plano assinado é recusado com o aviso "A conferência de assinaturas ainda não foi configurada".

Coloque aqui a cadeia do gov.br, publicada pelo ITI em http://repo.iti.br/docs/Cadeia_GovBr-der.p7b
(AC Raiz, AC Intermediária e AC Final do Governo Federal do Brasil v1), que emite os certificados das
assinaturas feitas em assinador.iti.br com a conta gov.br. Aceita também `.p7b`/`.p7c`. Para ver a cadeia e
o endereço do emissor de um PDF assinado: `python scripts/extrair_certificados.py arquivo.pdf`. Para aceitar também certificados ICP-Brasil (e-CPF), acrescente a raiz
da ICP-Brasil (v5, v10...).

Outra pasta pode ser usada com a variável `CERTIFICADOS_DIR`.
