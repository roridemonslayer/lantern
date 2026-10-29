# 🏮 lantern

An AI assistant that runs entirely on your own laptop, like an offline Claude. Ask it anything, or have it write and fix code for you. No internet, no API key, no account.

lantern works like Claude Code in your terminal: you ask for something, and it reads your files, writes new code, edits what's there and runs commands to check its work. It asks before every edit or command. The model runs locally through [Ollama](https://ollama.com), so once the model is downloaded you can use it on a plane.

```
$ lantern
🏮 lantern qwen3:4b-instruct · ~/my-project · /help for commands

> why does test_parse fail?
  search def test_parse
  read_file tests/test_parse.py
  ...
```

## What it can do

**Write code.** Ask for a script, a function, a new feature or a whole small project and it creates the files for you.

```
> make a python script that renames every photo in this folder by the date it was taken
> add a --verbose flag to cli.py
> write tests for utils.py
```

**Fix and change existing code.** It reads the files involved, makes small targeted edits, then runs your tests or the program to check the change works. If something fails, it reads the error and tries again, taking up to 40 steps on one request.

```
> why does test_parse fail?
> the app crashes when the input file is empty, fix it
> rename get_user to fetch_user everywhere
```

**Understand a project.** It can list folders, read files and search the code (like `grep`), so you can ask about code you didn't write.

```
> what does this repo do?
> where is the login handled?
```

**Run commands.** Tests, builds, scripts, git, installs: anything you'd type in a terminal, run in the current folder. It gets the output back and uses it.

**Answer anything else.** Questions, explanations, studying, writing, planning, advice. For plain conversation it just answers without touching your files. It has no internet, so it says when it isn't sure about recent facts.

**Stay in your control.** Before it writes a file, edits one or runs a command, it shows you exactly what it will do: the command, a red/green diff of the edit, or the first lines of a new file. You answer `y` (yes), `n` (no) or `a` (always, for the rest of the session). If you say no, it asks what you'd like instead. Reading and searching don't need permission.

**Stay quick.** Answers stream in as they're written. Models that reason first show a `thinking... 12s` timer instead of filling the screen (use `--show-thinking` to see the reasoning).

## Setup (needs internet once)

```sh
brew install ollama
ollama pull qwen3:4b-instruct   # ~2.5 GB, the default model (no thinking step, so it answers fast)
./install.sh                    # puts `lantern` on your PATH
```

After that, everything works offline. You don't need to run `ollama serve`: lantern starts the Ollama server itself if it isn't already running (its log goes to `~/.ollama/lantern-serve.log`).

## Use

```sh
cd some/project
lantern                         # start a session in this folder
lantern "add a --verbose flag"  # start with a request
lantern -m qwen2.5-coder:7b     # pick a different model
lantern --yes                   # skip the allow prompts
lantern --show-thinking         # print the model's reasoning as it thinks
```

lantern starts in the folder you run it from, so `cd` into your project first. It can still open any other path you name, including `~` paths like `~/notes/todo.md`.

In a session:

| Command | What it does |
|---|---|
| `/help` | list the commands |
| `/clear` | forget the conversation and start fresh |
| `/model NAME` | switch to another downloaded model |
| `/exit` | quit (or Ctrl+D) |

## Picking a model

Bigger models are smarter but slower and need more memory. For coding, the `qwen2.5-coder` models are the strongest at each size. Rough guide:

| RAM | Model | Download |
|---|---|---|
| 8 GB | `qwen3:4b-instruct` (default), or `qwen3:4b` for slower step-by-step reasoning | 2.5 GB |
| 8 GB, if you close other apps | `qwen2.5-coder:7b` | 4.7 GB |
| 16 GB+ | `qwen3:8b` or `qwen2.5-coder:14b` | 5–9 GB |

The model must support tool calling. If you pick one you haven't downloaded, lantern tells you the `ollama pull` command and lists the models you have.

## Settings

| Variable | Default | What it does |
|---|---|---|
| `LANTERN_MODEL` | `qwen3:4b-instruct` | the model to use |
| `LANTERN_CONTEXT` | `8192` | tokens the model sees at once; 8192 keeps a 4B model fully on the GPU of an 8 GB Mac, raise it on bigger machines |
| `OLLAMA_HOST` | `http://localhost:11434` | where the Ollama server is |

For example: `export LANTERN_MODEL=qwen2.5-coder:7b` in your `~/.zshrc`.

## How it works

`lantern.py` is one file with no dependencies beyond Python 3. It sends the conversation to
Ollama's `/api/chat` on localhost with six tools, runs whatever tools the model asks for, feeds the
results back, and repeats until the model answers:

| Tool | Asks first? |
|---|---|
| `list_dir`: list a folder | no |
| `read_file`: read a file with line numbers, 400 lines at a time | no |
| `search`: regex search across files (skips `.git` and `node_modules`) | no |
| `write_file`: create a file or replace its contents | yes |
| `edit_file`: replace one exact piece of text in a file | yes |
| `run`: run a shell command (5 minute limit) | yes |

Long tool output is cut to 12,000 characters so it fits in a small model's memory.
