# ditado-hermes

Ditado por voz para Linux, local e independente de acessibilidade: você toca um atalho, fala,
toca de novo, e o texto aparece no cursor do aplicativo em foco.

- **Reconhecimento local** com `faster-whisper` (nenhum áudio sai da máquina).
- **Injeção por `uinput`** — o texto entra como se fosse digitado. Sem área de transferência
  (o "colar" no GNOME pisca um popup perto do cursor) e **sem AT-SPI**.
- **Refino por IA opcional**, com o provedor que você escolher, configurado depois da instalação.
- **Atalho global por `evdev`**, que é o caminho que existe no Wayland.

## Por que existe

Aplicativos comerciais de ditado no Linux costumam inserir texto pela **acessibilidade (AT-SPI)**.
Isso mantém o barramento de acessibilidade em uso, e no GNOME do Ubuntu 24.04 há um defeito
conhecido em que o `gnome-shell` cai nesse caminho. Um ditado que injeta por `uinput` **não toca
AT-SPI**, então essa família de quedas de sessão deixa de existir.

O custo é honesto: software próprio é manutenção própria.

## Requisitos

| peça | para quê |
|---|---|
| Python 3.11+ | o programa |
| `faster-whisper` | reconhecimento de fala local |
| PipeWire (`pw-record`, `pw-play`) | captura e avisos sonoros |
| grupo `input` | ler o teclado e criar o teclado virtual |
| `notify-send` | avisos de estado |
| um microfone | o resto |

Modelo: `turbo` (`large-v3-turbo`) com `compute_type="int8"` roda bem em CPU de 16 threads.
Medido numa Ryzen 9 7940HS: **~6 s para transcrever 10 s de fala**, +2 s de refino. Modelos
`small`/`medium`/`base` podem já estar no cache do Hugging Face — confira antes de baixar 1,6 GB.

## Instalação

```bash
git clone https://github.com/otakai/ditado-hermes.git
cd ditado-hermes
./install.sh
```

O `install.sh` não usa `root`. Ele confere as dependências, copia o programa para `~/.local/bin/ditado`,
instala o serviço de usuário e avisa se você não estiver no grupo `input`.

## Configurar a IA do refino

O refino é o que dá acabamento ao texto: tira muletas de fala, corrige concordância e pontuação.
**Não existe padrão que funcione sozinho** — todo provedor de qualidade exige uma chave. Por isso
a primeira execução pede a configuração:

```bash
ditado --configurar
```

Abre uma janela (ou pergunta no terminal, se não houver sessão gráfica) com os provedores comuns
prontos: OpenRouter, DeepSeek, OpenAI, Groq, Ollama local, ou qualquer outro compatível com a API
de chat da OpenAI. **Ele testa antes de salvar**: faz uma chamada de verdade e, se o serviço recusar,
mostra o erro e não grava nada.

Arquivos:

```
~/.config/ditado/config.toml   provedor, modelo e prompt — SEM a chave
~/.config/ditado/credencial    só a chave, permissão 600
```

Para usar sem nuvem, aponte para um Ollama local (`http://localhost:11434/v1`) e nada sai da máquina.

## Uso

1. Toque no **Alt direito** (AltGr) — aviso sonoro e notificação de gravação.
2. Fale.
3. Toque no **Alt direito** de novo — o texto aparece no cursor.

Só conta como toque se o Alt for pressionado e solto **sem nenhuma outra tecla no meio** e em menos
de meio segundo; AltGr usado para digitar símbolo nunca dispara o ditado.

O serviço sobe com a sessão (`systemctl --user status ditado`).

## Problemas conhecidos (medidos, não supostos)

**Aplicativos Electron** (Chromium embutido, como muitos clientes de chat) tratam teclas de forma
diferente do resto do sistema:

- **Ignoram a composição de teclas mortas.** Os acentos saem errados **só neles**, e corretos em
  aplicativos nativos. Não é defeito da injeção.
- **Ignoram os keysyms do teclado numérico**: `KP_Delete`, `KP_Up`, `KP_Left` não fazem nada,
  enquanto `Delete` e as setas comuns funcionam. Contorno: remapear os códigos do numérico para os
  keysyms comuns.

**Remapeadores de teclado** (por exemplo `input-remapper`) agarram o teclado físico e reemitem por um
dispositivo virtual próprio. Os números `event*` mudam, e o `by-path` do teclado original fica mudo.
Este programa vigia `/dev/input` por inotify e reabre sozinho, mas se você escrever outro leitor,
**precisa fazer o mesmo** — sem isso o serviço fica ativo e surdo, sem nenhum erro no log.

**Mapa de acentos incompleto falha em silêncio.** Caractere fora do mapa é simplesmente ignorado pelo
emissor. No `br abnt2`: agudo = tecla 26, til e circunflexo na mesma tecla 40 (cru = til, **com Shift
= circunflexo**), crase = Shift+26, cedilha = 39.

**IBus pode estar num layout diferente do GNOME.** `gsettings org.gnome.desktop.input-sources` dizer
`br` não garante nada — confira `ibus engine`.

## Qualidade medida

Comparação com o histórico de um aplicativo comercial (que guarda apenas o texto final, já passado
por IA) em 20 ditados reais com áudio:

| conjunto | amostras | concordância de palavras |
|---|---|---|
| modo transcrição | 18 | **86%** (faixa 61–100%) |
| modo comando | 1 | executou a instrução ditada |
| modo tradução | 1 | traduziu para inglês |

Os dois casos fora da curva **não eram erro de reconhecimento**: neles o aplicativo de referência
executou um comando e traduziu, enquanto este transcreveu a fala literalmente. A concordância de 86%
mede **semelhança com o estilo** da referência, não acerto de audição.

## Licença e autoria

MIT. Código escrito por **Hermes Agent** (Nous Research), com o modelo **DeepSeek V4 Flash**.
Requisitos, testes diários e os relatos de defeito são de **Osvaldo Takai**. Detalhes em `AUTHORS`.
