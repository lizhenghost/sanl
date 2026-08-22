"""API 文档页（本地化）：FastAPI 默认 /docs 引用 cdn.jsdelivr.net 的 swagger-ui 资源，
国内网络被墙导致白屏。改为读取同源 /openapi.json 自渲染，零外部依赖。"""


def register_local_docs(app):
    """挂载本地化 API 文档页"""

    @app.get("/docs", include_in_schema=False)
    async def local_docs():
        html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sanl API 文档</title>
<style>
:root{--bg:#f8fafc;--card:#fff;--bd:#e2e8f0;--tx:#0f172a;--mut:#64748b;--blu:#2563eb}
.dark{--bg:#0f172a;--card:#1e293b;--bd:#334155;--tx:#f1f5f9;--mut:#94a3b8}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--tx);padding:20px}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:22px;margin-bottom:4px}.sub{color:var(--mut);font-size:13px;margin-bottom:18px}
.bar{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}
input{flex:1;min-width:200px;padding:8px 12px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--tx)}
select,button{padding:8px 14px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--tx);cursor:pointer}
button.pri{background:var(--blu);color:#fff;border:none;font-weight:600}
.ep{background:var(--card);border:1px solid var(--bd);border-radius:10px;margin-bottom:8px;overflow:hidden}
.ep-h{display:flex;align-items:center;gap:10px;padding:11px 14px;cursor:pointer;flex-wrap:wrap}
.m{font-size:11px;font-weight:700;padding:3px 8px;border-radius:5px;color:#fff;min-width:52px;text-align:center}
.GET{background:#16a34a}.POST{background:#2563eb}.PUT{background:#d97706}.DELETE{background:#dc2626}
.path{font-family:ui-monospace,monospace;font-size:13px;font-weight:600}
.sum{color:var(--mut);font-size:12px;margin-left:auto}
.ep-b{display:none;padding:12px 14px;border-top:1px solid var(--bd)}
.ep.open .ep-b{display:block}
.params{font-size:12px;color:var(--mut);margin-bottom:10px;line-height:1.7}
.try input{padding:6px 10px;font-size:12px;width:auto}
.resp{margin-top:10px;background:var(--bg);border:1px solid var(--bd);border-radius:8px;padding:10px;font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap;max-height:320px;overflow:auto;display:none}
</style>
</head>
<body><div class="wrap">
<h1>📚 Sanl API 文档</h1>
<div class="sub">本地渲染 · 无外部 CDN 依赖 · 数据来自 /openapi.json — 点击端点展开在线调试</div>
<div class="bar">
  <select id="fmeth"><option value="">全部方法</option><option>GET</option><option>POST</option></select>
  <input id="fq" placeholder="搜索路径或说明…">
  <button class="pri" onclick="render()">🔍 筛选</button>
  <button onclick="location.reload()">刷新</button>
</div>
<div id="list">加载中…</div>
</div>
<script>
let SPEC=null;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){
  try{
    const r=await fetch('/openapi.json');SPEC=await r.json();render();
  }catch(e){document.getElementById('list').textContent='加载 openapi.json 失败: '+e;}
}
function render(){
  const q=document.getElementById('fq').value.toLowerCase(),m=document.getElementById('fmeth').value;
  const list=document.getElementById('list');let html='';
  for(const[p,methods]of Object.entries(SPEC.paths)){
    for(const[meth,op]of Object.entries(methods)){
      if(!['get','post','put','delete'].includes(meth))continue;
      if(m&&meth.toUpperCase()!==m)continue;
      const sum=op.summary||op.description||'';
      if(q&&!(p.toLowerCase().includes(q)||String(sum).toLowerCase().includes(q)))continue;
      const params=(op.parameters||[]).map(pp=>`${esc(pp.name)}${pp.required?'*':''}(${pp.schema&&pp.schema.type||''}): ${esc(pp.description||'')}`).join('<br>');
      html+=`<div class="ep" onclick="this.classList.toggle('open')">
        <div class="ep-h"><span class="m ${meth.toUpperCase()}">${meth.toUpperCase()}</span>
        <span class="path">${esc(p)}</span><span class="sum">${esc(String(sum).slice(0,60))}</span></div>
        <div class="ep-b" onclick="event.stopPropagation()">
          ${params?`<div class="params"><b>参数：</b><br>${params}</div>`:''}
          <div class="try"><input id="in-${btoa(p+meth).replace(/=/g,'')}" placeholder="?param=value&…">
          <button class="pri" onclick="tryIt('${p}','${meth}')">▶ 发送请求</button>
          <span style="font-size:11px;color:var(--mut)">写操作会真实执行，谨慎点击</span></div>
          <div class="resp" id="rs-${btoa(p+meth).replace(/=/g,'')}"></div>
        </div></div>`;
    }
  }
  list.innerHTML=html||'无匹配端点';
}
async function tryIt(p,meth){
  const k=btoa(p+meth).replace(/=/g,'');
  const extra=document.getElementById('in-'+k).value.trim();
  const box=document.getElementById('rs-'+k);
  box.style.display='block';box.textContent='⏳ 请求中…';
  try{
    const r=await fetch(p+(extra?(extra.startsWith('?')?extra:'?'+extra):''),{method:meth.toUpperCase()});
    const t=await r.text();
    let out=t;try{out=JSON.stringify(JSON.parse(t),null,2)}catch(e){}
    box.textContent=`HTTP ${r.status}\\n\\n${out.slice(0,4000)}`;
  }catch(e){box.textContent='❌ '+e;}
}
load();
</script></body></html>"""
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html)
