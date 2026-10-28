#!/usr/bin/env python3
"""lantern: an AI assistant that runs entirely on your own machine.

It talks to a model served by Ollama on localhost, so once the model is
downloaded it works with no internet at all. Ask it anything, like you would
Claude. When a task involves your files it can read, search and edit them and
run commands, and it asks before it changes anything.

    lantern                    start a session in the current folder
    lantern -m qwen3:8b        use a different model
    lantern "fix the tests"    start with a first message
    lantern --yes              don't ask before edits and commands
    lantern --show-thinking    print the model's reasoning as it thinks
"""
import argparse
import functools
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("LANTERN_MODEL", "qwen3:4b")
CONTEXT = int(os.environ.get("LANTERN_CONTEXT", "8192"))  # tokens the model can see at once
MAX_OUTPUT = 12000  # characters of tool output handed back to the model

DIM, BOLD, CYAN, YELLOW, RED, RESET = "\033[2m", "\033[1m", "\033[36m", "\033[33m", "\033[31m", "\033[0m"

SYSTEM = """You are lantern, a helpful AI assistant running offline on the user's computer.
Help with anything they ask: questions, explanations, writing, studying, planning, advice and code.
Talk like a friendly, knowledgeable person. You have no internet, so for recent events or facts
you're unsure of, say so rather than guess.

You are in the folder {cwd}. You have tools to read, search, write and edit files and to run
shell commands. Use them only when the request is about the user's files or needs a command run.
For greetings, questions and conversation, just answer; don't call any tools.

When working with files:
- Look before you change anything: list folders and read the files involved first.
- Make small, focused edits with edit_file. Use write_file only for new files or full rewrites.
- After a change, run the relevant command (tests, the script, a build) to check it works.
- Keep answers short and direct. Show code only when it helps.
- If you aren't sure what the user wants, ask."""

TOOLS = [
    {"name": "list_dir", "description": "List the files and folders in a directory.",
     "parameters": {"path": {"type": "string", "description": "Directory to list, default '.'"}}, "required": []},
    {"name": "read_file", "description": "Read a text file. Lines are numbered.",
     "parameters": {"path": {"type": "string"},
                    "start": {"type": "integer", "description": "First line to read, default 1"},
                    "count": {"type": "integer", "description": "How many lines, default 400"}},
     "required": ["path"]},
    {"name": "search", "description": "Search file contents for a regular expression, like grep -rn.",
     "parameters": {"pattern": {"type": "string"},
                    "path": {"type": "string", "description": "File or folder to search, default '.'"}},
     "required": ["pattern"]},
    {"name": "write_file", "description": "Create a file, or replace a file's entire contents.",
     "parameters": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    {"name": "edit_file", "description": "Replace one exact piece of text in a file. old must appear exactly once.",
     "parameters": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
     "required": ["path", "old", "new"]},
    {"name": "run", "description": "Run a shell command in the working folder and return its output.",
     "parameters": {"command": {"type": "string"}}, "required": ["command"]},
]
CHANGES = {"write_file", "edit_file", "run"}  # tools that ask first


def schema(tool):
    return {"type": "function", "function": {
        "name": tool["name"], "description": tool["description"],
        "parameters": {"type": "object", "properties": tool["parameters"], "required": tool["required"]}}}


def clip(text):
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n... ({len(text) - MAX_OUTPUT} more characters cut)"


def list_dir(path="."):
    names = sorted(os.listdir(path))
    return "\n".join(n + ("/" if os.path.isdir(os.path.join(path, n)) else "") for n in names if n != ".git") or "(empty)"


def read_file(path, start=1, count=400):
    with open(path, errors="replace") as f:
        lines = f.readlines()
    start = max(int(start), 1)
    chunk = lines[start - 1:start - 1 + int(count)]
    out = "".join(f"{start + i:5}  {line}" for i, line in enumerate(chunk))
    if start - 1 + len(chunk) < len(lines):
        out += f"\n({len(lines)} lines in total; read more with start={start + len(chunk)})"
    return out or "(empty file)"


def search(pattern, path="."):
    r = subprocess.run(["grep", "-rnIE", "--exclude-dir=.git", "--exclude-dir=node_modules", pattern, path],
                       capture_output=True, text=True)
    return r.stdout or "no matches"


def write_file(path, content):
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return f"wrote {path} ({content.count(chr(10)) + 1} lines)"


def edit_file(path, old, new):
    with open(path) as f:
        text = f.read()
    n = text.count(old)
    if n != 1:
        return f"error: old text appears {n} times in {path}; it must appear exactly once. Read the file and try again."
    with open(path, "w") as f:
        f.write(text.replace(old, new))
    return f"edited {path}"


def run(command):
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "error: command timed out after 5 minutes"
    out = (r.stdout + r.stderr).strip()
    return f"exit code {r.returncode}\n{out}" if out else f"exit code {r.returncode}"


FUNCS = {"list_dir": list_dir, "read_file": read_file, "search": search,
         "write_file": write_file, "edit_file": edit_file, "run": run}


def preview(name, args):
    if name == "run":
        return f"$ {args.get('command', '')}"
    if name == "edit_file":
        old = "\n".join(f"{RED}- {l}{RESET}" for l in str(args.get("old", "")).splitlines())
        new = "\n".join(f"{CYAN}+ {l}{RESET}" for l in str(args.get("new", "")).splitlines())
        return f"edit {args.get('path')}\n{old}\n{new}"
    if name == "write_file":
        content = str(args.get("content", ""))
        head = "\n".join(content.splitlines()[:15])
        more = content.count("\n") - 15
        return f"write {args.get('path')}\n{DIM}{head}{RESET}" + (f"\n{DIM}... {more} more lines{RESET}" if more > 0 else "")
    return f"{name} {json.dumps(args)}"


class Session:
    def __init__(self, model, yes, show_thinking=False):
        self.show_thinking = show_thinking
        self.model, self.yes = model, yes
        self.messages = [{"role": "system", "content": SYSTEM.format(cwd=os.getcwd())}]

    def allowed(self, name, args):
        print(f"\n{YELLOW}{preview(name, args)}{RESET}")
        if self.yes:
            return True
        answer = input(f"{BOLD}allow? [y]es / [n]o / [a]lways: {RESET}").strip().lower()
        if answer.startswith("a"):
            self.yes = True
        return answer[:1] in ("y", "a")

    def call(self, name, args):
        if name not in FUNCS:
            return f"error: there is no tool called {name}"
        if name in CHANGES and not self.allowed(name, args):
            return "the user declined this. Ask them what they'd like instead."
        if name not in CHANGES:
            print(f"{DIM}  {name} {' '.join(str(v) for v in args.values())[:100]}{RESET}")
        try:
            return clip(str(FUNCS[name](**args)))
        except TypeError as e:
            return f"error: bad arguments for {name}: {e}"
        except Exception as e:
            return f"error: {e}"

    def chat(self):
        """Stream one model reply. Returns the assistant message."""
        body = {"model": self.model, "messages": self.messages, "tools": [schema(t) for t in TOOLS],
                "stream": True, "think": thinks(self.model), "options": {"num_ctx": CONTEXT}}
        req = urllib.request.Request(HOST + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        content, calls, thought = "", [], False
        start, status = time.time(), not self.show_thinking

        def clear():  # erase the "thinking..." line before printing anything real
            nonlocal status
            if status:
                print("\r\033[K", end="", flush=True)
                status = False

        if status:
            print(f"{DIM}thinking...{RESET}", end="", flush=True)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                for line in r:
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise RuntimeError(chunk["error"])
                    msg = chunk.get("message", {})
                    if msg.get("thinking"):  # reasoning: hidden behind a timer unless --show-thinking
                        if self.show_thinking:
                            print(DIM + msg["thinking"] + RESET, end="", flush=True)
                            thought = True
                        elif status:
                            print(f"\r{DIM}thinking... {time.time() - start:.0f}s{RESET}", end="", flush=True)
                    if msg.get("content"):
                        clear()
                        if thought:
                            print()
                            thought = False
                        if not content:
                            msg["content"] = msg["content"].lstrip()
                        content += msg["content"]
                        print(msg["content"], end="", flush=True)
                    calls += msg.get("tool_calls") or []
        finally:
            clear()
        if content or thought:
            print()
        return {"role": "assistant", "content": content, "tool_calls": calls}

    def turn(self, text):
        self.messages.append({"role": "user", "content": text})
        for _ in range(40):  # keep going until the model stops asking for tools
            reply = self.chat()
            self.messages.append(reply)
            if not reply["tool_calls"]:
                return
            for c in reply["tool_calls"]:
                fn = c["function"]
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args or "{}")
                result = self.call(fn["name"], args)
                self.messages.append({"role": "tool", "tool_name": fn["name"], "content": result})
        print(f"{DIM}(stopped after 40 steps){RESET}")


@functools.lru_cache
def thinks(model):
    """Whether the model reasons before answering. Thinking-only models like qwen3:4b
    ignore think=False and mix their reasoning into the answer, so ask for it separately."""
    req = urllib.request.Request(HOST + "/api/show", data=json.dumps({"model": model}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return "thinking" in (json.load(r).get("capabilities") or [])


def check_server(model):
    try:
        with urllib.request.urlopen(HOST + "/api/tags", timeout=5) as r:
            have = [m["name"] for m in json.load(r)["models"]]
    except (urllib.error.URLError, OSError):
        sys.exit(f"can't reach Ollama at {HOST}. Start it in another tab with:  ollama serve")
    if model not in have and model + ":latest" not in have:
        sys.exit(f"model {model} isn't downloaded. Get it (needs internet once) with:  ollama pull {model}\n"
                 f"downloaded models: {', '.join(have) or 'none'}")


def main():
    ap = argparse.ArgumentParser(description="offline AI assistant")
    ap.add_argument("prompt", nargs="*", help="first message")
    ap.add_argument("-m", "--model", default=MODEL)
    ap.add_argument("-y", "--yes", action="store_true", help="don't ask before edits and commands")
    ap.add_argument("--show-thinking", action="store_true", help="print the model's reasoning")
    args = ap.parse_args()
    check_server(args.model)

    s = Session(args.model, args.yes, args.show_thinking)
    print(f"{BOLD}🏮 lantern{RESET} {DIM}{args.model} · {os.getcwd()} · /help for commands{RESET}")
    first = " ".join(args.prompt)
    while True:
        try:
            text = first or input(f"\n{BOLD}{CYAN}> {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        first = ""
        if not text:
            continue
        if text in ("/exit", "/quit"):
            return
        if text == "/help":
            print("/clear  forget the conversation\n/model NAME  switch models\n/exit  quit")
            continue
        if text == "/clear":
            s = Session(s.model, s.yes, s.show_thinking)
            print(f"{DIM}cleared{RESET}")
            continue
        if text.startswith("/model"):
            name = text.split(maxsplit=1)[1] if " " in text else ""
            if name:
                check_server(name)
                s.model = name
            print(f"{DIM}model: {s.model}{RESET}")
            continue
        try:
            s.turn(text)
        except KeyboardInterrupt:
            print(f"\n{DIM}(interrupted){RESET}")
        except Exception as e:
            print(f"{RED}error: {e}{RESET}")


if __name__ == "__main__":
    main()
