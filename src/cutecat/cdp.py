from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import struct
import subprocess
import tempfile
import time
from urllib.parse import urlparse

import requests

HANDSHAKE_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455
OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x1, 0x2, 0x8, 0x9, 0xA


class CDPError(Exception):
    """The browser wouldn't start, wouldn't talk, or refused a command."""


#websocket


class WebSocket:
    """The client half of RFC 6455, in as few lines as it takes."""

    def __init__(self, url: str, timeout: float = 30.0):
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise CDPError(f"could not connect to the browser: {exc}") from exc
        self.sock.settimeout(timeout)
        self._buf = b""
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.sock.sendall(
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        header = self._read_until(b"\r\n\r\n")
        if b"101" not in header.split(b"\r\n", 1)[0]:
            raise CDPError(f"the browser refused the websocket: {header[:80]!r}")

    def _read_until(self, marker: bytes) -> bytes:
        while marker not in self._buf:
            try:
                chunk = self.sock.recv(65536)
            except OSError as exc:
                raise CDPError(f"lost the browser: {exc}") from exc
            if not chunk:
                raise CDPError("the browser closed the connection")
            self._buf += chunk
        head, self._buf = self._buf.split(marker, 1)
        return head + marker

    def _read_exactly(self, n: int) -> bytes:
        while len(self._buf) < n:
            try:
                chunk = self.sock.recv(max(65536, n - len(self._buf)))
            except OSError as exc:
                raise CDPError(f"lost the browser: {exc}") from exc
            if not chunk:
                raise CDPError("the browser closed the connection")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def send(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x80 | OP_TEXT])  # FIN + text
        mask = secrets.token_bytes(4)
        size = len(payload)
        if size < 126:
            header.append(0x80 | size)  # client frames are always masked
        elif size < 1 << 16:
            header.append(0x80 | 126)
            header += struct.pack(">H", size)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", size)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        try:
            self.sock.sendall(bytes(header) + masked)
        except OSError as exc:
            raise CDPError(f"lost the browser: {exc}") from exc

    def recv(self) -> str:
        """One complete message (reassembling continuation frames)."""
        message = bytearray()
        while True:
            b0, b1 = self._read_exactly(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            size = b1 & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read_exactly(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read_exactly(8))[0]
            if b1 & 0x80:  # a server frame should never be masked, but cope
                mask = self._read_exactly(4)
                payload = bytes(
                    b ^ mask[i % 4]
                    for i, b in enumerate(self._read_exactly(size))
                )
            else:
                payload = self._read_exactly(size)
            if opcode == OP_CLOSE:
                raise CDPError("the browser closed the connection")
            if opcode == OP_PING:
                self.sock.sendall(bytes([0x80 | OP_PONG, 0x80]) + secrets.token_bytes(4))
                continue
            if opcode == OP_PONG:
                continue
            message += payload
            if fin:
                return message.decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.sock.sendall(bytes([0x80 | OP_CLOSE, 0x80]) + secrets.token_bytes(4))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


#the browser


class Browser:
    """A headless browser we launched, with a DevTools connection to it."""

    def __init__(self, exe: str, timeout: float = 60.0):
        self.exe = exe
        self.timeout = timeout
        # ignore_cleanup_errors: the browser can still be flushing its profile
        # as we tear it down, and a leftover temp file is not worth an exception.
        self._profile = tempfile.TemporaryDirectory(
            prefix="cutecat-cdp-", ignore_cleanup_errors=True
        )
        self.proc: subprocess.Popen | None = None
        self.ws: WebSocket | None = None
        self._id = 0

    # -- lifecycle

    def __enter__(self) -> "Browser":
        self._launch()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _launch(self) -> None:
        argv = [
            self.exe,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--remote-debugging-port=0",  # a free port; chrome tells us which
            f"--user-data-dir={self._profile.name}",
            "about:blank",
        ]
        for attempt in (argv, [argv[0], "--no-sandbox", *argv[1:]]):
            try:
                self.proc = subprocess.Popen(
                    attempt,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                raise CDPError(f"could not run {self.exe}: {exc}") from exc
            port = self._wait_for_port()
            if port is not None:
                self._connect(port)
                return
            self.proc.kill()  # probably the sandbox; retry without it
        raise CDPError("the browser did not start a devtools endpoint")

    def _wait_for_port(self) -> int | None:
        """Chrome writes the port it chose into DevToolsActivePort."""
        marker = os.path.join(self._profile.name, "DevToolsActivePort")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return None  # it died
            try:
                first = open(marker, encoding="utf-8").readline().strip()
                if first.isdigit():
                    return int(first)
            except OSError:
                pass
            time.sleep(0.05)
        return None

    def _connect(self, port: int) -> None:
        base = f"http://127.0.0.1:{port}"
        try:
            # /json/new mints a fresh tab. Newer Chrome requires PUT.
            resp = requests.put(f"{base}/json/new?about:blank", timeout=10)
            if resp.status_code >= 400:
                resp = requests.get(f"{base}/json/new?about:blank", timeout=10)
            target = resp.json()
            ws_url = target["webSocketDebuggerUrl"]
            self._target_id = target.get("id")
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise CDPError(f"could not open a devtools tab: {exc}") from exc
        self.ws = WebSocket(ws_url, timeout=self.timeout)

    def close(self) -> None:
        if self.ws is not None:
            self.ws.close()
            self.ws = None
        if self.proc is not None:
            for stop in (self.proc.terminate, self.proc.kill):
                try:
                    stop()
                    self.proc.wait(5)
                    break
                except (OSError, subprocess.TimeoutExpired):
                    continue
            self.proc = None
        self._profile.cleanup()

    # -- protocol

    def call(self, method: str, **params) -> dict:
        """Send one command and wait for *its* reply, ignoring events."""
        if self.ws is None:
            raise CDPError("not connected")
        self._id += 1
        request_id = self._id
        self.ws.send(json.dumps({"id": request_id, "method": method,
                                 "params": params or {}}))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except ValueError:
                continue  # a frame we can't parse is not worth dying over
            except (OSError, TimeoutError) as exc:
                raise CDPError(f"{method}: lost the browser ({exc})") from exc
            if not isinstance(message, dict):
                continue
            if message.get("id") != request_id:
                continue  # an event, or another command's reply
            if "error" in message:
                raise CDPError(f"{method}: {message['error'].get('message')}")
            return message.get("result", {})
        raise CDPError(f"{method} timed out")

    def wait_for_event(self, name: str, timeout: float) -> bool:
        """Wait for a CDP event. False on timeout or a lost browser — the caller
        carries on and captures whatever the page has, rather than failing."""
        if self.ws is None:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.ws.sock.settimeout(max(0.1, deadline - time.monotonic()))
                message = json.loads(self.ws.recv())
            except (socket.timeout, TimeoutError, CDPError, OSError, ValueError):
                return False
            finally:
                if self.ws is not None:
                    self.ws.sock.settimeout(self.timeout)
            if isinstance(message, dict) and message.get("method") == name:
                return True
        return False

    # -- the useful bit

    def screenshot(self, url: str, *, width: int, height: int, wait_ms: int,
                   full_page: bool) -> bytes:
        """PNG bytes. full_page captures the entire document, not just the
        viewport — which is the thing the command line cannot do."""
        self.call("Page.enable")
        self.call(
            "Emulation.setDeviceMetricsOverride",
            width=width, height=height, deviceScaleFactor=1, mobile=False,
        )
        self.call("Page.navigate", url=url)
        self.wait_for_event("Page.loadEventFired", timeout=self.timeout)
        time.sleep(wait_ms / 1000)  # let post-load scripts settle

        params = {"format": "png"}
        if full_page:
            # grow the viewport to the full doc so fixed/sticky don't repeat
            metrics = self.call("Page.getLayoutMetrics")
            size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
            full_h = int(size.get("height") or height)
            full_w = int(size.get("width") or width)
            self.call(
                "Emulation.setDeviceMetricsOverride",
                width=full_w, height=full_h, deviceScaleFactor=1, mobile=False,
            )
            params["captureBeyondViewport"] = True
            params["clip"] = {"x": 0, "y": 0, "width": full_w,
                              "height": full_h, "scale": 1}
        result = self.call("Page.captureScreenshot", **params)
        data = result.get("data")
        if not data:
            raise CDPError("the browser returned an empty screenshot")
        return base64.b64decode(data)
