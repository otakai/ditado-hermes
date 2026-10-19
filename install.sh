#!/usr/bin/env bash
# Instalador do ditado-hermes: sem root, sem tocar em nada do sistema.
set -euo pipefail

# Os programas ficam num diretório, e o LAUNCHER é um arquivo com o mesmo nome do comando.
# NUNCA use o mesmo caminho para os dois: na v0.1.3 os dois apontavam para ~/.local/bin/ditado
# e o instalador morria com "É um diretório" — o dono percebeu na segunda máquina.
DESTINO="${HOME}/.local/lib/ditado"
LAUNCHER="${HOME}/.local/bin/ditado"
UNIT="${HOME}/.config/systemd/user/ditado.service"
AQUI="$(cd "$(dirname "$0")" && pwd)"

# Interpretador que vai rodar o programa. Precisa ter faster-whisper.
# Use PYTHON=... para apontar um venv dedicado, se o python3 do sistema não tiver o pacote.
PYTHON="${PYTHON:-$(command -v python3)}"

echo "== ditado-hermes: instalando em ${DESTINO}"
echo "   interpretador: ${PYTHON}"

# ---- dependências ----
falta=0
check() {
  if eval "$2" >/dev/null 2>&1; then echo "  ok: $1"; else echo "  FALTA: $1  ($3)"; falta=1; fi
}
check "Python 3.11+"        "\"$PYTHON\" -c 'import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)'" "instale python3 (ou aponte PYTHON= para um venv)"
check "faster-whisper"      "\"$PYTHON\" -c 'import faster_whisper'"                                   "pip install -r requirements.txt no interpretador acima"
check "PyAV < 19"           "\"$PYTHON\" -c 'import importlib.metadata as m; raise SystemExit(0 if int(m.version(\"av\").split(\".\")[0]) < 19 else 1)'" "av>=19 removeu metadata_errors e quebra toda transcrição: pip install 'av==18.0.0'"
check "pw-record"           "command -v pw-record"                                                     "pacote pipewire-bin"
check "pw-play"             "command -v pw-play"                                                       "pacote pipewire-bin"
check "notify-send"         "command -v notify-send"                                                   "pacote libnotify-bin"

if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
  echo "  ATENÇÃO: você não está no grupo 'input'."
  echo "           Sem ele o programa não lê o teclado nem cria o teclado virtual."
  echo "           Rode:  sudo usermod -aG input $USER   e saia e entre na sessão."
fi

[ "$falta" = "1" ] && { echo "== corrija o que falta e rode de novo"; exit 1; }

# ---- arquivos ----
# Conserta a instalação quebrada da v0.1.3: naquele layout os .py ficaram em ~/.local/bin/ditado
# (um diretório) porque o launcher tentava usar o mesmo caminho. Migra e libera o caminho.
if [ -d "$LAUNCHER" ]; then
  echo "  encontrando restos da v0.1.3 em ${LAUNCHER} (diretório); migrando os fontes"
  mkdir -p "$DESTINO"
  for f in "$LAUNCHER"/*.py; do [ -e "$f" ] && mv -f "$f" "$DESTINO"/; done
  if rmdir "$LAUNCHER" 2>/dev/null; then
    echo "  diretório antigo removido"
  else
    echo "  ATENÇÃO: ${LAUNCHER} ainda tem arquivos que não são .py. Mova-os e rode de novo."
    exit 1
  fi
fi

mkdir -p "$DESTINO" "$(dirname "$LAUNCHER")" "$(dirname "$UNIT")"
cp "$AQUI"/src/*.py "$DESTINO"/
chmod +x "$DESTINO"/ditado.py

cat > "$LAUNCHER" <<LAUNCH
#!/usr/bin/env bash
# launcher do ditado-hermes: os fontes ficam em ${DESTINO}
exec "${PYTHON}" "${DESTINO}/ditado.py" "\$@"
LAUNCH
chmod +x "$LAUNCHER"

cat > "$UNIT" <<UNITFILE
[Unit]
Description=Ditado por voz (atalho Alt direito -> gravar -> transcrever -> refinar -> inserir)
Documentation=file://${AQUI}/README.md

[Service]
Type=simple
ExecStart=${PYTHON} ${DESTINO}/ditado.py
Restart=on-failure
RestartSec=3
TimeoutStartSec=180

[Install]
WantedBy=default.target
UNITFILE

systemctl --user daemon-reload
systemctl --user enable ditado.service >/dev/null

echo "  instalado."
echo
echo "Próximos passos:"
echo "  1) ditado --configurar     (escolher o provedor de IA do refino)"
echo "  2) systemctl --user start ditado"
echo "  3) tocar no Alt direito, falar, tocar de novo"
echo
echo "  log:  journalctl --user -u ditado -f"
