# PRD — ditado próprio para GNOME/Wayland

Documento de requisitos do substituto do Typeless nesta máquina. Tudo aqui saiu de medição no
sistema do dono, não de suposição: os campos vêm do banco do próprio Typeless
(`~/.config/Typeless/typeless.db`, tabela `history_v2`), dos 56 ditados reais e dos testes de
reconhecimento que já rodamos.

## 1. Problema

O único ditado que funciona bem hoje nesta máquina é o **Typeless**, e ele tem dois custos:

- **Derruba a sessão GNOME.** O helper dele fala por **AT-SPI**, e o bug do Ubuntu **#2158636**
  (gnome-shell segfaulta em `libgobject` durante tráfego AT-SPI) já causou **4 a 6 quedas de
  sessão** desde 01/10. O comportamento foi reproduzido com o próprio LibreOffice como cliente
  AT-SPI, então não é exclusividade do app — mas é o app que mantém o barramento em uso.
- **Não temos controle.** É software fechado, sem fonte, e guarda apenas o resultado final
  (`refined_text`) — o texto bruto não existe no banco.

## 2. Usuário e uso real medido

- Um usuário (o dono), uso **pesado e diário**: **56 ditados** registrados, média de **17,6 s**,
  o maior de **170 s**, média de **151 caracteres** por ditado.
- Três modos já em uso: `voice_transcript` (a maioria), `voice_translation`, `voice_command`.

## 3. Requisitos (extraídos do comportamento observado)

| # | Requisito | Origem da evidência |
|---|---|---|
| R1 | Atalho global para iniciar/parar o ditado, e atalho separado para "colar o último texto" | `app-settings.json` → `featureShortcutBindings` (`dictationMode`, `askAnythingMode`, `translationMode`, `pasteLastTranscript`) |
| R2 | Inserir o texto **no cursor do aplicativo em foco**, em qualquer app | substitui o `libInputHelper` do Typeless (rotas uinput e AT-SPI) |
| R3 | Três modos: **transcrição**, **tradução** e **comando** | valores de `mode` no banco |
| R3a | **O modo comando EXECUTA a instrução ditada com IA** e insere o RESULTADO, não a fala | medido no teste ampliado: o dono ditou "reescreva como um post viral no Twitter com emojis e hashtags" e o app entregou um post pronto, com emojis e hashtags |
| R3b | O modo tradução traduz para o idioma pedido e insere a tradução | medido: o dono ditou em português e o app entregou em inglês, "Here is the product info…" |
| R4 | **Refino por IA** do texto: remover muletas, corrigir concordância e pontuação; em ditados longos, **estruturar em itens** | o único campo de texto é `refined_text`; a amostra de 79 s veio em lista numerada |
| R5 | Histórico com duração, microfone, texto e áudio | colunas `duration`, `mic_device`, `refined_text`, `audio_local_path` |
| R6 | Áudio guardado **localmente** | `~/.config/Typeless/Recordings/*.ogg` (56 arquivos, 2,2 MB) |
| R7 | **Não derrubar a sessão** — sem AT-SPI no caminho | a razão de existir deste projeto |
| R8 | Escolha de microfone | `microphoneDevices` em `app-settings.json`, `mic_device` no banco |
| R9 | Subir com a sessão | `launchAtSystemStartup` |
| R11 | **O usuário escolhe o modelo de refino** — qualquer provedor compatível com a API de chat da OpenAI (OpenRouter, DeepSeek, OpenAI, Groq, Ollama local, llama.cpp, vLLM) | pedido do dono: "que o usuário possa usar a IA que quiser" |
| R11a | **Sem padrão que funcione sozinho**: todo provedor de qualidade exige chave (o nível gratuito do OpenRouter responde **HTTP 401** sem ela — medido). Então a **primeira execução pede a configuração** e **valida na hora**, com uma chamada de verdade; se o provedor recusar, **nada é salvo** | decisão do dono: "o padrão gratuito não funciona; que o app permita indicar a IA que o usuário deseja" |
| R11a2 | O assistente já traz os provedores comuns prontos (OpenRouter, DeepSeek, OpenAI, Groq, Ollama local, outro) e usa **janela gráfica** quando há sessão, terminal quando não | preferência do dono por GUI; o app precisa funcionar sem ela também |
| R11b | **A chave nunca fica no arquivo de configuração** — só o NOME da variável de ambiente | o arquivo pode ser compartilhado sem vazar credencial |
| R11c | **Sem fallback silencioso**: provedor fora do ar ou chave ausente geram erro explícito, não troca automática de modelo | mesma regra da descoberta de dispositivos: o defeito tem de aparecer |
| R10 | Indicador de estado (gravando / transcrevendo / inserindo) | ausência disso torna o app "mudo"; o Typeless usa janela própria |

## 4. Não-objetivos da primeira versão

- Transcrição de reuniões ou de áudio de arquivo longo.
- Sincronização em nuvem, conta, login.
- Versão para outras plataformas.

## 5. Arquitetura proposta (reaproveitando o que já está provado)

```
atalho (evdev, já escrito no expansor)
   → pw-record (captura, já instalado)
      → faster-whisper local (turbo int8)      [medido: 95% e 83% de concordância em 20,6 s e 78,9 s]
         → refino por LLM (prompt; opção de rodar local)
            → uinput_type.py (injeção, já publicado no uinput-expander)
```

Cada peça já existe e está medida: leitura de teclado por evdev, injeção por uinput sem clipboard,
vigia de dispositivos por inotify. **A única peça nova é a transcrição**, e ela já foi testada.

## 6. Riscos medidos

| Risco | Situação | Mitigação |
|---|---|---|
| Qualidade do reconhecimento local | 95% (20,6 s) e 83% (78,9 s) de concordância com o texto do Typeless; erros reais foram 2–3 palavras em 79 s | teste ampliado com 20 amostras ≥ 8 s; se necessário, `medium` ou `distil-large-v3` |
| O refino mudar o registro da fala | observado: "contigo" virou "com você" no primeiro teste | prompt explícito ("mantenha o registro") + revisão por amostragem |
| Latência | a medir no protótipo (o teste rodou com VAD e `beam_size=5`) | `beam_size` menor, modelo `small`, ou refino desligado no modo rápido |
| O app pago também erra | num áudio de 1,8 s o Typeless escreveu "Che è tutto?", em italiano | nada a fazer senão não usar áudios curtos como referência |
| Privacidade | áudio fica local; só o texto vai ao LLM | opção de refino com modelo local, para o caso de "nada sai da máquina" |

## 7. Critérios de aceitação da v1

1. Ditar em qualquer aplicativo e o texto aparecer no cursor, **sem clipboard**.
2. **Nenhuma regressão de sessão** em uma semana de uso: `journalctl` sem `gnome-shell[..]: segfault`.
3. Concordância média ≥ 90% com o texto do Typeless em 20 amostras reais.
4. Atalho de "colar o último texto" funcionando.
5. Histórico local com áudio e texto, sem depender de serviço externo.

## 8. Marcos

- **M1** — atalho → gravar → transcrever → inserir (sem refino, sem UI). É o que prova o caminho.
- **M2** — refino por LLM com prompt versionado + comparação com o Typeless.
- **M3** — modos (`transcript`, `translation`, `command`).
- **M4** — histórico, escolha de microfone, indicador de estado.
- **M5** — publicação como projeto público, no mesmo padrão do `uinput-expander`.

## 8a. Resultado do teste de qualidade (20 amostras ≥ 8 s)

| conjunto | amostras | concordância média |
|---|---|---|
| modo `voice_transcript` | 18 | **86,3%** (bruto) / 84,7% (refinado) |
| modo `voice_command` | 1 | 2,8% — **não é erro de audição**: o app executou a instrução |
| modo `voice_translation` | 1 | 11,1% — **não é erro de audição**: o app traduziu para o inglês |

**Leitura correta:** nos dois casos fora da curva o Whisper transcreveu a fala **verbatim** — o
Typeless é que fez outra coisa (executou um comando, traduziu). A concordância de 86% no modo
padrão mede **semelhança com o estilo do Typeless**, não acerto de audição: a diferença é
majoritariamente de reescrita. Faixa observada: 61% a 100%.

## 8b. Refino configurável — implementado e testado (17/10)

`refino.py` lê `~/.config/ditado/config.toml`:

```toml
[refino]
base_url    = "https://api.deepseek.com/v1"   # ou openrouter.ai/api/v1, ollama, etc.
model       = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"              # o NOME da variável, nunca a chave
```

Quatro casos testados:

| caso | resultado |
|---|---|
| sem arquivo de config | usa o padrão (OpenRouter gratuito) e falha dizendo qual variável exportar |
| config do usuário (DeepSeek) | refino correto: "O prazo é até sexta, e o relatório tem que estar pronto." |
| provedor com URL inválida | erro do provedor aparece (`Name or service not known`), sem troca silenciosa |
| OpenRouter gratuito **sem** chave | HTTP **401** — o nível gratuito exige conta gratuita e chave |

**Assistente de configuração** (`refino.py --configurar`), testado de ponta a ponta:

| caso | resultado |
|---|---|
| primeira execução, sem config | recusa com a instrução: "ainda não configurado: rode refino.py --configurar" |
| fluxo completo (salvar → validar → carregar → refinar) | validação "respondeu: ok" e refino real correto |
| provedor fora do ar | recusa com o erro do provedor, sem trocar de modelo |
| chave vinda do ambiente | nenhum arquivo de credencial é escrito (só quando o usuário digita a chave) |

**O prompt é editável** (`prompt` ou `prompt_extra` no arquivo): é ali que mora a fluidez, e cada
usuário pode ajustar o registro que prefere.

## 9. O que já está decidido e o que falta medir

**Decidido:** injeção por uinput (sem clipboard, sem AT-SPI), ASR local, áudio local.
**Falta medir:** concordância média em 20 amostras (`/tmp/spike2.json`), latência ponta a ponta,
e se o Typeless usa nuvem para transcrever (tráfego durante um ditado).
