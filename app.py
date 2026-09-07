# vllm-chat — a small, stateless Streamlit front-end for local vLLM (OpenAI-compatible) servers.
# https://github.com/mike-nott/vllm-chat
# Stateless: session memory only, no files, no telemetry. Config: servers.toml next to this file.
import base64, json, os, time, tomllib, requests, streamlit as st
import streamlit.components.v1 as components

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "servers.toml")
if os.path.exists(CFG_PATH):
    with open(CFG_PATH, "rb") as f: CFG = tomllib.load(f)
else:                                   # quick start: no servers.toml → vLLM on localhost
    CFG = {"title": "vLLM", "servers": [{"name": "local vLLM", "base_url": os.environ.get("VLLM_URL", "http://127.0.0.1:8000")}]}
SERVERS = CFG["servers"]                      # [{name, base_url, profile}]
PROFILES = {                                  # what the model family understands
    "glm":     dict(effort=True,  thinking_toggle=False, passback="reasoning"),
    "qwen":    dict(effort=False, thinking_toggle=True,  passback="reasoning"),
    "generic": dict(effort=False, thinking_toggle=False, passback=None),
}
MCP_CFG = CFG.get("mcp")                      # optional [mcp] url + token → web tools, OFF by default
MAX_TOOL_ROUNDS = 6

class MCP:
    """Minimal MCP Streamable-HTTP client (JSON or SSE responses)."""
    def __init__(self, url, token):
        import itertools
        self.url, self.n, self.sid = url, itertools.count(1), None
        self.h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "vllm-chat", "version": "1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    def _post(self, payload):
        h = dict(self.h)
        if self.sid: h["Mcp-Session-Id"] = self.sid
        r = requests.post(self.url, headers=h, data=json.dumps(payload), timeout=120); r.raise_for_status()
        self.sid = r.headers.get("Mcp-Session-Id", self.sid)
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            msgs = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
            return next((m for m in reversed(msgs) if "result" in m or "error" in m), None)
        return r.json() if r.text.strip() else None
    def _rpc(self, method, params):
        m = self._post({"jsonrpc": "2.0", "id": next(self.n), "method": method, "params": params})
        if m and "error" in m: raise RuntimeError(m["error"].get("message", str(m["error"])))
        return m["result"] if m else None
    def tools(self): return self._rpc("tools/list", {})["tools"]
    def call(self, name, args):
        try:
            res = self._rpc("tools/call", {"name": name, "arguments": args})
            return "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text") or json.dumps(res)[:6000]
        except Exception as e: return f"tool error: {e}"

def openai_tools(mcp_tools):
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", "")[:1200],
             "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}} for t in mcp_tools]

def elide(body):
    """Request JSON for the raw view: base64 images shortened."""
    b = json.loads(json.dumps(body))
    for m in b.get("messages", []):
        if isinstance(m.get("content"), list):
            for p in m["content"]:
                if p.get("type") == "image_url": p["image_url"] = {"url": f"<image {len(p['image_url']['url']) * 3 // 4 // 1024} KB>"}
    return b
st.set_page_config(page_title=CFG.get("title", "vLLM"), page_icon="⚡", layout="centered", initial_sidebar_state="expanded")

ss = st.session_state
ss.setdefault("msgs", []); ss.setdefault("effort", "low"); ss.setdefault("temperature", 1.0); ss.setdefault("top_p", 0.95)
ss.setdefault("max_tokens", 4096); ss.setdefault("show_meta", False); ss.setdefault("server", SERVERS[0]["name"]); ss.setdefault("thinking", True); ss.setdefault("system", ""); ss.setdefault("raw", False); ss.setdefault("tools_on", False)
ss.setdefault("mode", "dark" if st.query_params.get("dark") else "light")

LIGHT = dict(bg="#ffffff", side="#f7f7f8", text="#1f1f1f", muted="#8a8a8a", bubble="#f0f0f0", input="#ffffff", border="#e4e4e7", accent="#3f3f46", accent_fg="#ffffff", card="#ffffff", ctl="#9a9a9a")
DARK  = dict(bg="#1c1c1e", side="#141416", text="#e6e6e6", muted="#8b8b8f", bubble="#2a2a2e", input="#242427", border="#2e2e32", accent="#d4d4d8", accent_fg="#1c1c1e", card="#1f1f22", ctl="#6b6b70")
P = DARK if ss.mode == "dark" else LIGHT

st.markdown(f"""<style>
html, body, .stApp, [data-testid="stSidebar"], .stMarkdown, button, input, textarea, [data-testid="stMarkdownContainer"] p {{font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;}}
[data-testid="stHeader"] {{background: transparent;}} [data-testid="stToolbarActions"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], [data-testid="stStatusWidget"], [data-testid="stDecoration"], #MainMenu, footer {{display: none;}}
[data-testid="stExpandSidebarButton"] {{color: {P['muted']} !important; background: transparent !important;}} [data-testid="stExpandSidebarButton"] * {{color: inherit !important;}}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{background: {P['bg']}; color: {P['text']};}}
.block-container {{max-width: 46rem; padding-top: 2.5rem; padding-bottom: 7rem;}}
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3, [data-testid="stWidgetLabel"] p, .stRadio label p, [data-testid="stExpander"] summary p {{color: {P['text']};}}
[data-testid="stMarkdownContainer"] p {{line-height: 1.65; font-size: 0.98rem;}}
/* sidebar */
[data-testid="stSidebar"], [data-testid="stSidebar"] > div {{background: {P['side']}; border-right: 1px solid {P['border']};}}
[data-testid="stSidebarUserContent"] {{padding: 0.4rem 1.2rem 1.2rem; height: 100%; margin-top: -2.4rem;}}
[data-testid="stSidebarUserContent"] > div > div {{display: flex; flex-direction: column; min-height: calc(100vh - 6.2rem);}}
.brand {{font-weight: 700; font-size: 1.6rem; letter-spacing: -0.02em; color: {P['text']}; display: flex; align-items: center; gap: 0.55rem; margin-top: -0.2rem;}}
.brand .dot {{width: 0.62rem; height: 0.62rem; border-radius: 50%; display: inline-block; box-shadow: 0 0 0 3px rgba(0,0,0,0.04);}}
.dot.ok {{background: #34c759;}} .dot.bad {{background: #ff3b30;}}
.model {{font-size: 0.72rem; color: {P['muted']}; margin: 0.25rem 0 1.6rem; word-break: break-all;}}
.section {{font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; color: {P['muted']}; font-weight: 600; margin: 0.6rem 0 0.2rem;}}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {{font-size: 0.82rem; font-weight: 500;}}
[data-testid="stSidebar"] hr {{margin: 0.6rem 0; border-color: {P['border']};}}
[data-testid="stSlider"], [data-testid="stToggle"], .stToggle {{opacity: 0.72;}}
[data-testid="stSlider"] [role="slider"] {{background: {P['ctl']} !important; border-color: {P['ctl']} !important;}}
.st-key-mode_ctl {{margin-top: auto !important;}}
[data-testid="stButtonGroup"] [role="radiogroup"] {{gap: 0.35rem; flex-wrap: nowrap;}}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {{border-radius: 0.7rem !important; border: 1px solid {P['border']} !important; background: {P['card']} !important; color: {P['text']} !important; font-size: 0.82rem !important; padding: 0.2rem 0.75rem !important; min-height: 0 !important;}}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"] {{background: {P['bubble']} !important; color: {P['accent']} !important; border-color: {P['accent']} !important;}}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] * {{color: inherit !important; fill: currentColor !important; font-size: 0.74rem !important;}}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {{padding: 0.15rem 0.6rem !important;}}
[data-testid="stSliderThumbValue"] p, [data-testid="stSliderTickBar"] p {{font-size: 0.72rem !important;}}
[data-testid="stSliderThumbValue"] {{color: {P['text']} !important;}}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {{background: {P['card']}; color: {P['text']}; border: 1px solid {P['border']};}}
/* chat */
[data-testid="stChatMessage"] {{background: transparent; border: none; padding: 0.3rem 0;}}
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {{display: none;}}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{justify-content: flex-end;}}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {{
  background: {P['bubble']}; border-radius: 1.2rem; padding: 0.7rem 1.1rem; max-width: 78%; margin-left: auto; width: fit-content;}}
[data-testid="stExpander"] {{border: none; box-shadow: none; font-size: 0.85rem;}}
[data-testid="stExpander"] details {{border: none; background: transparent;}} [data-testid="stExpander"] summary, [data-testid="stExpander"] summary:hover, [data-testid="stExpander"] details[open] summary {{padding: 0.1rem 0; color: {P['muted']}; background: transparent !important;}}
[data-testid="stExpanderDetails"] {{color: {P['muted']}; border-left: 2px solid {P['border']}; padding-left: 0.8rem;}}
[data-testid="stSidebar"] [data-testid="stExpanderDetails"] {{border: none !important; padding-left: 0; padding-right: 0;}}
[data-testid="stTextArea"] textarea, [data-testid="stTextAreaRootElement"] {{background: {P['input']} !important; color: {P['text']} !important; border-color: {P['border']} !important;}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary, [data-testid="stSidebar"] [data-testid="stExpander"] details {{border: none !important; box-shadow: none !important;}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p, [data-testid="stSidebar"] [data-testid="stExpander"] summary span {{font-size: 0.82rem !important; font-weight: 500;}}
.turnmeta {{color: {P['muted']}; font-size: 0.72rem; margin-top: -0.3rem;}}
.hello {{text-align: center; margin-top: 24vh; font-size: 1.85rem; font-weight: 600; letter-spacing: -0.02em; color: {P['text']};}}
/* composer */
[data-testid="stChatInput"], [data-testid="stChatInput"] > div {{background: {P['input']} !important; border: 1px solid {P['border']} !important; border-radius: 1.4rem !important; box-shadow: 0 4px 24px rgba(0,0,0,{'0.35' if ss.mode=='dark' else '0.06'});}}
.stChatInput textarea {{background: transparent !important; color: {P['text']} !important;}} .stChatInput textarea::placeholder {{color: {P['muted']};}}
[data-testid="stChatInputSubmitButton"] {{background: {P['accent']}; color: {P['accent_fg']}; border-radius: 50%;}} [data-testid="stChatInputSubmitButton"]:hover {{opacity: 0.85;}}
code {{background: {P['bubble']}; color: {P['text']};}} pre, [data-testid="stCode"] {{background: {P['bubble']} !important;}}
[data-testid="stCode"] pre, [data-testid="stCode"] code, [data-testid="stCode"] span, [data-testid="stText"] {{color: {P['text']} !important; opacity: 1 !important;}}
[data-testid="stExpanderDetails"] [data-testid="stText"] {{font-size: 0.8rem; white-space: pre-wrap;}}
</style>""", unsafe_allow_html=True)

@st.cache_data(ttl=30)
def model_id(base):
    return requests.get(f"{base}/v1/models", timeout=5).json()["data"][0]["id"]

def cache_counters(base):
    h = q = 0.0
    try:
        for ln in requests.get(f"{base}/metrics", timeout=5).text.splitlines():
            if ln.startswith("vllm:prefix_cache_hits_total"): h += float(ln.rsplit(" ", 1)[1])
            elif ln.startswith("vllm:prefix_cache_queries_total"): q += float(ln.rsplit(" ", 1)[1])
    except Exception: pass
    return h, q

with st.sidebar:
    SRV = next(x for x in SERVERS if x["name"] == ss.server); BASE = SRV["base_url"].rstrip("/")
    try: MODEL = model_id(BASE); ok = True
    except Exception: MODEL = "server unreachable"; ok = False
    prof_name = SRV.get("profile") or ("glm" if "glm" in MODEL.lower() else "qwen" if "qwen" in MODEL.lower() else "generic")   # guess from the model id when not set
    PROF = PROFILES.get(prof_name, PROFILES["generic"])
    st.markdown(f'<div class="brand"><span class="dot {"ok" if ok else "bad"}" title="{"server healthy" if ok else "server unreachable"}"></span>{CFG.get("title", "vLLM")}</div>', unsafe_allow_html=True)
    if len(SERVERS) > 1:
        pick = st.selectbox("Server", [x["name"] for x in SERVERS], index=[x["name"] for x in SERVERS].index(ss.server), label_visibility="collapsed")
        if pick != ss.server: ss.server = pick; ss.msgs = []; st.rerun()
    st.markdown(f'<div class="model">{MODEL}</div>', unsafe_allow_html=True)
    if not ok: st.stop()
    st.markdown('<div class="section">Settings</div>', unsafe_allow_html=True)
    with st.expander("System prompt" + (" ●" if ss.system.strip() else ""), expanded=False):
        ss.system = st.text_area("System prompt", ss.system, height=120, label_visibility="collapsed")
    if PROF["effort"]:
        eff = st.segmented_control("Reasoning effort", ["low", "high", "max"], default=ss.effort, key="effort_ctl", format_func=str.capitalize)
        if eff: ss.effort = eff
    if PROF["thinking_toggle"]: ss.thinking = st.toggle("Thinking", ss.thinking)
    ss.max_tokens = st.select_slider("Max tokens", [1024, 4096, 8192, 16384, 32768], value=ss.max_tokens)
    ss.temperature = st.slider("Temperature", 0.0, 1.5, ss.temperature, 0.05)
    ss.top_p = st.slider("Top-p", 0.1, 1.0, ss.top_p, 0.01)
    ss.show_meta = st.toggle("Show timing details", ss.show_meta)
    ss.raw = st.toggle("Raw view", ss.raw)
    if MCP_CFG and PROF["passback"]:
        ss.tools_on = st.toggle("Web MCP", ss.tools_on)
    mode = st.segmented_control("Appearance", ["light", "dark"], default=ss.mode, key="mode_ctl",
                                format_func=lambda m: ":material/light_mode:" if m == "light" else ":material/dark_mode:", label_visibility="collapsed")
    if mode and mode != ss.mode: ss.mode = mode; st.rerun()

hello = st.empty()
if not ss.msgs: hello.markdown('<div class="hello">How can I help?</div>', unsafe_allow_html=True)

def tools_html(rounds):
    import html
    box = f'background:{P["bubble"]};color:{P["text"]};white-space:pre-wrap;word-break:break-word;font-size:0.78rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;padding:0.5rem 0.7rem;border-radius:8px;margin:0.3rem 0 0.6rem;max-height:320px;overflow:auto'
    summ = f'cursor:pointer;color:{P["muted"]};font-size:0.85rem'
    esc = lambda t: html.escape(t).replace("\n", "<br>")
    out = []
    for r in rounds:
        if r.get("reasoning"): out.append(f'<details style="margin:0.15rem 0"><summary style="{summ}">Thought</summary><div style="{box};font-family:inherit">{esc(r["reasoning"])}</div></details>')
        for c in r.get("calls", []):
            sig = f"{c['name']}({', '.join(f'{k}={json.dumps(v)[:40]}' for k, v in (c['args'] or {}).items())})"
            body = json.dumps(c["args"], indent=1)[:1500] + "\n\n" + (c.get("result") or "…")[:3000]
            out.append(f'<details style="margin:0.15rem 0"><summary style="{summ}">🔧 {html.escape(sig)}</summary><div style="{box}">{esc(body)}</div></details>')
    return "".join(out)          # one HTML block, no blank lines: markdown must not split it

def render_tools(rounds):
    n = sum(len(r.get("calls", [])) for r in rounds)
    if n:
        with st.expander(f"Tools · {n} call{'s' if n > 1 else ''}", expanded=False): st.markdown(tools_html(rounds), unsafe_allow_html=True)

for m in ss.msgs:
    with st.chat_message(m["role"]):
        if m.get("rounds"): render_tools(m["rounds"])
        if m.get("reasoning"):
            with st.expander(m.get("thought_label", "Thought"), expanded=False): st.markdown(m["reasoning"])
        c = m.get("content")
        if isinstance(c, list):
            for p in c:
                if p["type"] == "image_url": st.image(p["image_url"]["url"], width=260)
            st.markdown("\n".join(p["text"] for p in c if p["type"] == "text"))
        else: st.markdown(c)
        if m.get("meta") and ss.show_meta: st.markdown(f'<div class="turnmeta">{m["meta"]}</div>', unsafe_allow_html=True)
        if m.get("raw") and ss.raw:
            with st.expander("Raw", expanded=False):
                st.code(json.dumps(m["raw"]["request"], indent=1)[:12000], language="json"); st.code(json.dumps(m["raw"]["response"], indent=1)[:3000], language="json")

sub = st.chat_input(f"Message {CFG.get('title', 'vLLM')}…", accept_file="multiple", file_type=["png", "jpg", "jpeg", "webp"])
if sub:
    hello.empty()
    text, files = (sub.text, sub.files) if hasattr(sub, "text") else (sub, [])
    if files:
        parts = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(f.getvalue()).decode()}} for f in files]
        parts.append({"type": "text", "text": text or "Describe this."}); ss.msgs.append({"role": "user", "content": parts})
    else: ss.msgs.append({"role": "user", "content": text})
    with st.chat_message("user"):
        for f in files: st.image(f.getvalue(), width=260)
        st.markdown(text)
    kw = {}
    if PROF["effort"]: kw["reasoning_effort"] = ss.effort
    if PROF["thinking_toggle"]: kw["enable_thinking"] = ss.thinking
    tools = None
    if ss.tools_on and MCP_CFG:
        try:
            if "mcp" not in ss: ss.mcp = MCP(MCP_CFG["url"], MCP_CFG["token"]); ss.mcp_tools = openai_tools(ss.mcp.tools())
            tools = ss.mcp_tools
        except Exception as e: st.warning(f"web-mcp unavailable: {e}"); tools = None

    h0, q0 = cache_counters(BASE)
    stop_slot = st.empty()
    with stop_slot.container():   # swap the send arrow for a stop square while streaming
        st.markdown(f"""<style>[data-testid="stChatInputSubmitButton"] {{visibility: hidden;}}
.st-key-stop {{position: fixed; z-index: 1001; width: auto; opacity: 0;}}
.st-key-stop button {{width: 34px; height: 34px; min-height: 0; padding: 0; border-radius: 50%; border: none; background: {P['accent']}; color: {P['accent_fg']}; font-size: 0.8rem; line-height: 1;}}
</style>""", unsafe_allow_html=True)
        st.button("■", key="stop", help="Stop generating")
        components.html("""<script>
(function(){const d=window.parent.document;function place(){const a=d.querySelector('[data-testid="stChatInputSubmitButton"]');const s=d.querySelector('.st-key-stop');if(!a||!s)return;const r=a.getBoundingClientRect();
s.style.left=(r.left+r.width/2-17)+'px';s.style.top=(r.top+r.height/2-17)+'px';s.style.bottom='auto';s.style.right='auto';s.style.opacity='1';}
place();const t=setInterval(place,250);setTimeout(()=>clearInterval(t),1800000);})();</script>""", height=0)
    pending = {"role": "assistant", "content": "", "reasoning": "", "thought_label": "Thought", "meta": "", "rounds": [], "raw": None}; ss.msgs.append(pending); stats = {}

    def build_wire():
        w = [{"role": "system", "content": ss.system.strip()}] if ss.system.strip() else []
        for m in ss.msgs:
            if m["role"] == "assistant":
                if m is pending and not m.get("rounds"): continue        # the turn being generated: only its finished tool rounds go on the wire
                for r in m.get("rounds", []):
                    am = {"role": "assistant", "content": "", "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}} for c in r["calls"]]}
                    if r.get("reasoning") and PROF["passback"]: am[PROF["passback"]] = r["reasoning"]
                    w.append(am); w += [{"role": "tool", "tool_call_id": c["id"], "content": c.get("result") or ""} for c in r["calls"]]
                if m is not pending and (m.get("content") or not m.get("rounds")):
                    am = {"role": "assistant", "content": m.get("content") or ""}
                    if m.get("reasoning") and PROF["passback"]: am[PROF["passback"]] = m["reasoning"]
                    w.append(am)
            else: w.append({"role": m["role"], "content": m["content"]})
        return w
    def stream_once(body, rslot, cslot):
        """One streamed completion. Returns (reasoning, content, tool_calls, finish, usage, t_first, t_first_content)."""
        rtxt = ctxt = ""; calls = {}; finish = None; usage = None; first = None; tfc = None; stats["rounds"] = stats.get("rounds", 0) + 1
        with requests.post(f"{BASE}/v1/chat/completions", json=body, stream=True, timeout=1800) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith(b"data: ") or line.strip() == b"data: [DONE]": continue
                d = json.loads(line[6:])
                if d.get("usage"): usage = d["usage"]
                ch = (d.get("choices") or [{}])[0]; de = ch.get("delta", {}) or {}
                if ch.get("finish_reason"): finish = ch["finish_reason"]
                if de.get("reasoning"): rtxt += de["reasoning"]; pending["reasoning"] = rtxt; rslot.markdown(rtxt)
                if de.get("content"):
                    if tfc is None: tfc = time.time()
                    ctxt += de["content"]; pending["content"] = ctxt; cslot.markdown(ctxt)
                for tc in de.get("tool_calls") or []:
                    c = calls.setdefault(tc.get("index", 0), {"id": tc.get("id") or f"call_{tc.get('index', 0)}", "name": "", "args": ""})
                    if tc.get("id"): c["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"): c["name"] += fn["name"]
                    if fn.get("arguments"): c["args"] += fn["arguments"]
                if first is None and (de.get("reasoning") or de.get("content") or de.get("tool_calls")): first = time.time()
        if first: stats["gen_s"] = stats.get("gen_s", 0) + (time.time() - first); stats["ct"] = stats.get("ct", 0) + (usage or {}).get("completion_tokens", 0)
        return rtxt, ctxt, [calls[k] for k in sorted(calls)], finish, usage, first, tfc

    with st.chat_message("assistant"):
        t0 = time.time(); first_any = None; tfirst_content = None; usage = None; body = None; finish = None; ctxt = rtxt = ""; last_calls = []
        tools_slot = st.empty(); think_slot = st.empty(); cslot = st.empty()
        try:
            for rnd in range(MAX_TOOL_ROUNDS + 1):
                body = {"model": MODEL, "messages": build_wire(), "temperature": ss.temperature, "top_p": ss.top_p, "max_tokens": ss.max_tokens,
                        "stream": True, "stream_options": {"include_usage": True}, **({"chat_template_kwargs": kw} if kw else {}),
                        **({"tools": tools, "tool_choice": "auto"} if tools and rnd < MAX_TOOL_ROUNDS else {})}
                with think_slot.container(): rbox = st.expander("Thinking…", expanded=False); rslot = rbox.empty()
                rtxt, ctxt, calls, finish, usage, first, tfc = stream_once(body, rslot, cslot)
                first_any = first_any or first; tfirst_content = tfirst_content or tfc
                pending["reasoning"] = rtxt; pending["content"] = ctxt
                if not calls: break
                # execute the tool calls, record the round, loop
                round_rec = {"reasoning": rtxt, "thought_label": "Thought", "calls": []}
                for c in calls:
                    try: args = json.loads(c["args"] or "{}")
                    except Exception: args = {"_raw": c["args"]}
                    round_rec["calls"].append({"id": c["id"], "name": c["name"], "args": args, "result": None})
                    with tools_slot.container(): render_tools(pending["rounds"] + [round_rec])      # show the call while it runs
                    round_rec["calls"][-1]["result"] = ss.mcp.call(c["name"], args) if tools else "tools disabled"
                think_slot.empty(); cslot.empty()
                last_calls = calls; pending["rounds"].append(round_rec); pending["reasoning"] = ""; pending["content"] = ""
                with tools_slot.container(): render_tools(pending["rounds"])
        except Exception as e:
            st.error(f"Something went wrong: {e}"); st.stop()
        end = time.time(); ct = stats.get("ct", 0)
        thought_s = ((tfirst_content or end) - (first_any or t0)) if rtxt else 0
        label = f"Thought for {thought_s:.0f}s" if rtxt else "Thought"
        h1, q1 = cache_counters(BASE); dq = q1 - q0
        meta = f"{(first_any or end) - t0:.1f}s to first token · {ct / max(stats.get("gen_s", 0), 1e-6):.0f} tok/s · {100 * (h1 - h0) / dq if dq else 0:.0f}% cached" + (f" · {sum(len(r['calls']) for r in pending['rounds'])} tool calls" if pending["rounds"] else "")
        meta_slot = st.empty()
        if ss.show_meta: meta_slot.markdown(f'<div class="turnmeta">{meta}</div>', unsafe_allow_html=True)
    pending.update({"content": ctxt, "reasoning": rtxt, "thought_label": label, "meta": meta,
                    "raw": {"request": elide(body), "response": {"finish_reason": finish, "usage": usage, "completion_tokens_all_rounds": ct, "rounds": len(pending["rounds"]) + 1}}})
    stop_slot.empty(); st.rerun()
