#!/usr/bin/env python3
"""
Motor de digitação por uinput — base do expansor próprio (sem clipboard, sem piscar).

Por que existe: no GNOME Wayland a única injeção confiável é uinput (teclado virtual no
kernel). O Espanso dependia do clipboard para acentos, e era isso que produzia o
"quadradinho" perto do cursor. Aqui a digitação é só tecla, sempre.

Uso:  uinput_type.py "texto a digitar"

Mapa de teclas: códigos evdev (fixos, independentes de layout — o compositor aplica o
layout br). Os símbolos com shift NÃO seguem o padrão americano: os códigos abaixo foram
medidos por sonda nesta máquina em 15/out/2026.
"""
import ctypes
import fcntl
import os
import struct
import sys
import time

UINPUT = "/dev/uinput"
EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_SETUP = 0x405C5503
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502


class InputId(ctypes.Structure):
    _fields_ = [("bustype", ctypes.c_uint16), ("vendor", ctypes.c_uint16),
                ("product", ctypes.c_uint16), ("version", ctypes.c_uint16)]


class UinputSetup(ctypes.Structure):
    _fields_ = [("id", InputId), ("name", ctypes.c_char * 80),
                ("ff_effects_max", ctypes.c_uint32)]


# --- códigos evdev (KEY_*) das teclas que importam -------------------------------
K = {
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23,
    "o": 24, "p": 25, "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35,
    "j": 36, "k": 37, "l": 38, "z": 44, "x": 45, "c": 46, "v": 47, "b": 48,
    "n": 49, "m": 50,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    " ": 57, ".": 52, ",": 51, "-": 12, "=": 13, ";": 53, "/": 89, "\\": 86, "?": 0,
    "[": 26, "]": 27, "`": 41,
    "enter": 28, "backspace": 14, "tab": 15, "shift": 42, "ctrl": 29, "esc": 1,
}

# símbolos que são Shift + tecla de dígito (esses seguem o padrão)
# apóstrofo: medido na sonda — é a tecla 41 (a 40 é o til, tecla morta)
K["'"] = 41

SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "&": "7", "*": "8",
           "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\"}

# MEDIDO por sonda (15/out/2026, layout br desta máquina): o teclado brasileiro não segue
# o padrão americano nos símbolos com shift.
#   ':' = Shift+53  |  '"' = Shift+41  |  '^' = Shift+40 (morta)  |  '<' = Shift+51  |  '>' = Shift+52
#   '/' = 89 e '?' = Shift+89 | '\\' = 86 e '|' = Shift+86 (medidos por sonda)
SHIFT_EXTRA = {":": 53, '"': 41, "^": 40, "<": 51, ">": 52,
               "?": 89, "|": 86}

# Acentos no layout br: tecla morta + vogal, ou tecla própria (ç).
# MEDIDO: 26 = acento agudo (á é í ó ú) | 40 = til (ã õ) e, com shift, circunflexo (ê â)
#         39 = ç (mesma tecla do ';')
# (código da tecla morta, vogal, exige Shift?)
# Medido no layout br abnt2: 26 = tecla do acento agudo; 40 = tecla do til/acento circunflexo
# (com Shift vira o circunflexo); 39 = tecla do ç.
ACENTOS = {
    "á": (26, K["a"], False), "é": (26, K["e"], False), "í": (26, K["i"], False),
    "ó": (26, K["o"], False), "ú": (26, K["u"], False),
    "â": (40, K["a"], True),  "ê": (40, K["e"], True),  "ô": (40, K["o"], True),
    "ã": (40, K["a"], False), "õ": (40, K["o"], False),
    "à": (26, K["a"], True),
    "ç": (39, None, False),
}


class Teclado:
    def __init__(self, nome="expansor-hermes"):
        self.fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        # Habilita TODOS os códigos de tecla. Habilitar só os que estão no mapa parece
        # suficiente, mas torna invisível todo código fora dele: o kernel descarta eventos
        # de teclas não declaradas, e o sintoma é silêncio (nenhum caractere), não erro.
        for code in range(1, 256):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        setup = UinputSetup()
        setup.id = InputId(0x03, 0x1234, 0x5678, 1)
        setup.name = nome.encode()[:79]
        setup.ff_effects_max = 0
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.35)   # o compositor precisa ver o dispositivo antes do 1º evento

    def _emit(self, etype, code, value):
        os.write(self.fd, struct.pack("llHHi", 0, 0, etype, code, value))

    def key(self, code, shift=False):
        # 2 ms entre apertar e soltar: sem isso, alguns aplicativos perdem a tecla
        # (apertar e soltar no mesmo instante pode ser lido como repetição ou ignorado).
        if shift:
            self._emit(EV_KEY, K["shift"], 1)
        self._emit(EV_KEY, code, 1)
        time.sleep(0.002)
        self._emit(EV_KEY, code, 0)
        if shift:
            self._emit(EV_KEY, K["shift"], 0)
        self._emit(EV_SYN, SYN_REPORT, 0)

    def digitar(self, texto, pausa=0.012, pausa_acento=0.05):
        """Digita o texto. Caracteres fora do mapa são ignorados."""
        for ch in texto:
            if ch in ACENTOS:
                base, vogal, com_shift = ACENTOS[ch]
                if vogal is None:            # ç: tecla própria
                    self.key(base, shift=com_shift)
                else:                        # tecla morta: precisa de folga antes da vogal
                    self.key(base, shift=com_shift)
                    time.sleep(pausa_acento)
                    self.key(vogal)
            elif ch in SHIFT_EXTRA:
                self.key(SHIFT_EXTRA[ch], shift=True)
            elif ch in SHIFTED:
                self.key(K[SHIFTED[ch]], shift=True)
            elif ch.isupper() and ch.lower() in K:
                self.key(K[ch.lower()], shift=True)
            elif ch in K:
                self.key(K[ch])
            time.sleep(pausa)

    def fechar(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    kb = Teclado()
    try:
        kb.digitar(" ".join(sys.argv[1:]))
    finally:
        time.sleep(0.2)
        kb.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
