#!/usr/bin/env bash
# Baixa do npm e copia para app/static/vendor as bibliotecas de interface usadas pelas páginas:
#   - Padrão Digital de Governo (Design System gov.br) - CSS do core e dos componentes usados
#   - Fonte Rawline (a do DS), só o subconjunto latino nos pesos usados
#   - Font Awesome 5 Free (ícones do DS), estilos solid e regular
# Ficam versionadas no repositório: o servidor não depende de CDN nem de Node.
# Uso (precisa de npm): scripts/atualizar_vendor.sh   — depois rode os testes e confira as páginas.
set -euo pipefail
DS=3.7.0; RAWLINE=5.2.0; FA=5.15.4
COMPONENTES="header footer button card tag message list item divider avatar"
PESOS="400 500 600 700"

raiz="$(cd "$(dirname "$0")/.." && pwd)"; destino="$raiz/app/static/vendor"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
npm pack -q "@govbr-ds/core@$DS" "rawline-webfont@$RAWLINE" "@fortawesome/fontawesome-free@$FA" >/dev/null
for t in *.tgz; do mkdir "${t%.tgz}"; tar xzf "$t" -C "${t%.tgz}"; done

rm -rf "$destino"; mkdir -p "$destino/govbr-ds" "$destino/rawline/files" "$destino/fontawesome/css" "$destino/fontawesome/webfonts"

ds="govbr-ds-core-$DS/package/dist"
{
  echo "/* Padrão Digital de Governo (@govbr-ds/core $DS, licença MIT): tokens, base e componentes: $COMPONENTES */"
  cat "$ds/core-tokens.min.css"; echo; cat "$ds/core-base.min.css"; echo
  for c in $COMPONENTES; do cat "$ds/components/$c/$c.min.css"; echo; done
} | sed '/sourceMappingURL/d' > "$destino/govbr-ds/govbr-ds.min.css"
cp "govbr-ds-core-$DS/package/LICENSE" "$destino/govbr-ds/LICENSE"

rl="rawline-webfont-$RAWLINE/package"
: > "$destino/rawline/rawline.css"
for p in $PESOS; do
  cp "$rl/files/rawline-latin-$p-normal.woff2" "$destino/rawline/files/"
  printf "@font-face{font-family:'Rawline';font-style:normal;font-display:swap;font-weight:%s;src:url(files/rawline-latin-%s-normal.woff2) format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}\n" "$p" "$p" >> "$destino/rawline/rawline.css"
done
cp "$rl/LICENSE" "$destino/rawline/LICENSE"

fa="fortawesome-fontawesome-free-$FA/package"
cp "$fa/css/fontawesome.min.css" "$fa/css/solid.min.css" "$fa/css/regular.min.css" "$destino/fontawesome/css/"
cp "$fa"/webfonts/fa-solid-900.woff2 "$fa"/webfonts/fa-solid-900.woff "$fa"/webfonts/fa-regular-400.woff2 "$fa"/webfonts/fa-regular-400.woff "$destino/fontawesome/webfonts/"
cp "$fa/LICENSE.txt" "$destino/fontawesome/LICENSE.txt"

echo "Atualizado em $destino:"; du -sh "$destino"/*
