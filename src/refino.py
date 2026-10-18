#!/usr/bin/env python3
"""Configuração do modelo de IA usado no refino do ditado.

Não existe padrão que funcione sozinho: todo provedor de qualidade exige uma chave. Então o
programa **não finge** ter um padrão. Na primeira execução ele pede a configuração e valida na
hora, com uma chamada de verdade — se o provedor recusar, nada é salvo.

Uso:
    refino.py --configurar     # assistente (janela gráfica, se houver)
    refino.py --mostrar        # mostra a configuração atual
    refino.py "texto..."       # refina um texto

Arquivos:
    ~/.config/ditado/config.toml   → provedor, modelo, prompt (SEM a chave)
    ~/.config/ditado/credencial    → só a chave, permissão 600

Qualquer serviço compatível com a API de chat da OpenAI serve (OpenRouter, DeepSeek, OpenAI,
Groq, Ollama local, llama.cpp, vLLM). O assistente já traz os mais comuns prontos.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request

CONFIG_DIR = os.path.expanduser("~/.config/ditado")
CONFIG = os.path.join(CONFIG_DIR, "config.toml")
CRED = os.path.join(CONFIG_DIR, "credencial")

PROMPT = (
    "Você recebe a transcrição literal de uma fala em português brasileiro. "
    "Reescreva como texto escrito, preservando exatamente o sentido e o vocabulário de quem falou. "
    "Regras: remova muletas de fala (né, tipo, então, ahn, éé, bom, tá); corrija concordância, "
    "pontuação e maiúsculas; não resuma; não acrescente informação; não mude o registro da fala "
    "(se ele disse 'contigo', mantenha 'contigo'). Devolva apenas o texto final."
)

PROVEDORES = [
    ("OpenRouter (tem modelos gratuitos)", "https://openrouter.ai/api/v1", "google/gemma-4-31b-it:free"),
    ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ("Ollama (local, não pede chave)", "http://localhost:11434/v1", "llama3.1"),
    ("Outro (informar a URL)", "", ""),
]


# ---------- interface: janela quando houver, terminal quando não ----------
def tem_zenity():
    return shutil.which("zenity") is not None and bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def perguntar(texto, segredo=False, padrao=""):
    if tem_zenity():
        cmd = ["zenity", "--entry", "--title=Configurar o ditado", "--width=760", "--text=%s" % texto]
        if segredo:
            cmd.append("--hide-text")
        if padrao:
            cmd.append("--entry-text=%s" % padrao)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("configuração cancelada")
        return r.stdout.strip()
    if segredo:
        import getpass
        return getpass.getpass(texto + " ")
    return input(texto + (" [%s] " % padrao if padrao else " ")).strip() or padrao


def escolher(titulo, opcoes):
    if tem_zenity():
        cmd = ["zenity", "--list", "--title=Configurar o ditado", "--width=760",
               "--text=%s" % titulo, "--column=Serviço", "--height=380"]
        cmd += [o[0] for o in opcoes]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("configuração cancelada")
        escolhido = r.stdout.strip()
    else:
        print(titulo)
        for i, o in enumerate(opcoes, 1):
            print("  %d) %s" % (i, o[0]))
        escolhido = opcoes[int(input("número: ")) - 1][0]
    for o in opcoes:
        if o[0] == escolhido:
            return o
    raise SystemExit("opção inválida")


def avisar(mensagem, erro=False):
    if tem_zenity():
        subprocess.run(["zenity", "--error" if erro else "--info", "--title=Configurar o ditado",
                        "--width=700", "--text=%s" % mensagem])
    else:
        print(("ERRO: " if erro else "") + mensagem)


# ---------- configuração ----------
def salvar(base_url, model, chave):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write("# Configuração do refino por IA do ditado.\n"
                "# Trocar de modelo é só mudar estas linhas. A chave NÃO fica aqui.\n"
                "[refino]\n"
                'base_url = "%s"\n'
                'model    = "%s"\n' % (base_url, model))
    if chave:
        with open(CRED, "w", encoding="utf-8") as f:
            f.write(chave + "\n")
        os.chmod(CRED, stat.S_IRUSR | stat.S_IWUSR)
    elif os.path.exists(CRED):
        os.remove(CRED)


def testar(base_url, model, chave):
    corpo = json.dumps({"model": model, "max_tokens": 20,
                        "messages": [{"role": "user", "content": "responda apenas: ok"}]}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=corpo,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + (chave or "local")})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.load(r)
        return True, "respondeu: %s" % str(d["choices"][0]["message"]["content"]).strip()[:60]
    except urllib.error.HTTPError as e:
        return False, "HTTP %s — %s" % (e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception as e:
        return False, str(e)[:200]


def configurar():
    nome, base_url, modelo = escolher("Qual serviço de IA vai refinar o seu texto?", PROVEDORES)
    if not base_url:
        base_url = perguntar("URL base compatível com a API da OpenAI (ex.: https://meu-servidor/v1):")
    modelo = perguntar("Modelo a usar:", padrao=modelo or "")
    local = "localhost" in base_url or "127.0.0.1" in base_url
    chave = "" if local else perguntar(
        "Cole a chave de API de %s (vai para um arquivo 600, fora da configuração):" % nome,
        segredo=True)
    ok, detalhe = testar(base_url, modelo, chave)
    if not ok:
        avisar("O serviço recusou:\n\n%s\n\nNada foi salvo. Rode --configurar de novo." % detalhe,
               erro=True)
        return 1
    salvar(base_url, modelo, chave)
    avisar("Configurado e testado.\n\nServiço: %s\nModelo: %s\n%s\n\nConfiguração: %s\nChave: %s"
           % (nome, modelo, detalhe, CONFIG, CRED if chave else "não usada (servidor local)"))
    return 0


def carregar():
    if not os.path.exists(CONFIG):
        raise SystemExit("ainda não configurado: rode  refino.py --configurar")
    with open(CONFIG, "rb") as f:
        sec = tomllib.load(f).get("refino", {})
    cfg = {"base_url": sec.get("base_url"), "model": sec.get("model"),
           "api_key_env": sec.get("api_key_env"),
           "temperature": sec.get("temperature", 0.2), "timeout": sec.get("timeout", 60),
           "prompt": sec.get("prompt") or (PROMPT + (" " + sec["prompt_extra"] if sec.get("prompt_extra") else ""))}
    if not cfg["base_url"] or not cfg["model"]:
        raise SystemExit("configuração incompleta em %s: rode  refino.py --configurar" % CONFIG)
    return cfg


def chave(cfg):
    nomes = [cfg.get("api_key_env") or "", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"]
    for nome in nomes:
        if nome and os.environ.get(nome):
            return os.environ[nome]
    if os.path.exists(CRED):
        return open(CRED, encoding="utf-8").read().strip()
    env = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env):
        for linha in open(env, encoding="utf-8"):
            for nome in ("OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"):
                if linha.startswith(nome + "="):
                    return linha.split("=", 1)[1].strip().strip('"').strip("'")
    if "localhost" in (cfg["base_url"] or "") or "127.0.0.1" in (cfg["base_url"] or ""):
        return ""
    raise SystemExit("chave ausente: rode  refino.py --configurar")


def refinar(texto, cfg=None):
    cfg = cfg or carregar()
    corpo = json.dumps({"model": cfg["model"], "temperature": cfg["temperature"],
                        "messages": [{"role": "system", "content": cfg["prompt"]},
                                     {"role": "user", "content": texto}]}).encode()
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=corpo, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + chave(cfg)})
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        raise SystemExit("serviço recusou (%s): %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))
    except urllib.error.URLError as e:
        raise SystemExit("não consegui falar com %s: %s" % (url, e.reason))


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--configurar":
        return configurar()
    if args[0] == "--mostrar":
        try:
            cfg = carregar()
        except SystemExit as e:
            print(e)
            return 1
        print("configuração:", CONFIG)
        for k in ("base_url", "model", "temperature", "timeout"):
            print("  %-11s %s" % (k, cfg[k]))
        print("  credencial  %s" % (CRED if os.path.exists(CRED) else "ausente"))
        return 0
    print(refinar(" ".join(args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
