"""CF Worker deployment generator -- inspired by edgetunnel's lightweight approach.

Generates a Cloudflare Workers-compatible JS script that relays VLESS traffic,
plus config links for client deployment. Zero binary dependency.
"""
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..schema import repository

logger = logging.getLogger(__name__)

router = APIRouter()


class WorkerGenerateRequest(BaseModel):
    node_count: int = Field(20, ge=1, le=100, description="Reference node count")
    user_id: Optional[str] = Field(None, description="VLESS UUID (random if empty)")
    proxy_ip: str = Field("", description="Failover IP (optional)")
    max_channels: int = Field(100, ge=10, le=500, description="Max concurrent channels")
    include_nodes: bool = Field(True, description="Include reference node list")


class WorkerGenerateResponse(BaseModel):
    ok: bool
    script: str = ""
    config_link: str = ""
    worker_host: str = ""
    node_count: int = 0
    nodes: List[dict] = []
    error: str = ""


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=WorkerGenerateResponse)
async def generate_worker(req: WorkerGenerateRequest):
    """Generate a CF Workers script for V2Ray relay (edgetunnel-style)."""
    try:
        nodes = []
        if req.include_nodes:
            with repository.get_connection() as conn:
                rows = conn.execute(
                    """SELECT node_type, node_data, node_name, latency, country
                       FROM nodes
                       WHERE node_type IN ('vless', 'vmess')
                         AND (node_data LIKE '%"network": "ws"%'
                              OR node_data LIKE '%"network":"ws"%')
                         AND status = 'active'
                         AND latency IS NOT NULL
                       ORDER BY latency ASC, score DESC
                       LIMIT ?""",
                    (min(req.node_count, 20),),
                ).fetchall()
            for row in rows:
                try:
                    nd = json.loads(row["node_data"]) if isinstance(row["node_data"], str) else row["node_data"]
                    nodes.append({
                        "name": row["node_name"],
                        "type": row["node_type"],
                        "server": nd.get("server", ""),
                        "port": nd.get("port", 443),
                        "uuid": nd.get("uuid", ""),
                        "latency": row["latency"],
                        "country": row["country"] or "",
                    })
                except Exception:
                    continue

        uid = req.user_id or str(uuid.uuid4())
        ws_path = secrets.token_hex(8)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        script = _build_script(uid, ws_path, len(nodes), req.proxy_ip,
                               req.max_channels, now, nodes)

        config_link = (
            "vless://" + uid + "@"
            "{YOUR_WORKER_HOST}:443"
            "?encryption=none&security=tls&sni={YOUR_WORKER_HOST}"
            "&fp=randomized&type=ws&host={YOUR_WORKER_HOST}"
            "&path=/" + ws_path + "#sanl-cf-relay"
        )

        return WorkerGenerateResponse(
            ok=True, script=script, config_link=config_link,
            worker_host="{YOUR_WORKER_HOST}", node_count=len(nodes), nodes=nodes,
        )
    except Exception as e:
        logger.exception("[edgetunnel] generate failed")
        return WorkerGenerateResponse(ok=False, error=f"{type(e).__name__}: {e}")


@router.get("/config-example")
async def config_example():
    """Return a sample worker script and deployment instructions."""
    uid = "d342d11e-d424-4583-b36e-524ab1f0afa4"
    ws_path = "demo"
    script = _build_script(uid, ws_path, 0, "", 100, "2026-01-01T00:00:00Z", [])
    config_link = (
        "vless://" + uid + "@{YOUR_HOST}:443"
        "?encryption=none&security=tls&sni={YOUR_HOST}"
        "&fp=randomized&type=ws&host={YOUR_HOST}&path=/" + ws_path
        + "#sanl-demo"
    )
    return {
        "script": script,
        "config_link": config_link,
        "deploy_steps": [
            "1. Call POST /api/edgetunnel/generate to get your script",
            "2. Go to https://dash.cloudflare.com -> Workers & Pages -> Create",
            "3. Paste the script and deploy",
            "4. Replace YOUR_WORKER_HOST with your actual worker URL",
            "5. Use config_link to configure your client",
        ],
        "limits": (
            "Free tier: 100k requests/day, 30s execution timeout. "
            "Paid Worker: $5/mo for higher limits."
        ),
    }


# ---------------------------------------------------------------------------
# Script builder
# ---------------------------------------------------------------------------

def _build_script(
    user_id: str, ws_path: str, node_count: int,
    proxy_ip: str, max_channels: int,
    generated_at: str, nodes: List[dict],
) -> str:
    """Build the complete CF Worker JS script."""
    nodes_json = json.dumps(nodes, ensure_ascii=False)
    proxy_ip_val = '"' + proxy_ip + '"' if proxy_ip else '""'

    lines = [
        "// Sanl CF Worker -- auto-generated",
        "// Deploy: paste into Cloudflare Workers Dashboard",
        f"// Generated: {generated_at}",
        f"// Reference nodes: {node_count}",
        "",
        "import { connect } from 'cloudflare:sockets';",
        "",
        f'const USER_ID = "{user_id}";',
        f"const PROXY_IP = {proxy_ip_val};",
        f"const MAX_CHANNELS = {max_channels};",
        f'const WS_PATH = "/{ws_path}";',
        "",
        "export default {",
        "  async fetch(request) {",
        "    try {",
        "      const upgrade = request.headers.get('Upgrade');",
        "      if (!upgrade || upgrade !== 'websocket') return handleHttp(request);",
        "      return await handleWs(request);",
        "    } catch (e) {",
        "      return new Response(JSON.stringify({ error: e.message }), {",
        "        status: 500, headers: { 'Content-Type': 'application/json' }",
        "      });",
        "    }",
        "  },",
        "};",
        "",
        "function handleHttp(request) {",
        "  const url = new URL(request.url);",
        "  if (url.pathname === '/') {",
        "    return new Response(JSON.stringify({",
        f"      service: 'sanl-cf-worker', node_count: {node_count},",
        f"      generated_at: '{generated_at}', uuid: USER_ID, ws_path: WS_PATH,",
        "      cf: request.cf ? { country: request.cf.country, colo: request.cf.colo } : null,",
        "    }), { headers: { 'Content-Type': 'application/json' } });",
        "  }",
        '  if (url.pathname === "/" + USER_ID) {',
        "    const host = request.headers.get('Host') || 'your-worker.workers.dev';",
        "    return new Response(genConfig(USER_ID, host), {",
        "      status: 200, headers: { 'Content-Type': 'text/plain;charset=utf-8' },",
        "    });",
        "  }",
        '  if (url.pathname === \'/api/nodes\') {',
        f"    return new Response(JSON.stringify({nodes_json}), {{",
        "      headers: { 'Content-Type': 'application/json' }",
        "    });",
        "  }",
        "  return new Response('Not Found', { status: 404 });",
        "}",
        "",
        "async function handleWs(request) {",
        "  const pair = new WebSocketPair();",
        "  const [client, ws] = Object.values(pair);",
        "  ws.accept();",
        "  const reader = request.body ? request.body.getReader() : null;",
        "  if (!reader) { ws.close(); return new Response('no body', {status: 400}); }",
        "",
        "  (async () => {",
        "    try {",
        "      while (true) {",
        "        const { done, value } = await reader.read();",
        "        if (done) break;",
        "        if (value && value.byteLength >= 24) {",
        "          const { addr, port, data, isUdp } = parseVless(value, USER_ID);",
        "          if (addr) {",
        "            if (isUdp && port === 53) { await dnsForward(ws, data); }",
        "            else if (!isUdp) { await tcpForward(addr, port, data, ws); }",
        "          }",
        "        }",
        "      }",
        "    } catch (e) { console.log('ws read error:', e.message); }",
        "    ws.close();",
        "  })();",
        "",
        "  return new Response(null, { status: 101, webSocket: client });",
        "}",
        "",
        "async function tcpForward(addr, port, data, ws) {",
        "  const sock = connect({ hostname: addr, port });",
        "  const w = sock.writable.getWriter();",
        "  await w.write(data); w.releaseLock();",
        "  sock.readable.pipeTo(new WritableStream({",
        "    async write(chunk) { if (ws.readyState === 1) ws.send(chunk); }",
        "  })).catch(() => sock.close());",
        "}",
        "",
        "async function dnsForward(ws, data) {",
        "  const resp = await fetch('https://1.1.1.1/dns-query', {",
        "    method: 'POST', headers: { 'content-type': 'application/dns-message' }, body: data,",
        "  });",
        "  const result = await resp.arrayBuffer();",
        "  if (ws.readyState === 1) ws.send(result);",
        "}",
        "",
        "function parseVless(buf, userId) {",
        "  if (buf.byteLength < 24) return {};",
        "  const id = buf.slice(1, 17);",
        "  if (String.fromCharCode(...new Uint8Array(id)) !== userId) return {};",
        "  const optLen = buf[17];",
        "  const cmd = buf[18 + optLen];",
        "  const port = new DataView(buf).getUint16(18 + optLen + 1);",
        "  const addrType = buf[19 + optLen];",
        "  let addr = '', end = 20 + optLen + 1;",
        "  if (addrType === 1) {",
        "    addr = [...buf.slice(end, end + 4)].join('.');",
        "  } else if (addrType === 2) {",
        "    const len = buf[end];",
        "    addr = new TextDecoder().decode(buf.slice(end + 1, end + 1 + len));",
        "    end += 1 + len;",
        "  } else if (addrType === 3) {",
        "    const v = new DataView(buf, end, 16);",
        "    const parts = [];",
        "    for (let i = 0; i < 8; i++) parts.push(v.getUint16(i * 2).toString(16));",
        "    addr = parts.join(':');",
        "    end += 16;",
        "  }",
        "  return { addr, port, data: buf.slice(end), isUdp: cmd === 2 };",
        "}",
        "",
        "function genConfig(uid, host) {",
        '  const path = WS_PATH;',
        "  return `",
        "################################################################",
        "V2Ray Config (Sanl CF Worker)",
        "UUID: ${uid}",
        "Path: ${path}",
        f"Generated: {generated_at}",
        "################################################################",
        "vless://${uid}@${host}:443?encryption=none&security=tls&sni=${host}&fp=randomized&type=ws&host=${host}&path=${encodeURIComponent(path)}#${host}",
        "",
        "################################################################",
        "Clash Meta",
        "################################################################",
        "- type: vless",
        "  name: Sanl-CF-Relay",
        "  server: ${host}",
        "  port: 443",
        "  uuid: ${uid}",
        "  network: ws",
        "  tls: true",
        "  udp: true",
        "  sni: ${host}",
        "  client-fingerprint: chrome",
        "  ws-opts:",
        '    path: "${path}"',
        "    headers:",
        "      host: ${host}",
        "`;",
        "}",
    ]
    return "\n".join(lines)
