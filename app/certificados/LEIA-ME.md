# Certificados raiz aceitos nas assinaturas dos planos

Quando o professor envia o plano assinado, o app só aceita assinaturas de certificados emitidos por uma
das autoridades raiz desta pasta (arquivos `.crt`, `.cer`, `.pem` ou `.der`). Sem nenhum certificado aqui,
todo envio de plano assinado é recusado com o aviso "A conferência de assinaturas ainda não foi configurada".

Coloque aqui o certificado da **AC Raiz do Governo Federal do Brasil v1**, a raiz das assinaturas feitas em
assinador.iti.br com a conta gov.br. Para aceitar também certificados ICP-Brasil (e-CPF), acrescente a raiz
da ICP-Brasil (v5, v10...).

Outra pasta pode ser usada com a variável `CERTIFICADOS_DIR`.
