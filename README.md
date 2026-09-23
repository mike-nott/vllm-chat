# vllm-chat

A small, stateless chat front-end for a local [vLLM](https://github.com/vllm-project/vllm) server. One Python file,
no database, no accounts, nothing logged. Point it at `http://<host>:8000`, open it in a browser, talk to the model.

![light](docs/shot-light.png)

Built for testing models on home inference boxes (DGX Spark, RTX rigs) where you want a quick, clean UI rather than a
full platform. Works with any OpenAI-compatible `/v1/chat/completions` endpoint, llama-server included; the extras
(thinking level, cache-hit %) light up when the server is vLLM.

## Features

- Streaming replies with a stop button in the composer, "Thought for Ns" expander for reasoning models
- Image attachments (＋ in the composer) for vision models
- Model-family profiles with a Thinking level control: GLM Low/High/Max, Qwen Off/Low/Medium/XHigh, generic. Guessed from the model id, or set per server
- Max tokens, temperature, top-p, optional system prompt
- Timing line per reply: time to first token, tok/s, prefix-cache hit % (from vLLM `/metrics`)
- Raw view: the exact request JSON and response summary under each reply
- Optional tool calling against any number of MCP servers ([web-mcp](https://github.com/mike-nott/web-mcp) for the
  web, [comfy-mcp](https://github.com/mike-nott/comfy-mcp) for image and video generation); one sidebar toggle each, all off by default
- Several servers in one instance with a sidebar picker; light and dark; a status dot that says whether the server is up
- Zero persistence: conversation lives in the browser session only. Refresh to start over

## Quick start

```bash
git clone https://github.com/mike-nott/vllm-chat ~/vllm-chat
cd ~/vllm-chat
pip install -r requirements.txt        # or: uv tool install --with requests --with watchdog streamlit
bash run.sh                            # http://<this-host>:8501 → talks to http://127.0.0.1:8000
```

vLLM on another host or port: `VLLM_URL=http://192.168.1.10:8000 bash run.sh`, or create `servers.toml` (next section).

## Configure servers

```bash
cp servers.example.toml servers.toml
```

```toml
title = "vLLM"

[[servers]]
name = "GLM box"
base_url = "http://192.168.1.10:8000"
profile = "glm"          # glm | qwen | generic — optional, guessed from the model id if omitted

[[servers]]
name = "Qwen box"
base_url = "http://192.168.1.11:8000"

[[servers]]
name = "llama-server box"
base_url = "http://192.168.1.12:8080"
profile = "qwen"
reasoning_key = "reasoning_content"   # optional — see below
```

| profile | sidebar control | what is sent |
|---|---|---|
| `glm` | Thinking level Low / High / Max | `chat_template_kwargs.reasoning_effort`, prior reasoning passed back as `reasoning` |
| `qwen` | Thinking level Off / Low / Medium / XHigh | `chat_template_kwargs.enable_thinking` (Off = `false`) and `reasoning_effort` for the other levels, prior reasoning passed back |
| `generic` | none | plain OpenAI chat |

`reasoning_key` overrides the field prior reasoning is passed back in, which the profiles default to `reasoning`.
llama-server expects `reasoning_content`. Incoming streams are read either way, so this is only about the passback.

`tool_result_max_chars` at the top level caps how much of a tool result is fed back to the model (default 12000);
anything longer is truncated with a note. Prompt processing is the slow part on small boxes, so a long page fetch
costs more than it is worth.

`servers.toml` is git-ignored, so `git pull` never overwrites it. The app re-reads it on every page load.

## Run as a service (port 80)

```bash
bash install.sh              # or PORT=8501 bash install.sh
```

Installs streamlit (via `uv` if present, else `pip --user`), creates `servers.toml` from the example if missing, renders
`vllm-chat.service` for your user and directory, and enables it. Port 80 works without root through
`AmbientCapabilities=CAP_NET_BIND_SERVICE`. Updating later is `git pull`: streamlit hot-reloads `app.py`
(that is what `watchdog` is for), so no restart is needed.

## Tools (MCP)

One `[[mcp]]` block per server in `servers.toml`, each with its own sidebar toggle named after it:

```toml
[[mcp]]
name = "Web-MCP"
url = "https://your-worker.example.workers.dev/mcp"
token = "your-bearer-token"

[[mcp]]
name = "Comfy-MCP"
url = "http://127.0.0.1:8765/mcp"
token = "your-bearer-token"
timeout = 300                  # seconds one tool call may take; default 120

[mcp.tool_defaults.generate_image]
steps = 20                     # filled in when the model omits the argument
```

Every toggle starts off. One with no `url`/`token` is greyed out with a tooltip saying what to add, and they all stay
greyed out for the `generic` profile. Turn on as many as you like: their tools are merged into one list and passed as
OpenAI `tools` with `tool_choice: auto`, and if two servers export the same tool name the one listed first in
`servers.toml` wins. Streamed tool calls go back over MCP Streamable HTTP as `role: tool` messages, up to
`max_tool_rounds` rounds (default 10 — a video render polls `wait_for_job` over several of them). Every call, its
arguments and its result sit in one collapsed **Tools · N calls** row above the reply.

Tool results that carry images — a [comfy-mcp](https://github.com/mike-nott/comfy-mcp) render, say — show up as
previews under that row. They are displayed, not sent back to the model: the model gets the text part, which for
comfy-mcp includes the path the full-size file was saved to **on the machine running the MCP server**.

To keep full-size files off that machine entirely, run comfy-mcp 0.2.2+ with `save_policy = "never"`. It then returns
a one-shot `download: comfy://result/<token>` handle instead of saving. vllm-chat fetches each file straight away
(`GET <mcp origin>/dl/<token>`, with the same bearer token), keeps the bytes in the browser session only, and shows a
**Download** button under the preview. The model sees a "delivered to the user as a download" note, never the handle.
Nothing reaches disk on either server; refresh the page and the files are gone. Since the fetch is server-side,
comfy-mcp can stay on `127.0.0.1` when it runs on the same box as vllm-chat.

Two servers it was built against: [web-mcp](https://github.com/mike-nott/web-mcp) (Reddit, X, YouTube, web search,
page fetch) and [comfy-mcp](https://github.com/mike-nott/comfy-mcp) (Qwen Image 2.1, MiniMax H3 video), the latter
started with `COMFY_MCP_HTTP_TOKEN=... comfy-mcp --http`. Any Streamable HTTP endpoint with bearer auth works.

A single legacy `[mcp]` table still works and shows up as **Web-MCP**.

## Privacy

Nothing is written to disk. Conversation state is Streamlit session state in the browser tab. Streamlit usage
statistics are off. vLLM's own access log records method, path and status, not prompt content. The MCP token, if you
use one, lives in plain text in `servers.toml`, which is git-ignored for that reason.

## Files

| file | purpose |
|---|---|
| `app.py` | the whole app |
| `servers.example.toml` | template for `servers.toml` |
| `.streamlit/config.toml` | base theme (greys) |
| `vllm-chat.service` | systemd unit template, rendered by `install.sh` |
| `install.sh` / `run.sh` | service install / quick start |
| `requirements.txt` | streamlit, requests, watchdog |

## Troubleshooting

- Red dot, "server offline": `curl <base_url>/v1/models` from the box running vllm-chat. An amber dot ("server
  starting up") means the port is refusing connections or the model is still loading — give it a moment.
- No Thinking level control: the profile was guessed as `generic`. Set `profile` explicitly.
- Reasoning shows while streaming but the model loses it next turn: set `reasoning_key = "reasoning_content"` for
  llama-server servers.
- An MCP toggle greyed out: that `[[mcp]]` block has no url or token (hover it for the hint), or the profile is
  `generic`. "<name> unavailable": bad url or token, or the server is not running.
- A tool call times out: raise `timeout` on that `[[mcp]]` block. Long renders should be started with a tool that
  returns a job id and polled instead.
- Port 80 already in use: `PORT=8501 bash install.sh`.
- Edits to `app.py` not showing: `watchdog` is not installed in the streamlit environment; install it and restart.

## Notes

Streamlit 1.63. The look is plain CSS on Streamlit's test ids, so a Streamlit upgrade can move things. Dark mode is
`?dark=1` or the switch at the bottom of the sidebar.
