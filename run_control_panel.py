#!/usr/bin/env python3
"""HTTP control panel for reviewing and publishing RoozVan pipeline output."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import traceback
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from roozvan.control_panel_service import ControlPanelError, ControlPanelService, ensure_preview_html


def panel_log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RoozVan review control panel HTTP server.")
    parser.add_argument(
        "--dump-dir",
        default="runs/live-debug",
        help="Pipeline dump directory containing index.html and selected.json.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port.")
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    dump_dir = (repo_root / args.dump_dir).resolve()
    service = ControlPanelService(dump_dir=dump_dir, repo_root=repo_root)
    handler = build_handler(service=service, repo_root=repo_root, dump_dir=dump_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    index_path = dump_dir / "index.html"
    panel_log(f"RoozVan control panel at http://{args.host}:{args.port}/")
    panel_log("Open that URL in your browser. Do not open runs/live-debug/index.html as a local file.")
    panel_log(f"Dump dir: {dump_dir}")
    panel_log(f"Preview HTML: {index_path}")
    if not index_path.exists():
        panel_log("No index.html yet — click Reingest RSS in the panel or run the pipeline first.")
    panel_log("Waiting for requests…")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        panel_log("Stopped.")
    return 0


def build_handler(*, service: ControlPanelService, repo_root: Path, dump_dir: Path):
    class ControlPanelHandler(BaseHTTPRequestHandler):
        server_version = "RoozVanControlPanel/1.0"

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            panel_log(f"{self.address_string()} {format % args}")

        def do_GET(self) -> None:  # noqa: N802
            started_at = time.perf_counter()
            parsed = urlparse(self.path)
            path = parsed.path
            panel_log(f"GET {path}")

            try:
                if path in {"", "/"}:
                    self._serve_file(ensure_preview_html(dump_dir))
                elif path == "/index.html":
                    self._serve_file(ensure_preview_html(dump_dir))
                elif path == "/api/status":
                    self._send_json(service.status())
                else:
                    candidate = (repo_root / path.lstrip("/")).resolve()
                    if not str(candidate).startswith(str(repo_root)):
                        self._send_json({"ok": False, "error": "Forbidden"}, HTTPStatus.FORBIDDEN)
                    elif candidate.is_file():
                        self._serve_file(candidate)
                    else:
                        self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
            finally:
                panel_log(f"GET {path} done in {time.perf_counter() - started_at:.2f}s")

        def do_POST(self) -> None:  # noqa: N802
            started_at = time.perf_counter()
            parsed = urlparse(self.path)
            panel_log(f"POST {parsed.path}")

            if not parsed.path.startswith("/api/"):
                self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
                panel_log(f"POST {parsed.path} rejected (404) in {time.perf_counter() - started_at:.2f}s")
                return

            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                panel_log(f"POST {parsed.path} bad JSON: {exc}")
                return

            try:
                if parsed.path == "/api/reingest":
                    result = service.reingest()
                elif parsed.path == "/api/regenerate-text":
                    result = service.regenerate_text(int(payload["source_index"]))
                elif parsed.path == "/api/regenerate-image":
                    result = service.regenerate_image(
                        int(payload["source_index"]),
                        slide=_optional_int(payload.get("slide")),
                    )
                elif parsed.path == "/api/publish":
                    result = service.publish(int(payload["source_index"]))
                else:
                    self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
                    panel_log(f"POST {parsed.path} unknown endpoint")
                    return
            except (ControlPanelError, KeyError, TypeError, ValueError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                panel_log(f"POST {parsed.path} failed: {exc}")
                return
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                panel_log(f"POST {parsed.path} error: {exc}")
                return

            self._send_json(result)
            summary = _summarize_api_result(parsed.path, result)
            panel_log(f"POST {parsed.path} ok in {time.perf_counter() - started_at:.2f}s {summary}")

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _serve_file(self, path: Path) -> None:
            if not path.is_file():
                return self._send_json({"ok": False, "error": f"Missing file: {path}"}, HTTPStatus.NOT_FOUND)
            content = path.read_bytes()
            content_type, _ = mimetypes.guess_type(str(path))
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ControlPanelHandler


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _summarize_api_result(path: str, result: dict) -> str:
    if path == "/api/reingest":
        stats = result.get("stats") or {}
        return (
            f"(extracted={stats.get('extracted_count', '?')}, "
            f"scored={stats.get('scored_count', '?')}, "
            f"selected={result.get('selected_count', '?')}, "
            f"errors={result.get('error_count', 0)})"
        )
    if path == "/api/regenerate-text":
        warnings = result.get("warnings") or []
        warning_text = f", warnings={len(warnings)}" if warnings else ""
        return f"(source_index={result.get('source_index')}, format={result.get('format')}{warning_text})"
    if path == "/api/regenerate-image":
        slide = result.get("slide")
        slide_text = f", slide={slide}" if slide is not None else ""
        return f"(source_index={result.get('source_index')}{slide_text})"
    if path == "/api/publish":
        publish = result.get("publish") or {}
        return f"(source_index={result.get('source_index')}, media_id={publish.get('media_id')})"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
