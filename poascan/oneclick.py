"""One-click MCP install links (Cursor, VS Code) and the Claude Code command for a remote HTTP MCP server."""
import base64, json
from html import escape as E
from urllib.parse import quote

def links(name, url):
    cur = base64.b64encode(json.dumps({"url": url}, separators=(",", ":")).encode()).decode()
    vsc = json.dumps({"name": name, "type": "http", "url": url}, separators=(",", ":"))
    return {"cursor": f"cursor://anysphere.cursor-deeplink/mcp/install?name={quote(name)}&config={quote(cur, safe='')}",
            "vscode": "vscode:mcp/install?" + quote(vsc, safe=""),
            "claude_code": f"claude mcp add --transport http {name} {url}"}

def html(name, url):
    l = links(name, url); c = l["claude_code"]
    return (f'<div class="apps mcpa"><a class="app" href="{E(l["cursor"])}" data-mcp="cursor">Cursor<span class="ab auto">Add</span></a>'
            f'<a class="app" href="{E(l["vscode"])}" data-mcp="vscode">VS Code<span class="ab auto">Add</span></a>'
            f'</div><div class="cmds"><div class="cmd" data-mcp="claude-code"><span class="lbl">Claude Code</span><code>{E(c)}</code>'
            f'<button class="cp" type="button" data-copy="{E(c)}" aria-label="Copy Claude Code command"><i></i></button></div></div>')
