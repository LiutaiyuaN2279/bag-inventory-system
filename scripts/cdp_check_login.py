"""用 Chrome DevTools Protocol 验证「报销角色登录后是否正常跳转」。

背景：登录成功但页面不动的 bug —— 路由守卫在没有首页权限时无限重定向到
/dashboard（自己跳自己），Vue Router 判定循环后中止导航。修复后应跳到
用户真正有权访问的第一个页面（报销角色 → /reimburse/list）。

本脚本不依赖第三方库，手写最小 WebSocket 客户端（RFC 6455 客户端帧需 mask）。

运行（在项目根目录）：
    python scripts/cdp_check_login.py
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

CDP_PORT = 9333
BASE_URL = "http://127.0.0.1:5173"
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


class WS:
    """最小 WebSocket 客户端：只支持文本帧、客户端 mask、不分片。"""

    def __init__(self, url):
        # ws://127.0.0.1:9333/devtools/page/XXXX
        assert url.startswith("ws://")
        rest = url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手失败：连接被关闭")
            buf += chunk
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError(f"WebSocket 握手失败：{buf[:200]!r}")
        self._id = 0

    def send(self, method, params=None):
        self._id += 1
        payload = json.dumps({"id": self._id, "method": method,
                              "params": params or {}}).encode()
        header = b"\x81"  # FIN + text
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)
        return self._id

    def recv(self):
        """读一帧，返回解析后的 dict。"""
        def read_exact(n):
            data = b""
            while len(data) < n:
                chunk = self.sock.recv(n - len(data))
                if not chunk:
                    raise RuntimeError("连接已关闭")
                data += chunk
            return data

        h = read_exact(2)
        opcode = h[0] & 0x0F
        length = h[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", read_exact(8))[0]
        payload = read_exact(length) if length else b""
        if opcode == 0x8:
            raise RuntimeError("服务端关闭了 WebSocket")
        if opcode == 0x9:      # ping → pong
            self.sock.sendall(b"\x8a\x80" + os.urandom(4))
            return self.recv()
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def call(self, method, params=None, timeout=15):
        """发命令并等待同 id 的响应。"""
        mid = self.send(method, params)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.recv()
            if msg.get("id") == mid:
                return msg
        raise TimeoutError(f"{method} 超时")

    def eval(self, expression, timeout=15):
        """执行 JS 表达式，返回结果值。"""
        r = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        }, timeout=timeout)
        result = r.get("result", {}).get("result", {})
        if result.get("subtype") == "error":
            return {"__error__": result.get("description", "")}
        return result.get("value")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def start_edge(user_dir):
    import subprocess
    for exe in EDGE_CANDIDATES:
        if os.path.exists(exe):
            proc = subprocess.Popen([
                exe, "--headless=new", "--disable-gpu", "--no-sandbox",
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={user_dir}",
                "--no-first-run", "--disable-extensions",
                "--window-size=1440,900", "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # 等 CDP 端口就绪
            for _ in range(40):
                time.sleep(0.5)
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2) as r:
                        if r.status == 200:
                            return proc
                except Exception:
                    continue
            proc.kill()
            raise RuntimeError("Edge CDP 端口未就绪")
    raise RuntimeError("找不到 Edge 可执行文件")


def page_ws_url():
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=5) as r:
        pages = json.loads(r.read())
    for p in pages:
        if p.get("type") == "page":
            return p["webSocketDebuggerUrl"]
    # 没有页面就新建
    with urllib.request.urlopen(
        f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank", timeout=5) as r:
        return json.loads(r.read())["webSocketDebuggerUrl"]


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    user_dir = os.path.join(root, ".tmp-run", "edge-cdp-login")
    os.makedirs(user_dir, exist_ok=True)
    for f in os.listdir(user_dir):
        try:
            os.remove(os.path.join(user_dir, f))
        except Exception:
            pass

    print("=" * 70)
    print("验证：不同角色登录后的跳转目标")
    print("=" * 70)

    proc = None
    try:
        proc = start_edge(user_dir)
        ws = WS(page_ws_url())
        ws.call("Page.enable")
        ws.call("Runtime.enable")

        # 关闭 localStorage 干扰，从登录页开始
        ws.call("Page.navigate", {"url": f"{BASE_URL}/#/login"})
        time.sleep(4)

        accounts = ws.eval(
            "JSON.parse(localStorage.getItem('__none__') || 'null') || "
            "Array.from(document.querySelectorAll('.acct')).map(b => b.textContent.trim())"
        )
        print(f"登录页账号卡片数：{len(accounts) if isinstance(accounts, list) else '?'}")

        roles = ["admin", "maker", "finance", "depthead", "gm", "sales"]
        results = []
        for username in roles:
            # 每个角色单独一轮：清空 token → 回登录页 → 填账号 → 点登录
            ws.eval("localStorage.clear(); sessionStorage.clear(); location.hash = '#/login'")
            time.sleep(1.5)
            ws.eval("location.reload()")
            time.sleep(3)

            # 点击对应账号按钮（按用户名匹配 .acct-user 文本）
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
                results.append((username, "找不到账号按钮", ""))
                continue
            time.sleep(0.8)

            # 点击登录按钮
            ws.eval("""
(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  const b = btns.find(x => x.textContent.replace(/\\s/g, '').includes('登录'));
  if (b) b.click();
  return !!b;
})()
""")
            # 等跳转 + 守卫链路（拉 userinfo → 重定向）
            time.sleep(6)
            final_hash = ws.eval("location.hash")
            token = ws.eval("localStorage.getItem('token') || ''")
            results.append((username, final_hash, "有 token" if token else "无 token"))

        print()
        print(f"{'账号':<12}{'登录后路由':<28}{'状态'}")
        print("-" * 60)
        for u, h, t in results:
            print(f"{u:<12}{str(h):<28}{t}")

        print()
        ok = [r for r in results if r[1] and "#/login" not in str(r[1])]
        bad = [r for r in results if not r[1] or "#/login" in str(r[1])]
        print(f"共 {len(results)} 个角色：成功跳转 {len(ok)}，停留登录页 {len(bad)}")
        if bad:
            for u, h, _ in bad:
                print(f"  ✗ {u} 未能跳转（当前 {h}）")
            return 1
        print("所有角色登录后均正常跳转！")
        return 0
    finally:
        if proc:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
