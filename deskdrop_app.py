"""Desktop launcher for the DeskDrop local file server."""

from __future__ import annotations

import socket
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
import sys

from lan_file_server import FileHandler, FileServer


def local_address() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class DeskDropApp:
    def __init__(self) -> None:
        self.root_path = application_directory() / "SharedFromLaptop"
        self.root_path.mkdir(parents=True, exist_ok=True)
        try:
            self.server = FileServer(("0.0.0.0", 8000), FileHandler)
        except OSError:
            self.server = FileServer(("0.0.0.0", 0), FileHandler)
        self.server.root = self.root_path  # type: ignore[attr-defined]
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.closing = False

        port = self.server.server_address[1]
        self.url = f"http://{local_address()}:{port}/"
        self.window = tk.Tk()
        self.window.title("DeskDrop")
        self.window.geometry("430x300")
        self.window.minsize(430, 300)
        self.window.resizable(False, False)
        self.window.configure(bg="#10211e")
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        tk.Label(
            self.window,
            text="DeskDrop",
            bg="#10211e",
            fg="#f8f3e9",
            font=("Georgia", 26, "bold"),
        ).pack(pady=(28, 2))
        tk.Label(
            self.window,
            text="Your local file desk is ready",
            bg="#10211e",
            fg="#b9d0c3",
            font=("Trebuchet MS", 11),
        ).pack()
        address = tk.Label(
            self.window,
            text=self.url,
            bg="#21332f",
            fg="#f08a62",
            font=("Consolas", 12, "bold"),
            padx=14,
            pady=10,
        )
        address.pack(pady=18)
        controls = tk.Frame(self.window, bg="#10211e")
        controls.pack()
        tk.Button(
            controls,
            text="Open DeskDrop",
            command=lambda: webbrowser.open(self.url),
            bg="#e2734e",
            fg="white",
            activebackground="#f08a62",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            controls,
            text="Stop server",
            command=self.close,
            bg="#21332f",
            fg="#f8f3e9",
            activebackground="#3a5149",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Label(
            self.window,
            text="Keep this window open while sharing files.",
            bg="#10211e",
            fg="#b9d0c3",
            font=("Trebuchet MS", 10),
        ).pack(pady=(18, 4))
        webbrowser.open(self.url)

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.window.title("DeskDrop - stopping")
        threading.Thread(target=self._stop_server, daemon=True).start()

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.window.after(0, self.window.destroy)

    def run(self) -> None:
        self.window.mainloop()


if __name__ == "__main__":
    DeskDropApp().run()
