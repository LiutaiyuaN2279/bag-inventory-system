"""验证「所有角色都有首页看板」——用 CDP 驱动真实浏览器登录并检查落地页与渲染。

检查项：
1. 每个账号登录后都能进入 `#/dashboard`（不再被丢到报销单列表）
2. 报销专用角色看到的是「报销工作台」（含 KPI 卡片、待办）
3. 采购/管理岗看到的是「采购库存看板」

运行（需前后端都已启动）：
    python scripts/cdp_check_workbench.py
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

CDP_PORT = 9444
BASE_URL = "http://127.0.0.1:5173"
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

#: 账号 → 期望的首页类型（reimburse=报销工作台，purchase=采购库存看板）
ACCOUNTS = [
    ("admin", "purchase"),
    ("manager", "purchase"),
    ("buyer", "reimburse"),      # 无 report:view → 报销工作台
    ("keeper", "reimburse"),
    ("qc", "reimburse"),
    ("finance", "reimburse"),
    ("finmaker", "reimburse"),
    ("sales", "reimburse"),
    ("tech", "reimburse"),
    ("depthead", "reimburse"),
    ("director", "reimburse"),
    ("gm", "reimburse"),
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
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手失败")
            buf += chunk
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError(f"握手失败: {buf[:120]!r}")
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
            data = b""
            while len(data) < n:
                c = self.sock.recv(n - len(data))
                if not c:
                    raise RuntimeError("连接关闭")
                data += c
            return data

        h = exact(2)
        opcode = h[0] & 0x0F
        length = h[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", exact(8))[0]
        payload = exact(length) if length else b""
        if opcode == 0x8:
            raise RuntimeError("服务端关闭连接")
        if opcode == 0x9:
            self.sock.sendall(b"\x8a\x80" + os.urandom(4))
            return self.recv()
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def call(self, method, params=None, timeout=15):
        mid = self.send(method, params)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.recv()
            if msg.get("id") == mid:
                return msg
        raise TimeoutError(method)

    def eval(self, expr, timeout=15):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True},
                      timeout=timeout)
        res = r.get("result", {}).get("result", {})
        if res.get("subtype") == "error":
            return None
        return res.get("value")

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
        proc = subprocess.Popen([
            exe, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={user_dir}",
            "--no-first-run", "--disable-extensions", "--window-size=1440,960", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        raise RuntimeError("Edge CDP 未就绪")
    raise RuntimeError("找不到 Edge")


def page_ws():
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=5) as r:
        pages = json.loads(r.read())
    for p in pages:
        if p.get("type") == "page":
            return p["webSocketDebuggerUrl"]
    with urllib.request.urlopen(
            f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank", timeout=5) as r:
        return json.loads(r.read())["webSocketDebuggerUrl"]


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    user_dir = os.path.join(root, ".tmp-run", "edge-wb")
    os.makedirs(user_dir, exist_ok=True)
    for f in os.listdir(user_dir):
        try:
            os.remove(os.path.join(user_dir, f))
        except Exception:
            pass

    print("=" * 78)
    print("首页看板验证：所有角色登录后都应有看板")
    print("=" * 78)

    proc = None
    results = []
    try:
        proc = start_edge(user_dir)
        ws = WS(page_ws())
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        # 禁用浏览器缓存：否则 Vite 的旧模块可能被 Edge 缓存，
        # 导致验证到的是改动前的组件（排查时踩过一次坑）
        try:
            ws.call("Network.enable")
            ws.call("Network.setCacheDisabled", {"cacheDisabled": True})
        except Exception:
            pass

        for idx, (username, expect) in enumerate(ACCOUNTS):
            # 清空登录态 → 用带时间戳的 URL 强制整页重新加载（仅改 hash 不会重载模块）
            ws.eval("localStorage.clear(); sessionStorage.clear();")
            ws.call("Page.navigate",
                    {"url": f"{BASE_URL}/?t={int(time.time() * 1000)}_{idx}#/login"})
            # 等账号列表异步加载完成（轮询 .acct 数量，避免固定等待不够）
            for _ in range(30):
                time.sleep(0.5)
                n_cards = ws.eval("document.querySelectorAll('.acct').length") or 0
                if n_cards > 0:
                    break

            # 点击账号卡片
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
                # 再等一轮（首屏偶发慢）
                time.sleep(2)
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
                results.append((username, expect, "找不到账号卡片", "", False))
                continue
            time.sleep(0.6)

            # 点登录
            ws.eval("""
(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  const b = btns.find(x => x.textContent.replace(/\\s/g, '').includes('登录'));
  if (b) b.click();
  return !!b;
})()
""")
            time.sleep(7)   # 等 token → userinfo → 路由跳转 → 看板渲染

            hash_ = ws.eval("location.hash") or ""
            # 判断渲染的是哪种看板
            kind = ws.eval("""
(() => {
  if (document.querySelector('.rw')) return 'reimburse';
  if (document.querySelector('.dashboard')) return 'purchase';
  return 'unknown';
})()
""")
            kpi_count = ws.eval("document.querySelectorAll('.kpi-card').length")
            has_card = (kind == "reimburse" and (kpi_count or 0) > 0) or kind == "purchase"

            ok = ("dashboard" in hash_) and (kind == expect) and has_card
            results.append((username, expect, hash_, kind, ok))
            mark = "✓" if ok else "✗"
            print(f"  {mark} {username:<10}落地={hash_ or '—':<16}"
                  f"看板={kind:<10}KPI={kpi_count if kpi_count is not None else '?'}")

        print("\n" + "=" * 78)
        ok = [r for r in results if r[4]]
        bad = [r for r in results if not r[4]]
        print(f"共 {len(results)} 个账号：通过 {len(ok)}，失败 {len(bad)}")
        if bad:
            for u, e, h, k, _ in bad:
                print(f"  ✗ {u}：期望 {e} 看板，实际落地 {h or '—'} / {k}")
            return 1
        print("所有角色登录后都能正常看到首页看板！")
        return 0
    finally:
        if proc:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
