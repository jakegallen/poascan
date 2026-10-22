"""MCP install options for a remote Streamable HTTP server. One-click deeplinks only where the client documents one:
Cursor (cursor.com/docs/context/mcp/install-links, web link cursor.com/install-mcp), VS Code and Insiders (code.visualstudio.com/docs/copilot/customization/mcp-servers),
Kiro (kiro.dev/docs/mcp/servers, web link kiro.dev/launch/mcp/add), Trae (docs.trae.ai/ide/mcp-server-install-links), Goose (block/goose deeplink.ts),
LM Studio (lmstudio.ai/docs/app/mcp/deeplink), Cherry Studio (CherryHQ/cherry-studio mcpInstall.ts). Everything else is a
copy-ready command or config: Claude Code, Codex (codex mcp add --url), Gemini CLI, Claude custom connector URL,
Windsurf (docs.windsurf.com/plugins/cascade/mcp), Cline (docs.cline.bot/mcp), Zed (zed.dev/docs/ai/mcp)."""
import base64, json
from html import escape as E
from urllib.parse import quote

def _j(o): return json.dumps(o, separators=(",", ":"))
def _b64(o): return base64.b64encode(_j(o).encode()).decode()

def links(name, url):
    vsc = quote(_j({"name": name, "type": "http", "url": url}), safe="")
    return {
        "cursor": f"https://cursor.com/install-mcp?name={quote(name)}&config={quote(_b64({'url': url}), safe='')}",
        "vscode": "vscode:mcp/install?" + vsc,
        "vscode_insiders": "vscode-insiders:mcp/install?" + vsc,
        "kiro": f"https://kiro.dev/launch/mcp/add?name={quote(name)}&config={quote(_j({'url': url, 'disabled': False, 'autoApprove': []}), safe='')}",
        "trae": f"trae://trae.ai-ide/mcp-import?type=http&name={quote(name)}&config={quote(_b64({'url': url}), safe='')}",
        "goose": f"goose://extension?type=streamable_http&url={quote(url, safe='')}&id={quote(name)}&name={quote(name)}&description={quote('Remote MCP server')}",
        "lmstudio": f"lmstudio://add_mcp?name={quote(name)}&config={quote(_b64({'url': url}), safe='')}",
        "cherry": "cherrystudio://mcp/install?servers=" + quote(_b64({"mcpServers": {name: {"name": name, "type": "streamableHttp", "baseUrl": url}}}), safe=""),
        "claude_code": f"claude mcp add --transport http {name} {url}",
        "codex": f"codex mcp add {name} --url {url}",
        "gemini": f"gemini mcp add --transport http {name} {url}",
        "claude": url,
        "windsurf": _j({"mcpServers": {name: {"serverUrl": url}}}),
        "cline": _j({"mcpServers": {name: {"type": "streamableHttp", "url": url}}}),
        "zed": _j({"context_servers": {name: {"url": url}}}),
    }

BUTTONS = [("cursor", "Cursor"), ("vscode", "VS Code"), ("lmstudio", "LM Studio"), ("goose", "Goose"),
           ("vscode_insiders", "VS Code Insiders"), ("kiro", "Kiro"), ("trae", "Trae"), ("cherry", "Cherry Studio")]
COPY = [("claude_code", "Claude Code"), ("codex", "Codex"), ("gemini", "Gemini CLI"), ("claude", "Claude connector"),
        ("windsurf", "Windsurf"), ("cline", "Cline"), ("zed", "Zed")]

WEB = {"cursor", "kiro"}  # official https install pages, opened in a new tab

def fallback(name, url):
    """What every Add button also copies, in the format that client pastes, so a click always leaves something usable."""
    srv = _j({"mcpServers": {name: {"url": url}}})
    return {"cursor": srv, "kiro": srv, "vscode": _j({"servers": {name: {"type": "http", "url": url}}}), "vscode_insiders": _j({"servers": {name: {"type": "http", "url": url}}}),
            "lmstudio": srv, "trae": srv, "goose": url,
            "cherry": _j({"mcpServers": {name: {"type": "streamableHttp", "baseUrl": url}}})}

def html(name, url):
    l = links(name, url)
    from .join import more, label
    fb = fallback(name, url)
    b = lambda k, n: (f'<a class="app" href="{E(l[k])}" data-mcp="{k.replace("_", "-")}"'
                      + (' target="_blank" rel="noopener noreferrer"' if k in WEB else "") + f' data-mcpcopy="{E(fb[k])}" data-app="{E(n)}"'
                      + f'>{label(n)}<span class="ab auto">Add</span></a>')
    btn, btn2 = "".join(b(k, n) for k, n in BUTTONS[:4]), "".join(b(k, n) for k, n in BUTTONS[4:])
    row = lambda k, n: (f'<div class="cmd" data-mcp="{k.replace("_", "-")}"><span class="lbl">{label(n)}</span><code>{E(l[k])}</code>'
                        f'<button class="cp" type="button" data-copy="{E(l[k])}" aria-label="Copy {n}"><i></i></button></div>')
    rows = "".join(row(k, n) for k, n in COPY)
    return (f'<div class="apps mcpa">{btn}</div>'
            + more("Other clients", f'<div class="apps mcpa">{btn2}</div><div class="cmds">{rows}</div>', "mcpm"))
