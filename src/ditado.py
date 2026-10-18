#!/usr/bin/env python3
"""Ditado por voz — marco 1: atalho → gravar → transcrever → refinar → inserir.

Um toque no **Alt direito** (o mesmo AltGr do Typeless) começa a gravar; outro toque para. O texto
aparece no cursor do aplicativo em foco. Sem clipboard, sem acessibilidade (AT-SPI) — o texto entra
pelo teclado virtual, como se fosse digitado.

Desenho do atalho: AltGr é modificador e também serve para digitar símbolo. Só conta como atalho
quando a tecla é pressionada e solta **sem nenhuma outra tecla no meio** e em menos de meio segundo.

Duas armadilhas medidas em 17/10, já resolvidas aqui:
  * **Leitura não bloqueante de evdev devolve `None`**, não levanta `BlockingIOError`. Comparar antes
    de `len()`, senão o serviço morre com `TypeError` no meio do uso.
  * **`pw-record` só finaliza o WAV com SIGINT.** Com SIGTERM o arquivo fica sem cabeçalho válido e a
    transcrição falha com "Invalid data found when processing input".

Uso:
    ditado.py                  # roda em primeiro plano (Ctrl+C sai)
    ditado.py --teste ARQUIVO  # transcreve um arquivo de áudio e imprime
    ditado.py --teste-gravacao # grava 3 s do microfone, confere o WAV e transcreve
"""
import ctypes
import os
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time

# os módulos companheiros (injeção e refino) ficam no mesmo diretório deste arquivo,
# para o programa poder ser copiado para qualquer lugar pelo install.sh
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from uinput_type import Teclado         # noqa: E402  (motor de injeção: classe Teclado)
import refino as refino_mod             # noqa: E402  (refino configurável)

KEY_RIGHTALT = 100
EV_KEY = 0x01
TAP_MAX = 0.5                              # s — acima disso é AltGr segurado, não é atalho
BY_PATH = "/dev/input/by-path"
TAM_EVENTO = struct.calcsize("<qqHHi")     # 24 bytes: time_t(8) time_t(8) u16 u16 s32


# ---------- avisos ao usuário ----------
BIPE = {"inicio": "/tmp/ditado-inicio.wav", "fim": "/tmp/ditado-fim.wav", "erro": "/tmp/ditado-erro.wav"}


def avisar(titulo, corpo="", som=None):
    # --transient: o aviso não fica no histórico de notificações.
    # x-canonical-private-synchronous: a notificação nova SUBSTITUI a anterior em vez de empilhar.
    # Sem as duas coisas, cada ditado deixava três avisos na bandeja, e eles reapareciam
    # todos quando a sessão era retomada depois da tela de descanso.
    subprocess.run(["notify-send","--transient","--app-name=Ditado","-t","1500",
                    "-h","string:x-canonical-private-synchronous:ditado", titulo, corpo],
                   check=False, capture_output=True)
    if som and os.path.exists(som):
        subprocess.run(["pw-play", som], check=False, capture_output=True)


def preparar_bipes():
    """Três tons diferentes, para saber o estado sem olhar a tela."""
    import math
    import wave
    for nome, (freq, dur) in {"inicio": (880, 0.09), "fim": (660, 0.12), "erro": (220, 0.30)}.items():
        caminho = BIPE[nome]
        if os.path.exists(caminho):
            continue
        try:
            with wave.open(caminho, "w") as w:
                taxa = 22050
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(taxa)
                amostras = bytearray()
                for i in range(int(taxa * dur)):
                    env = min(1.0, i / (taxa * 0.01)) * min(1.0, (taxa * dur - i) / (taxa * 0.01))
                    amostras += struct.pack("<h", int(12000 * env * math.sin(2 * math.pi * freq * i / taxa)))
                w.writeframes(bytes(amostras))
        except OSError:
            pass


# ---------- captura ----------
class Gravador:
    def __init__(self):
        self.proc = None
        self.arquivo = None
        self.erros = None

    def comecar(self):
        fd, self.arquivo = tempfile.mkstemp(prefix="ditado-", suffix=".wav")
        os.close(fd)
        # stderr em arquivo, nunca em DEVNULL: foi o silêncio dele que escondeu a causa do teste falho
        self.erros = open("/tmp/ditado-pw-record.log", "ab")
        self.proc = subprocess.Popen(
            ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", self.arquivo],
            stdout=subprocess.DEVNULL, stderr=self.erros)

    def parar(self):
        """SIGINT, não SIGTERM: é o único sinal com que o pw-record finaliza o WAV."""
        if self.proc:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None
            if self.erros:
                self.erros.close()
                self.erros = None
        return self.arquivo


# ---------- transcrição ----------
_modelo = None


def modelo():
    global _modelo
    if _modelo is None:
        from faster_whisper import WhisperModel
        print("carregando o modelo (uma vez)...", flush=True)
        _modelo = WhisperModel("turbo", device="cpu", compute_type="int8", cpu_threads=12)
    return _modelo


def transcrever(caminho):
    segmentos, _ = modelo().transcribe(caminho, language="pt", vad_filter=True,
                                       beam_size=5, condition_on_previous_text=False)
    return "".join(s.text for s in segmentos).strip()


# ---------- teclado físico ----------
# Nomes de dispositivos que NÃO devem ser lidos (evitam eco do que nós mesmos digitamos)
IGNORAR = ("ditado-hermes", "expansor-hermes")


def teclados():
    """Todos os dispositivos de teclado, menos os nossos próprios.

    O `by-path` sozinho não basta: quando outro programa agarra o teclado físico (o
    input-remapper, por exemplo) e passa a reemitir por um dispositivo virtual, o `by-path`
    do teclado original fica mudo. Ler todos os `event*` que declaram teclas resolve, e é o
    que o expansor já faz. Os nossos próprios dispositivos ficam de fora para não gerar eco.
    """
    import glob
    lista, vistos = [], set()
    for ev in sorted(glob.glob("/dev/input/event*"), key=lambda x: int(x.rsplit("event", 1)[1])):
        try:
            with open("/sys/class/input/%s/device/name" % os.path.basename(ev)) as f:
                nome = f.read().strip()
            with open("/sys/class/input/%s/device/capabilities/key" % os.path.basename(ev)) as f:
                tem_teclas = bool(f.read().strip())
        except OSError:
            continue
        if not tem_teclas or nome in IGNORAR:
            continue
        real = os.path.realpath(ev)
        if real in vistos:
            continue
        vistos.add(real)
        lista.append(ev)
    return lista


def _teclados_legado():
    """Teclados físicos pelo caminho estável (by-path), sem nós repetidos do MESMO aparelho.

    Armadilha medida em 17/10: o mesmo teclado aparece duas vezes em by-path
    (`...-usb-0:1.2:1.1-event-kbd` e `...-usbv2-0:1.2:1.1-event-kbd`), e os dois nomes apontam para
    o mesmo `event*`. Abrir os dois fazia um único toque no AltGr ser processado duas vezes — o
    sintoma era a notificação de gravação repetida, sem parar. Deduplicar pelo caminho real resolve.
    """
    if not os.path.isdir(BY_PATH):
        return []
    vistos, unicos = set(), []
    for nome in sorted(os.listdir(BY_PATH)):
        if not nome.endswith("-event-kbd"):
            continue
        completo = os.path.join(BY_PATH, nome)
        real = os.path.realpath(completo)
        if real in vistos:
            continue
        vistos.add(real)
        unicos.append(completo)
    return unicos


def abrir(dispositivos):
    fds = {}
    for d in dispositivos:
        try:
            fds[os.open(d, os.O_RDONLY | os.O_NONBLOCK)] = d
        except OSError:
            pass
    return fds


def ler_evento(fd, timeout):
    """Um evento do teclado, ou None. Em fd não bloqueante, read devolve None — não levanta exceção."""
    try:
        prontos, _, _ = select.select([fd], [], [], timeout)
    except InterruptedError:
        return None
    if not prontos:
        return None
    try:
        dados = os.read(fd, TAM_EVENTO)
    except OSError:
        return None
    if not dados or len(dados) < TAM_EVENTO:
        return None
    _, _, tipo, codigo, valor = struct.unpack("<qqHHi", dados)
    return tipo, codigo, valor


def esperar_toque(fd, limite):
    """Depois do AltGr pressionado: True se for solto limpo (atalho), False se virar símbolo."""
    inicio = time.time()
    while time.time() - inicio < limite:
        ev = ler_evento(fd, max(0.0, limite - (time.time() - inicio)))
        if ev is None:
            return False
        tipo, codigo, valor = ev
        if tipo != EV_KEY:
            continue
        if codigo == KEY_RIGHTALT and valor == 0:
            return (time.time() - inicio) < TAP_MAX
        if valor == 1 and codigo != KEY_RIGHTALT:
            return False            # AltGr + outra tecla = símbolo
    return False


def esperar_inicio(fds):
    """Bloqueia até um toque limpo de AltGr em qualquer teclado."""
    while True:
        try:
            prontos, _, _ = select.select(list(fds), [], [], 1.0)
        except InterruptedError:
            continue
        for fd in prontos:
            ev = ler_evento(fd, 0.05)
            if ev is None:
                continue
            tipo, codigo, valor = ev
            if tipo == EV_KEY and codigo == KEY_RIGHTALT and valor == 1:
                if esperar_toque(fd, 1.5):
                    return fd


# ---------- injeção ----------
_teclado = None


def teclado():
    """Um único teclado virtual para toda a sessão, como o expansor faz."""
    global _teclado
    if _teclado is None:
        _teclado = Teclado("ditado-hermes")
        print("teclado virtual criado: ditado-hermes", flush=True)
    return _teclado



# ---------- vigia de /dev/input (inotify) ----------
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_ATTRIB = 0x00000004
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_Q_OVERFLOW = 0x00004000


def abrir_vigia(caminho="/dev/input"):
    """Fd que avisa quando um dispositivo entra ou sai — o kernel avisa, ninguém adivinha.

    Sem isso, quando outro programa (input-remapper, app de ditado, remapeador) recria os
    dispositivos virtuais, os números event* mudam e o ditado fica surdo com o serviço ativo.
    """
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    fd = libc.inotify_init1(os.O_NONBLOCK)
    if fd < 0:
        return None
    mascara = IN_CREATE | IN_DELETE | IN_ATTRIB | IN_MOVED_FROM | IN_MOVED_TO
    if libc.inotify_add_watch(fd, caminho.encode(), mascara) < 0:
        os.close(fd)
        return None
    return fd


def drenar_vigia(fd):
    """Consome os avisos pendentes e diz se houve mudança."""
    mudou = False
    while True:
        try:
            dados = os.read(fd, 4096)
        except OSError:
            break
        if not dados:
            break
        mudou = True
    return mudou


# ---------- ciclo principal ----------
def ciclo():
    preparar_bipes()
    dispositivos = teclados()
    if not dispositivos:
        raise SystemExit("nenhum teclado encontrado em %s" % BY_PATH)
    print("teclados:", ", ".join(os.path.basename(d) for d in dispositivos), flush=True)
    fds = abrir(dispositivos)
    vigia = abrir_vigia()
    print("vigia de /dev/input: %s" % ("ativo" if vigia else "indisponível"), flush=True)
    modelo()
    teclado()
    # Nada de notificação na partida. O serviço reinicia em várias situações (retomada da
    # sessão, atualização, remapeamento), e cada partida deixava um aviso que reaparecia na
    # tela de login. O estado "pronto" fica só no log, onde é consultável.
    print("pronto — toque no Alt direito", flush=True)

    gravador = Gravador()
    while True:
        # espera um toque, mas fica atento a mudanças em /dev/input
        while True:
            observados = list(fds) + ([vigia] if vigia else [])
            prontos, _, _ = select.select(observados, [], [], 1.0)
            if vigia and vigia in prontos and drenar_vigia(vigia):
                time.sleep(0.3)                      # deixa o dispositivo terminar de aparecer
                for fd in list(fds):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                novos = teclados()
                fds = abrir(novos)
                print("dispositivos mudaram; reabrindo (%d) — %s" % (
                    len(fds), ", ".join(os.path.basename(d) for d in novos)), flush=True)
                continue
            if prontos:
                break
        # um dos dispositivos tem evento: processa
        disparou = False
        for fd in prontos:
            if fd == vigia:
                continue
            ev = ler_evento(fd, 0.05)
            if ev is None:
                continue
            tipo, codigo, valor = ev
            if tipo == EV_KEY and codigo == KEY_RIGHTALT and valor == 1 and esperar_toque(fd, 1.5):
                disparou = True
                break
        if not disparou:
            continue

        avisar("Gravando", "Toque no Alt direito para parar.", BIPE["inicio"])
        print("gravando...", flush=True)
        gravador.comecar()
        time.sleep(0.45)          # o pw-record precisa abrir o arquivo; toque antes disso gera 0 byte

        limite = time.time() + 300          # rede de segurança: 5 minutos
        parado = False
        while not parado and time.time() < limite:
            try:
                prontos, _, _ = select.select(list(fds), [], [], 0.5)
            except InterruptedError:
                continue
            for fd in prontos:
                ev = ler_evento(fd, 0.05)
                if ev is None:
                    continue
                tipo, codigo, valor = ev
                if tipo == EV_KEY and codigo == KEY_RIGHTALT and valor == 1 and esperar_toque(fd, 1.5):
                    parado = True
                    break
        if not parado:
            avisar("Limite de 5 minutos", "Gravação encerrada automaticamente.", BIPE["erro"])

        arquivo = gravador.parar()
        time.sleep(0.15)
        tamanho = os.path.getsize(arquivo) if os.path.exists(arquivo) else 0
        if tamanho < 2000:
            detalhe = ""
            if os.path.exists("/tmp/ditado-pw-record.log"):
                detalhe = open("/tmp/ditado-pw-record.log", encoding="utf-8", errors="replace").read()[-300:]
            avisar("Gravou muito pouco", "%d bytes. %s" % (tamanho, detalhe[:150]), BIPE["erro"])
            print("gravação curta demais:", tamanho, "bytes |", detalhe.replace("\n", " ")[:200], flush=True)
            if os.path.exists(arquivo):
                os.unlink(arquivo)
            continue

        avisar("Transcrevendo", "Um instante.", BIPE["fim"])
        try:
            bruto = transcrever(arquivo)
        except Exception as e:
            avisar("Falha na transcrição", str(e)[:200], BIPE["erro"])
            print("erro na transcrição:", e, flush=True)
            if os.path.exists(arquivo):
                os.unlink(arquivo)
            continue
        if not bruto:
            avisar("Nada foi dito", "Gravação sem fala, nada inserido.", BIPE["erro"])
            if os.path.exists(arquivo):
                os.unlink(arquivo)
            continue
        print("transcrito:", bruto[:120], flush=True)

        texto = bruto
        try:
            texto = refino_mod.refinar(bruto)
        except SystemExit as e:                      # refino não configurado
            avisar("Refino não configurado", "%s — inserindo sem refino." % e, BIPE["erro"])
        except Exception as e:
            avisar("Refino falhou", "%s — inserindo sem refino." % str(e)[:160], BIPE["erro"])

        try:
            teclado().digitar(texto, pausa=0.011, pausa_acento=0.045)
            avisar("Inserido", texto[:120], BIPE["fim"])
            print("inserido:", texto[:120], flush=True)
        except Exception as e:
            avisar("Falha ao inserir", str(e)[:200], BIPE["erro"])
            print("erro ao inserir:", e, flush=True)
        if os.path.exists(arquivo):
            os.unlink(arquivo)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(sys.argv) > 2 and sys.argv[1] == "--teste":
        preparar_bipes()
        bruto = transcrever(sys.argv[2])
        print("BRUTO:", bruto)
        try:
            print("REFINADO:", refino_mod.refinar(bruto))
        except Exception as e:
            print("refino indisponível:", e)
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--teste-gravacao":
        preparar_bipes()
        g = Gravador()
        print("gravando 3 s do microfone...", flush=True)
        g.comecar()
        time.sleep(3)
        arquivo = g.parar()
        tamanho = os.path.getsize(arquivo)
        with open(arquivo, "rb") as f:
            cabecalho = f.read(4)
        print("arquivo:", arquivo, tamanho, "bytes")
        print("cabeçalho RIFF?", cabecalho == b"RIFF", cabecalho)
        print("BRUTO:", transcrever(arquivo) or "(nada)")
        return 0
    try:
        ciclo()
    except KeyboardInterrupt:
        print("\nsaindo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
