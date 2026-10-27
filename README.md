# 🏮 lantern

A coding assistant that runs entirely on your own laptop. No internet, no API key, no account.

lantern works like Claude Code in your terminal: you ask for something, and it reads your files, searches them, edits them and runs commands to check its work. It asks before every edit or command. The model runs locally through [Ollama](https://ollama.com), so once the model is downloaded you can use it on a plane.

```
$ lantern
🏮 lantern qwen3:4b · ~/my-project · /help for commands

> why does test_parse fail?
  search def test_parse
  read_file tests/test_parse.py
  ...
```

## Setup (needs internet once)

```sh
brew install ollama
brew services start ollama      # keeps the model server running in the background
ollama pull qwen3:4b            # ~2.5 GB, the default model
./install.sh                    # puts `lantern` on your PATH
```

After that, everything works offline.

## Use

```sh
cd some/project
lantern                         # start a session
lantern "add a --verbose flag"  # start with a request
lantern -m qwen2.5-coder:7b     # pick a different model
lantern --yes                   # skip the allow prompts
```

In a session: `/clear` forgets the conversation, `/model NAME` switches models, `/exit` quits.
When lantern wants to edit a file or run a command it shows you exactly what, and you answer
`y` (yes), `n` (no) or `a` (always, for the rest of the session).

## Picking a model

Bigger models are smarter but slower and need more memory. Rough guide:

| RAM | Model | Download |
|---|---|---|
| 8 GB | `qwen3:4b` (default) | 2.5 GB |
| 8 GB, if you close other apps | `qwen2.5-coder:7b` | 4.7 GB |
| 16 GB+ | `qwen3:8b` or `qwen2.5-coder:14b` | 5–9 GB |

The model must support tool calling. Set a default with `export LANTERN_MODEL=qwen2.5-coder:7b`.
`LANTERN_CONTEXT` sets how many tokens the model sees at once (default 16384; lower it if you run out of memory).

## How it works

`lantern.py` is one file with no dependencies beyond Python 3. It sends the conversation to
Ollama's `/api/chat` on localhost with six tools (`list_dir`, `read_file`, `search`, `write_file`,
`edit_file`, `run`), runs whatever tools the model asks for, feeds the results back, and repeats
until the model answers.
