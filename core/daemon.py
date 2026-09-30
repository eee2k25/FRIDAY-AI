"""Long-lived HTTP daemon for FRIDAY."""
from __future__ import annotations

import json
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools import memory_tools

from .agent_loop import AgentLoop
from .llm_engine import LLMEngine
from .memory import FridayMemory
from .tool_registry import ToolRegistry

_INDEX_HTML = b'''<!doctype html><html><head><title>FRIDAY Command Center</title><meta name="viewport" content="width=device-width"><style>body{margin:0;background:#07111f;color:#dbeafe;font:15px system-ui}main{max-width:1000px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;align-items:center}h1{color:#67e8f9}.grid{display:grid;grid-template-columns:2fr 1fr;gap:18px}.card{background:#0d1b2e;border:1px solid #1e3a5f;border-radius:12px;padding:18px;margin:14px 0}#chat{height:360px;overflow:auto;white-space:pre-wrap}input{background:#10243b;color:white;border:1px solid #31577d;border-radius:6px;padding:12px;width:70%}button{background:#0891b2;color:white;border:0;border-radius:6px;padding:12px;margin:4px;cursor:pointer}.muted{color:#93a4b8}</style></head><body><main><header><h1>F.R.I.D.A.Y.</h1><span id="health" class="muted">checking...</span></header><div class="grid"><section><div class="card"><div id="chat"></div><input id="q" placeholder="Ask FRIDAY"><button onclick="ask()">Send</button><button onclick="listen()">Speak</button></div></section><aside><div class="card"><h3>System</h3><pre id="status">Loading...</pre></div><div class="card"><h3>Profile</h3><pre id="profile">Loading...</pre></div></aside></div></main><script>
const chat=document.getElementById('chat');function line(who,text){chat.textContent+=who+': '+text+'\\n\\n';chat.scrollTop=chat.scrollHeight}
async function ask(t){t=t||document.getElementById('q').value;document.getElementById('q').value='';if(!t)return;line('You',t);let r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t})});let j=await r.json();line('FRIDAY',j.reply||j.error||'No response');if(window.speechSynthesis&&j.reply)speechSynthesis.speak(new SpeechSynthesisUtterance(j.reply))}
function listen(){let R=window.SpeechRecognition||window.webkitSpeechRecognition;if(!R)return alert('Speech input is not supported');let r=new R;r.onresult=e=>ask(e.results[0][0].transcript);r.start()}
async function refresh(){let h=await fetch('/health');document.getElementById('health').textContent=(await h.json()).ok?'ONLINE':'OFFLINE';let s=await fetch('/status');document.getElementById('status').textContent=JSON.stringify(await s.json(),null,2);let p=await fetch('/profile');document.getElementById('profile').textContent=(await p.json()).profile}refresh();setInterval(refresh,10000)
</script></body></html>'''


class FridayDaemon:
    def __init__(self, host='127.0.0.1', port=8765, token=None, pid_file=None):
        self.host = host
        self.port = port
        self.token = token or os.getenv('FRIDAY_DAEMON_TOKEN')
        self.pid_file = Path(pid_file or os.getenv('FRIDAY_PID_FILE', 'friday.pid'))
        self.lock = threading.RLock()
        self.memory = FridayMemory()
        self.engine = LLMEngine()
        self.registry = ToolRegistry()
        memory_tools.bind_memory(self.memory)
        self.registry.auto_discover()
        from .skills import SkillManager
        self.skills = SkillManager(self.registry)
        self.registry._skill_manager = self.skills
        from tools import skill_tools
        skill_tools.bind_manager(self.skills)
        self.agent = AgentLoop(self.engine, self.registry, self.memory)
        self.server = None

    def status(self):
        return {
            'version': __import__('config').FRIDAY_VERSION,
            'pid': os.getpid(),
            'tools': len(self.registry.tools),
            'model': self.engine.get_model_status(),
        }

    def serve(self):
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        if self.pid_file.exists():
            try:
                old = int(self.pid_file.read_text())
                os.kill(old, 0)
                raise RuntimeError(f'daemon already running (pid {old})')
            except ProcessLookupError:
                pass
            except ValueError:
                pass
        self.pid_file.write_text(str(os.getpid()))
        daemon = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def auth(self):
                return (
                    not daemon.token
                    or self.headers.get('Authorization', '') == 'Bearer ' + daemon.token
                )

            def send(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == '/health':
                    return self.send(200, {'ok': True, 'pid': os.getpid()})
                if not self.auth():
                    return self.send(401, {'error': 'unauthorized'})
                if self.path == '/status':
                    return self.send(200, daemon.status())
                if self.path == '/profile':
                    from tools.profile_tools import get_profile
                    return self.send(200, {'profile': get_profile()})
                if self.path == '/voice':
                    return self.send(200, {
                        'browser_speech_input': True,
                        'browser_speech_output': True,
                        'elevenlabs': bool(
                            os.getenv('ELEVENLABS_API_KEY') and os.getenv('ELEVENLABS_VOICE_ID')
                        ),
                    })
                if self.path == '/':
                    html = _INDEX_HTML
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Content-Length', str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return
                self.send(404, {'error': 'not found'})

            def do_POST(self):
                if not self.auth():
                    return self.send(401, {'error': 'unauthorized'})
                if self.path in ('/telegram/webhook', '/slack/events', '/imessage/webhook'):
                    try:
                        data = json.loads(
                            self.rfile.read(int(self.headers.get('Content-Length', '0')))
                        )
                        if self.path.endswith('telegram/webhook'):
                            text = ((data.get('message') or {}).get('text') or '')
                            sid = 'telegram:' + str(
                                (data.get('message') or {}).get('chat', {}).get('id', 'unknown')
                            )
                        elif self.path.endswith('imessage/webhook'):
                            text = data.get('text') or data.get('message', '')
                            sender = (
                                data.get('from')
                                or data.get('sender')
                                or data.get('phone')
                                or 'unknown'
                            )
                            sid = 'imessage:' + str(sender)
                        else:
                            if data.get('type') == 'url_verification':
                                return self.send(200, {'challenge': data.get('challenge', '')})
                            text = data.get('event', {}).get('text', '')
                            sid = 'slack:' + str(data.get('event', {}).get('user', 'unknown'))
                        if not text:
                            return self.send(200, {'ok': True})
                        with daemon.lock:
                            reply = daemon.agent.run(text, sid)
                        return self.send(200, {'reply': reply})
                    except Exception as e:
                        return self.send(400, {'error': str(e)})
                if self.path != '/chat':
                    return self.send(404, {'error': 'not found'})
                try:
                    data = json.loads(
                        self.rfile.read(int(self.headers.get('Content-Length', '0')))
                    )
                    text = data.get('message', data.get('text', ''))
                    sid = data.get('session_id', 'daemon')
                    if not text:
                        return self.send(400, {'error': 'message is required'})
                    with daemon.lock:
                        reply = daemon.agent.run(text, sid)
                    self.send(200, {'reply': reply, 'session_id': sid})
                except Exception as e:
                    self.send(500, {'error': str(e)})

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)

        def stop(*_):
            self.server.shutdown()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            self.server.serve_forever()
        finally:
            self.server.server_close()
            try:
                self.pid_file.unlink()
            except FileNotFoundError:
                pass


def run_daemon(**kwargs):
    FridayDaemon(**kwargs).serve()
