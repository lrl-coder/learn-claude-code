#!/usr/bin/env python3
"""
Minimal Agent Template - Copy and customize this.

This is the simplest possible working agent (~80 lines).
It has everything you need: 3 tools + loop.

Usage:
    1. Set OPENAI_API_KEY environment variable
    2. python minimal-agent.py
    3. Type commands, 'q' to quit
"""

from openai import OpenAI
from pathlib import Path
import json
import shutil
import subprocess
import os

# Configuration
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("MODEL_NAME", "gpt-6-astra")
WORKDIR = Path.cwd()

# System prompt - keep it simple
SYSTEM = f"""You are a coding agent at {WORKDIR}.

Rules:
- Use tools to complete tasks
- Prefer action over explanation
- Summarize what you did when done"""

# Minimal tool set - add more as needed
TOOLS = [
    {
        "type": "function",
        "name": "bash",
        "description": "Run shell command",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "Read file contents",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Write content to file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
]


def bash_argv(command: str) -> list[str]:
    bash = os.getenv("BASH_PATH") or shutil.which("bash")
    if not bash and os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "bash.exe"
        bash = str(candidate) if candidate.is_file() else None
    if not bash:
        raise FileNotFoundError("Bash not found. Install Git Bash or set BASH_PATH.")
    return [bash, "-lc", command]


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool and return result."""
    if name == "bash":
        try:
            r = subprocess.run(
                bash_argv(args["command"]), shell=False,
                stdin=subprocess.DEVNULL, cwd=WORKDIR,
                capture_output=True, text=True, errors="replace", timeout=60
            )
            return (r.stdout + r.stderr).strip() or "(empty)"
        except subprocess.TimeoutExpired:
            return "Error: Timeout"

    if name == "read_file":
        try:
            return (WORKDIR / args["path"]).read_text(encoding="utf-8")[:50000]
        except Exception as e:
            return f"Error: {e}"

    if name == "write_file":
        try:
            p = WORKDIR / args["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"Wrote {len(args['content'])} bytes to {args['path']}"
        except Exception as e:
            return f"Error: {e}"

    return f"Unknown tool: {name}"


def agent(prompt: str, history: list = None) -> str:
    """Run the agent loop."""
    if history is None:
        history = []

    history.append({"role": "user", "content": prompt})

    while True:
        response = client.responses.create(
            model=MODEL,
            instructions=SYSTEM,
            input=history,
            tools=TOOLS,
            max_output_tokens=8000,
        )

        history.extend(response.output)
        tool_calls = [item for item in response.output
                      if item.type == "function_call"]
        if not tool_calls:
            return response.output_text

        # Execute tools
        for call in tool_calls:
            arguments = json.loads(call.arguments)
            print(f"> {call.name}: {arguments}")
            output = execute_tool(call.name, arguments)
            print(f"  {output[:100]}...")
            history.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": output,
            })


if __name__ == "__main__":
    print(f"Minimal Agent - {WORKDIR}")
    print("Type 'q' to quit.\n")

    history = []
    while True:
        try:
            query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query in ("q", "quit", "exit", ""):
            break
        print(agent(query, history))
        print()
