#!/usr/bin/env python3
"""Simple local-network file server for downloading laptop files on a phone."""

from __future__ import annotations

import argparse
import html
import http.server
import ipaddress
import io
import socket
import sys
import urllib.parse
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath


class FileServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


class FileHandler(http.server.BaseHTTPRequestHandler):
    server_version = "LANFileServer/1.0"

    @property
    def root(self) -> Path:
        return self.server.root  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlsplit(self.path)
        request_path = urllib.parse.unquote(parsed_url.path)
        if request_path == "/deskdrop-icon.svg":
            self.send_icon()
            return
        if request_path == "/":
            self.send_directory()
            return
        if request_path == "/download-folder":
            self.send_folder_zip(urllib.parse.parse_qs(parsed_url.query).get("name", [""])[0])
            return

        relative_name = request_path.lstrip("/")
        requested_file = (self.root / relative_name).resolve()
        if not self.is_inside_root(requested_file) or not requested_file.is_file():
            self.send_error(http.server.HTTPStatus.NOT_FOUND, "File not found")
            return

        try:
            file_size = requested_file.stat().st_size
            self.send_response(http.server.HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{requested_file.name.replace(chr(34), "")}"',
            )
            self.send_header("Content-Length", str(file_size))
            self.end_headers()
            with requested_file.open("rb") as file_handle:
                while chunk := file_handle.read(1024 * 1024):
                    self.wfile.write(chunk)
        except OSError as error:
            self.send_error(http.server.HTTPStatus.INTERNAL_SERVER_ERROR, str(error))

    def do_POST(self) -> None:
        if urllib.parse.urlsplit(self.path).path != "/upload":
            self.send_error(http.server.HTTPStatus.NOT_FOUND, "Upload endpoint not found")
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self.send_error(
                http.server.HTTPStatus.BAD_REQUEST,
                "Upload must use multipart/form-data",
            )
            return

        try:
            content_length = self.headers.get("Content-Length")
            if not content_length:
                raise ValueError("Upload size is missing")
            body = self.rfile.read(int(content_length))
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {content_type}\r\n\r\n".encode() + body
            )
            uploaded_parts = [
                part for part in message.iter_parts()
                if part.get_param("name", header="content-disposition") == "file"
                and part.get_filename()
            ]
            if not uploaded_parts:
                raise ValueError("Choose a file or folder to upload")

            for uploaded in uploaded_parts:
                filename = uploaded.get_filename().replace("\\", "/")
                relative_path = PurePosixPath(filename)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise ValueError("Invalid upload path")
                destination = self.root.joinpath(*relative_path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output_file:
                    output_file.write(uploaded.get_payload(decode=True) or b"")
        except (OSError, ValueError, TypeError, UnicodeError) as error:
            self.send_error(http.server.HTTPStatus.BAD_REQUEST, str(error))
            return

        self.send_response(http.server.HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()

    def send_directory(self) -> None:
        files = sorted(path for path in self.root.iterdir() if path.is_file())
        folders = sorted(path for path in self.root.iterdir() if path.is_dir())
        all_files = [path for path in self.root.rglob("*") if path.is_file()]
        total_size = sum(file.stat().st_size for file in all_files)

        def readable_size(size: int) -> str:
            units = ("B", "KB", "MB", "GB")
            amount = float(size)
            for unit in units:
                if amount < 1024 or unit == units[-1]:
                    return f"{amount:.1f} {unit}" if unit != "B" else f"{size:,} B"
                amount /= 1024
            return f"{size:,} B"

        folder_rows = "\n".join(
            f'<li class="file-item folder-item" data-name="{html.escape(folder.name.lower(), quote=True)}" data-type="folder" data-size="0">'
            f'<a class="file-link" href="/download-folder?name={urllib.parse.quote(folder.name)}">'
            f'<span class="file-icon folder-icon">DIR</span>'
            f'<span class="file-details"><strong>{html.escape(folder.name)}</strong>'
            f'<small>Folder · download as ZIP</small></span>'
            f'<span class="download-icon" aria-hidden="true">&#8595;</span></a></li>'
            for folder in folders
        )
        file_rows = "\n".join(
            f'<li class="file-item" data-name="{html.escape(file.name.lower(), quote=True)}" '
            f'data-type="{html.escape(file.suffix.lower(), quote=True)}" data-size="{file.stat().st_size}">'
            f'<a class="file-link" href="/{urllib.parse.quote(file.name)}">'
            f'<span class="file-icon">{html.escape(file.suffix[1:].upper()[:4] or "FILE")}</span>'
            f'<span class="file-details"><strong>{html.escape(file.name)}</strong>'
            f'<small>{readable_size(file.stat().st_size)}</small></span>'
            f'<span class="download-icon" aria-hidden="true">&#8595;</span></a></li>'
            for file in files
        )
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        template_path = bundle_root / "gui.html"
        page = template_path.read_text(encoding="utf-8")
        page = page.replace("__FILES__", folder_rows + file_rows or '<li class="empty">No files or folders yet. Add items to the shared folder.</li>')
        page = page.replace("__FILE_COUNT__", str(len(files) + len(folders)))
        page = page.replace("__TOTAL_SIZE__", readable_size(total_size))
        body = page.encode("utf-8")
        self.send_response(http.server.HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_icon(self) -> None:
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        icon_path = bundle_root / "assets" / "deskdrop-icon.svg"
        try:
            body = icon_path.read_bytes()
        except OSError:
            self.send_error(http.server.HTTPStatus.NOT_FOUND, "Icon not found")
            return
        self.send_response(http.server.HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_folder_zip(self, folder_name: str) -> None:
        folder = (self.root / folder_name).resolve()
        if not folder_name or not self.is_inside_root(folder) or not folder.is_dir():
            self.send_error(http.server.HTTPStatus.NOT_FOUND, "Folder not found")
            return

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file in folder.rglob("*"):
                if file.is_file():
                    zip_file.write(file, file.relative_to(folder.parent))

        body = archive.getvalue()
        self.send_response(http.server.HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{folder.name}.zip"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def is_inside_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[{self.log_date_time_string}] {format_string % args}")


def local_addresses() -> list[str]:
    addresses: set[str] = set()
    for interface in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        address = interface[4][0]
        if not address.startswith("127."):
            try:
                if not ipaddress.ip_address(address).is_link_local:
                    addresses.add(address)
            except ValueError:
                pass
    return sorted(addresses)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).with_name("SharedFromLaptop"),
        help="folder to share (default: SharedFromLaptop next to this script)",
    )
    parser.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    args = parser.parse_args()

    root = args.directory.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    server = FileServer(("0.0.0.0", args.port), FileHandler)
    server.root = root  # type: ignore[attr-defined]

    print(f"Sharing: {root}")
    print("Open one of these addresses on your phone (both devices must use the same Wi-Fi):")
    for address in local_addresses():
        print(f"  http://{address}:{args.port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
