"""Long-lived HTTP daemon for FRIDAY."""
from __future__ import annotations
import json, os, signal, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .memory import FridayMemory
from .llm_engine import LLMEngine
from .tool_registry import ToolRegistry
from .agent_loop import AgentLoop
from tools import memory_tools

class FridayDaemon:
    def __init__(self, host='127.0.0.1', port=8765, token=None, pid_file=None):
        self.host, self.port, self.token = host, port, token or os.getenv('FRIDAY_DAEMON_TOKEN')
        self.pid_file = Path(pid_file or os.getenv('FRIDAY_PID_FILE','friday.pid'))
        self.lock = threading.RLock(); self.memory=FridayMemory(); self.engine=LLMEngine()
        self.registry=ToolRegistry(); memory_tools.bind_memory(self.memory); self.registry.auto_discover()
        self.agent=AgentLoop(self.engine,self.registry,self.memory); self.server=None
    def status(self):
        return {'version': __import__('config').FRIDAY_VERSION,'pid':os.getpid(),'tools':len(self.registry.tools),'model':self.engine.get_model_status()}
    def serve(self):
        self.pid_file.parent.mkdir(parents=True,exist_ok=True)
        if self.pid_file.exists():
            try:
                old=int(self.pid_file.read_text()); os.kill(old,0)
                raise RuntimeError(f'daemon already running (pid {old})')
            except ProcessLookupError: pass
            except ValueError: pass
        self.pid_file.write_text(str(os.getpid()))
        daemon=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def auth(self):
                return not daemon.token or self.headers.get('Authorization','') == 'Bearer '+daemon.token
            def send(self, code, obj):
                raw=json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def do_GET(self):
                if self.path=='/health': return self.send(200,{'ok':True,'pid':os.getpid()})
                if not self.auth(): return self.send(401,{'error':'unauthorized'})
                if self.path=='/status': return self.send(200,daemon.status())
                if self.path=='/': return self.send(200,{'service':'FRIDAY','status':'online',**daemon.status()})
                self.send(404,{'error':'not found'})
            def do_POST(self):
                if not self.auth(): return self.send(401,{'error':'unauthorized'})
                if self.path!='/chat': return self.send(404,{'error':'not found'})
                try:
                    data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); text=data.get('message',data.get('text','')); sid=data.get('session_id','daemon')
                    if not text: return self.send(400,{'error':'message is required'})
                    with daemon.lock: reply=daemon.agent.run(text,sid)
                    self.send(200,{'reply':reply,'session_id':sid})
                except Exception as e: self.send(500,{'error':str(e)})
        self.server=ThreadingHTTPServer((self.host,self.port),Handler)
        def stop(*_): self.server.shutdown()
        signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
        try: self.server.serve_forever()
        finally:
            self.server.server_close()
            try: self.pid_file.unlink()
            except FileNotFoundError: pass

def run_daemon(**kwargs): FridayDaemon(**kwargs).serve()
