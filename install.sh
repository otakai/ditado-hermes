#!/usr/bin/env bash
# Instalador do ditado-hermes: sem root, sem tocar em nada do sistema.
set -euo pipefail

DESTINO="${HOME}/.local/bin/ditado"
UNIT="${HOME}/.config/systemd/user/ditado.service"
AQUI="$(cd "$(dirname "$0")" && pwd)"

echo "== ditado-hermes: instalando em ${DESTINO}"

# ---- dependências ----
falta=0
check() {
  if eval "$2" >/dev/null 2>&1; then echo "  ok: $1"; else echo "  FALTA: $1  ($3)"; falta=1; fi
}
check "Python 3.11+"        "python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)'" "instale python3"
check "faster-whisper"      "python3 -c 'import faster_whisper'"                                        "pip install faster-whisper (no mesmo interpretador que vai rodar)"
check "pw-record"           "command -v pw-record"                                                      "pacote pipewire-bin"
check "pw-play"             "command -v pw-play"                                                        "pacote pipewire-bin"
check "notify-send"         "command -v notify-send"                                                    "pacote libnotify-bin"

if command -v pw-record >/dev/null; then
  PY_REC="$(command -v python3)"
  if ! "$PY_REC" -c 'import faster_whisper' 2>/dev/null; then
    echo "  aviso: o python3 do PATH não tem faster-whisper."
    echo "         Se você usa um venv, rode este instalador com o venv ativo,"
    echo "         ou edite ExecStart= no serviço para o interpretador correto."
  fi
fi

if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
  echo "  ATENÇÃO: você não está no grupo 'input'."
  echo "           Sem ele o programa não lê o teclado nem cria o teclado virtual."
  echo "           Rode:  sudo usermod -aG input $USER   e saia e entre na sessão."
fi

[ "$falta" = "1" ] && { echo "== corrija o que falta e rode de novo"; exit 1; }

# ---- arquivos ----
mkdir -p "$DESTINO" "$(dirname "$UNIT")"
cp "$AQUI"/src/*.py "$DESTINO"/
chmod +x "$DESTINO"/ditado.py

cat > "${HOME}/.local/bin/ditado" <<LAUNCH
#!/usr/bin/env bash
exec "$(command -v python3)" "${DESTINO}/ditado.py" "\$@"
LAUNCH
chmod +x "${HOME}/.local/bin/ditado"

cat > "$UNIT" <<UNITFILE
[Unit]
Description=Ditado por voz (atalho Alt direito -> gravar -> transcrever -> refinar -> inserir)
Documentation=file://${AQUI}/README.md

[Service]
Type=simple
ExecStart=$(command -v python3) ${DESTINO}/ditado.py
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
