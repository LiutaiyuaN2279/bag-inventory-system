"""用 CDP 截取指定账号登录后的首页看板截图。

用途：人工核对报销工作台 / 采购库存看板的实际渲染效果。

运行（需前后端已启动）：
    python scripts/cdp_shot_workbench.py finance
    python scripts/cdp_shot_workbench.py admin
"""
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CDP_PORT = 9555
BASE_URL = "http://127.0.0.1:5173"
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


class WS:
    def __init__(self, url):
        rest = url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /{path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = self.sock.recv(4096)
            if not c:
                raise RuntimeError("握手失败")
            buf += c
        self._id = 0

    def send(self, method, params=None):
        self._id += 1
        payload = json.dumps({"id": self._id, "method": method,
                              "params": params or {}}).encode()
        header = b"\x81"
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        return self._id

    def recv(self):
        def exact(n):
            d = b""
            while len(d) < n:
                c = self.sock.recv(n - len(d))
                if not c:
                    raise RuntimeError("closed")
                d += c
            return d
        h = exact(2)
        op = h[0] & 0x0F
        ln = h[1] & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", exact(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", exact(8))[0]
        payload = exact(ln) if ln else b""
        if op == 0x8:
            raise RuntimeError("closed")
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def call(self, method, params=None, timeout=20):
        mid = self.send(method, params)
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = self.recv()
            if m.get("id") == mid:
                return m
        raise TimeoutError(method)

    def eval(self, expr, timeout=15):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout)
        res = r.get("result", {}).get("result", {})
        return None if res.get("subtype") == "error" else res.get("value")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def start_edge(user_dir):
    import subprocess
    for exe in EDGE_CANDIDATES:
        if not os.path.exists(exe):
            continue
        p = subprocess.Popen([
            exe, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={user_dir}",
            "--no-first-run", "--disable-extensions", "--window-size=1500,1000", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2) as r:
                    if r.status == 200:
                        return p
            except Exception:
                continue
        p.kill()
        raise RuntimeError("Edge CDP 未就绪")
    raise RuntimeError("找不到 Edge")


def page_ws():
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=5) as r:
        for p in json.loads(r.read()):
            if p.get("type") == "page":
                return p["webSocketDebuggerUrl"]
    with urllib.request.urlopen(
            f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank", timeout=5) as r:
        return json.loads(r.read())["webSocketDebuggerUrl"]


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "finance"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    user_dir = os.path.join(root, ".tmp-run", f"edge-shot-{username}")
    import shutil
    shutil.rmtree(user_dir, ignore_errors=True)
    os.makedirs(user_dir, exist_ok=True)
    out = os.path.join(root, ".tmp-run", f"workbench-{username}.png")

    proc = None
    try:
        proc = start_edge(user_dir)
        ws = WS(page_ws())
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Network.enable")
        ws.call("Network.setCacheDisabled", {"cacheDisabled": True})

        ws.call("Page.navigate", {"url": f"{BASE_URL}/#/login"})
        for _ in range(30):
            time.sleep(0.5)
            if (ws.eval("document.querySelectorAll('.acct').length") or 0) > 0:
                break

        clicked = ws.eval(f"""
(() => {{
  const cards = Array.from(document.querySelectorAll('.acct'));
  const el = cards.find(c => (c.querySelector('.acct-user')?.textContent || '').trim() === '{username}');
  if (!el) return false;
  el.click();
  return true;
}})()
""")
        if not clicked:
            print(f"找不到账号卡片 {username}")
            return 1
        time.sleep(0.6)
        ws.eval("""
(() => {
  const b = Array.from(document.querySelectorAll('button'))
    .find(x => x.textContent.replace(/\\s/g, '').includes('登录'));
  if (b) b.click();
  return !!b;
})()
""")
        # 等看板渲染
        for _ in range(40):
            time.sleep(0.5)
            if ws.eval("!!document.querySelector('.rw,.dashboard')"):
                break
        time.sleep(2.5)   # 等图表/表格稳定

        kind = ws.eval("""
(() => document.querySelector('.rw') ? 'reimburse' : (document.querySelector('.dashboard') ? 'purchase' : 'unknown'))()
""")
        kpi = ws.eval("document.querySelectorAll('.kpi-card').length")

        # 截图
        shot = ws.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        data = shot.get("result", {}).get("data")
        if not data:
            print("截图失败")
            return 1
        with open(out, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"账号={username}  看板={kind}  KPI={kpi}  截图={out}")
        return 0
    finally:
        if proc:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
