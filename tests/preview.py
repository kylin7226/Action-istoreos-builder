#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

ROOT = Path(__file__).resolve().parents[1]
PAGE = '''<!doctype html><meta charset="utf-8"><title>SamWaf LuCI — mock RPC preview</title>
<style>body{font:16px sans-serif;max-width:1000px;margin:2em auto;background:#f4f5f7;color:#20252b}.cbi-section{padding:1em;background:white;margin:1em 0;border-radius:6px}button,a.cbi-button{margin:.3em;padding:.5em}td{padding:.4em 1em}input{padding:.4em}#notice{white-space:pre-wrap;color:#a22}dialog{max-width:650px}pre{overflow:auto}</style>
<h1>本地模拟预览（不会调用设备服务）</h1>
<label><input id="readonly" type="checkbox">模拟只读账号</label>
<label><input id="fail" type="checkbox">模拟升级失败</label>
<div id="notice"></div><main id="app"></main>
<script>
window._ = text => text;
window.L = {hasViewPermission: () => !document.querySelector('#readonly').checked};
window.E = function(tag, attrs, children) {
  if (!attrs || typeof attrs !== 'object' || Array.isArray(attrs) || attrs instanceof Node) {children=attrs;attrs={};}
  const element=document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) {
    if(typeof value==='function') element.addEventListener(key,value);
    else if(key==='disabled') element.disabled=!!value;
    else if(key==='value') element.value=value;
    else element.setAttribute(key,value);
  }
  for(const child of (Array.isArray(children)?children:[children])) {
    if(child!=null) element.append(child instanceof Node?child:document.createTextNode(String(child)));
  }
  return element;
};
const callbacks=new Set();
setInterval(()=>callbacks.forEach(callback=>callback()),3000);
const poll={add:callback=>callbacks.add(callback),remove:callback=>callbacks.delete(callback)};
const ui={
 addNotification:(_,node)=>document.querySelector('#notice').replaceChildren(node),
 createHandlerFn:(self,name,arg)=>()=>self[name](arg),
 hideModal:()=>document.querySelector('dialog')?.remove(),
 showModal:(title,body)=>{ui.hideModal();const modal=E('dialog',[E('h3',title),...body]);document.body.append(modal);modal.showModal();}
};
let status={ok:true,running:true,pid:123,enabled:true,port:8766,version:'v1.3.24'};
let upgrade={ok:true,running:false,done:null,log:''}, ticks=0, target='';
const fs={exec:async(_,args)=>{
 let data=status;
 if(args[0]==='set_port'){status.port=Number(args[1]);data={ok:true,port:status.port,restarted:status.running};}
 if(args[0]==='stop')status.running=false;
 if(args[0]==='start'||args[0]==='restart')status.running=true;
 if(args[0]==='enable')status.enabled=true;
 if(args[0]==='disable')status.enabled=false;
 if(args[0]==='upgrade'){target=args[1];ticks=0;upgrade={ok:true,running:true,done:null,log:'模拟下载与备份'};data={ok:true};}
 if(args[0]==='upgrade_status'){
  if(upgrade.running&&++ticks>=2){upgrade.running=false;upgrade.done=!document.querySelector('#fail').checked;upgrade.log=upgrade.done?'模拟升级完成':'模拟升级失败，已恢复备份';if(upgrade.done)status.version=target;}
  data=upgrade;
 }
 return {code:0,stdout:JSON.stringify(data),stderr:''};
}};
(async()=>{
 const source=await(await fetch('/samwaf.js')).text();
 const page=new Function('view','fs','ui','poll',source)({extend:x=>x},fs,ui,poll);
 document.querySelector('#app').append(page.render(await page.load()));
 document.querySelector('#readonly').onchange=()=>page.setBusy(page._busy);
})().catch(error=>document.querySelector('#notice').textContent=error.stack);
</script>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.server.server_port == 8766:
            body, kind = b'<!doctype html><h1>Mock SamWaf console</h1>', 'text/html'
        elif self.path == '/samwaf.js':
            body, kind = (ROOT / 'files/www/luci-static/resources/view/samwaf.js').read_bytes(), 'text/javascript'
        elif self.path == '/':
            body, kind = PAGE.encode(), 'text/html'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    console = ThreadingHTTPServer(('127.0.0.1', 8766), Handler)
    threading.Thread(target=console.serve_forever, daemon=True).start()
    print('Mock LuCI preview: http://127.0.0.1:8765', flush=True)
    try:
        ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
    finally:
        console.shutdown()
