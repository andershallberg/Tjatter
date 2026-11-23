from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Any


COLORS = {
    "background": "#F4F6FA",
    "ink": "#172033",
    "muted": "#718096",
    "accent": "#4F46E5",
    "border": "#E7EAF1",
    "input_border": "#D8DEEA",
    "white": "#FFFFFF",
    "error": "#B42318",
}


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


def create_chat_completions_url(project_endpoint: str) -> str:
    """Return the Azure OpenAI-compatible URL for a Foundry project endpoint."""
    parsed = urllib.parse.urlsplit(project_endpoint.strip())
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Enter a valid HTTPS Foundry project endpoint.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The project endpoint contains an invalid port.") from exc
    if port not in (None, 443):
        raise ValueError("The project endpoint must use the standard HTTPS port.")
    # Check the host before attaching the API key so it cannot be sent off Azure.
    if not hostname.endswith(".services.ai.azure.com"):
        raise ValueError(
            "The endpoint host must be a Foundry resource ending in "
            ".services.ai.azure.com."
        )

    segments = parsed.path.strip("/").split("/")
    if (
        len(segments) != 3
        or segments[0].casefold() != "api"
        or segments[1].casefold() != "projects"
        or not segments[2]
    ):
        raise ValueError(
            "Use the project endpoint format "
            "https://<resource>.services.ai.azure.com/api/projects/<project>."
        )

    # Model inference uses the resource's OpenAI-compatible route, not the project path.
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, "/openai/v1/chat/completions", "", "")
    )


def _read_reply(response_data: dict[str, Any]) -> str:
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("Azure returned a successful response without any assistant text.")

    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        text_parts = [
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        reply = "\n".join(text_parts).strip()
        if reply:
            return reply
    raise ValueError("Azure returned a successful response without any assistant text.")


def _service_error_message(status: int, response_body: str) -> str:
    try:
        error = json.loads(response_body).get("error")
        if isinstance(error, dict):
            message = error.get("message")
        elif isinstance(error, str):
            message = error
        else:
            message = None
        if isinstance(message, str) and message.strip():
            return f"Azure returned HTTP {status}: {message}"
    except (json.JSONDecodeError, AttributeError):
        pass

    detail = response_body[:500]
    if len(response_body) > 500:
        detail += "..."
    suffix = f": {detail}" if detail else ""
    return f"Azure returned HTTP {status}{suffix}"


def request_chat_completion(
    project_endpoint: str,
    api_key: str,
    model: str,
    history: list[ChatMessage],
    prompt: str,
) -> str:
    url = create_chat_completions_url(project_endpoint)
    messages = [
        {"role": message.role, "content": message.content}
        for message in history
    ]
    messages.append({"role": "system", "content": "You are a grumpy old pirate. You only answer questions in pirate speak, and you are not allowed to break character. You know only of boats, ships, fishing, and similar marine activities, and you are not allowed to answer questions about anything else."})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({"model": model, "messages": messages}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "api-key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        finally:
            exc.close()
        raise RuntimeError(_service_error_message(exc.code, body)) from exc

    if not isinstance(response_data, dict):
        raise ValueError("Azure returned an invalid response.")
    return _read_reply(response_data)


class TjatterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Tjatter")
        self.root.geometry("1120x760")
        self.root.minsize(860, 620)
        self.root.configure(bg=COLORS["background"])

        self.messages: list[ChatMessage] = []
        self.results: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self.busy = False
        self.settings_path = self._settings_path()

        self._configure_styles()
        self._build_ui()
        self._load_settings()
        self.root.after(100, self._check_results)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    @staticmethod
    def _settings_path() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "Tjatter" / "settings.json"

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Tjatter.TFrame", background=COLORS["white"])
        style.configure(
            "Tjatter.TLabel",
            background=COLORS["white"],
            foreground=COLORS["ink"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["white"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Field.TLabel",
            background=COLORS["white"],
            foreground="#344054",
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground=COLORS["white"],
            borderwidth=0,
            padding=(18, 11),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", "#A5A1E8"), ("active", "#4338CA")],
        )
        style.configure(
            "Secondary.TButton",
            background=COLORS["white"],
            foreground="#344054",
            bordercolor=COLORS["input_border"],
            padding=(12, 9),
            font=("Segoe UI", 9),
        )

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self.root, style="Tjatter.TFrame", padding=26, width=330)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(20, weight=1)

        logo = tk.Label(
            sidebar,
            text="T",
            bg="#EEF0FF",
            fg=COLORS["accent"],
            font=("Segoe UI", 22, "bold"),
            width=2,
            height=1,
            padx=4,
            pady=4,
        )
        logo.grid(row=0, column=0, sticky="w")
        ttk.Label(sidebar, text="Tjatter", style="Tjatter.TLabel", font=("Segoe UI", 20, "bold")).grid(
            row=1, column=0, sticky="w", pady=(14, 2)
        )
        ttk.Label(sidebar, text="Your private AI chat", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w"
        )

        self.endpoint_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.endpoint_entry = self._add_field(
            sidebar, 3, "PROJECT ENDPOINT", self.endpoint_var
        )
        self.model_entry = self._add_field(sidebar, 5, "MODEL DEPLOYMENT", self.model_var)
        self.key_entry = self._add_field(
            sidebar, 7, "API KEY", self.api_key_var, show="*"
        )

        note = tk.Label(
            sidebar,
            text="Your key stays on this device for this session and is never saved by the app.",
            bg=COLORS["white"],
            fg=COLORS["muted"],
            font=("Segoe UI", 8),
            justify="left",
            wraplength=265,
        )
        note.grid(row=9, column=0, sticky="w", pady=(8, 0))

        api_note = tk.Label(
            sidebar,
            text="API keys use the OpenAI-compatible endpoint on your Foundry resource. Paste the project endpoint above; Tjatter selects the model route.",
            bg=COLORS["background"],
            fg="#596579",
            font=("Segoe UI", 8),
            justify="left",
            wraplength=245,
            padx=12,
            pady=11,
        )
        api_note.grid(row=10, column=0, sticky="ew", pady=(20, 0))

        sidebar_bottom = ttk.Frame(sidebar, style="Tjatter.TFrame")
        sidebar_bottom.grid(row=21, column=0, sticky="sew")
        sidebar_bottom.grid_columnconfigure(0, weight=1)
        self.new_chat_button = ttk.Button(
            sidebar_bottom,
            text="New conversation",
            style="Secondary.TButton",
            command=self._new_conversation,
        )
        self.new_chat_button.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.status_var = tk.StringVar(value="Enter your Azure details to start chatting.")
        ttk.Label(
            sidebar_bottom,
            textvariable=self.status_var,
            style="Muted.TLabel",
            wraplength=260,
        ).grid(row=1, column=0, sticky="w")

        chat_area = tk.Frame(self.root, bg=COLORS["background"])
        chat_area.grid(row=0, column=1, sticky="nsew")
        chat_area.grid_columnconfigure(0, weight=1)
        chat_area.grid_rowconfigure(1, weight=1)

        header = tk.Frame(chat_area, bg=COLORS["white"], height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Chat",
            bg=COLORS["white"],
            fg=COLORS["ink"],
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="sw", padx=30, pady=(13, 0))
        tk.Label(
            header,
            text="Connected directly to your Azure model",
            bg=COLORS["white"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="nw", padx=30, pady=(1, 12))
        tk.Label(
            header,
            text="HTTPS to Azure",
            bg="#ECFDF3",
            fg="#027A48",
            font=("Segoe UI", 8),
            padx=10,
            pady=5,
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=30)
        tk.Frame(chat_area, bg=COLORS["border"], height=1).grid(row=0, column=0, sticky="sew")

        transcript_frame = tk.Frame(chat_area, bg=COLORS["background"])
        transcript_frame.grid(row=1, column=0, sticky="nsew")
        transcript_frame.grid_columnconfigure(0, weight=1)
        transcript_frame.grid_rowconfigure(0, weight=1)
        self.transcript = tk.Text(
            transcript_frame,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            padx=30,
            pady=24,
            bg=COLORS["background"],
            fg=COLORS["ink"],
            font=("Segoe UI", 10),
            spacing1=5,
            spacing3=12,
            cursor="arrow",
        )
        scrollbar = ttk.Scrollbar(
            transcript_frame, orient="vertical", command=self.transcript.yview
        )
        self.transcript.configure(yscrollcommand=scrollbar.set)
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.transcript.tag_configure("welcome_title", font=("Segoe UI", 18, "bold"), justify="center")
        self.transcript.tag_configure("welcome", foreground=COLORS["muted"], justify="center", spacing3=20)
        self.transcript.tag_configure("assistant_label", foreground=COLORS["accent"], font=("Segoe UI", 9, "bold"))
        self.transcript.tag_configure("user_label", foreground="#344054", font=("Segoe UI", 9, "bold"))
        self.transcript.tag_configure("message", lmargin1=12, lmargin2=12, rmargin=30, spacing3=12)
        self.transcript.tag_configure("error", foreground=COLORS["error"], lmargin1=12, lmargin2=12, rmargin=30, spacing3=12)
        self._show_welcome()

        composer = tk.Frame(chat_area, bg=COLORS["white"], padx=30, pady=17)
        composer.grid(row=2, column=0, sticky="ew")
        composer.grid_columnconfigure(0, weight=1)
        tk.Frame(chat_area, bg=COLORS["border"], height=1).grid(row=2, column=0, sticky="new")
        self.prompt = tk.Text(
            composer,
            height=2,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=COLORS["input_border"],
            highlightcolor=COLORS["accent"],
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
        )
        self.prompt.grid(row=0, column=0, sticky="ew")
        self.prompt.bind("<Return>", self._on_enter)
        self.send_button = ttk.Button(
            composer,
            text="Send",
            style="Accent.TButton",
            command=self._send_message,
        )
        self.send_button.grid(row=0, column=1, sticky="ns", padx=(12, 0))

    @staticmethod
    def _add_field(
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        show: str | None = None,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label, style="Field.TLabel").grid(
            row=row, column=0, sticky="w", pady=(18, 7)
        )
        entry = ttk.Entry(parent, textvariable=variable, show=show)
        entry.grid(row=row + 1, column=0, sticky="ew", ipady=7)
        return entry

    def _show_welcome(self) -> None:
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.insert("end", "\n\nWhat would you like to explore?\n", "welcome_title")
        self.transcript.insert(
            "end",
            "Ask a question to get started. Your messages are sent to the model you configure.",
            "welcome",
        )
        self.transcript.configure(state="disabled")

    def _append_message(self, label: str, content: str, role: str) -> None:
        self.transcript.configure(state="normal")
        if not self.messages and role != "error":
            self.transcript.delete("1.0", "end")
        label_tag = "user_label" if role == "user" else "assistant_label"
        body_tag = "error" if role == "error" else "message"
        self.transcript.insert("end", f"{label}\n", label_tag)
        self.transcript.insert("end", f"{content}\n\n", body_tag)
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _on_enter(self, event: tk.Event[tk.Misc]) -> str | None:
        if event.state & 0x0001:
            return None
        self._send_message()
        return "break"

    def _send_message(self) -> None:
        if self.busy:
            return
        prompt = self.prompt.get("1.0", "end-1c").strip()
        if not prompt:
            return

        endpoint = self.endpoint_var.get().strip()
        model = self.model_var.get().strip()
        api_key = self.api_key_var.get()
        if not endpoint or not model or not api_key:
            self.status_var.set("Enter the project endpoint, model deployment, and API key before sending.")
            return

        try:
            create_chat_completions_url(endpoint)
        except ValueError as exc:
            self.status_var.set(str(exc))
            return

        self._append_message("You", prompt, "user")
        self.messages.append(ChatMessage("user", prompt))
        self.prompt.delete("1.0", "end")
        self._set_busy(True)
        self.status_var.set("Waiting for your model…")
        history = self.messages[:-1].copy()

        # A daemon worker keeps network I/O off Tk and cannot hold the process open.
        worker = threading.Thread(
            target=self._request_in_background,
            args=(endpoint, api_key, model, history, prompt),
            daemon=True,
        )
        worker.start()

    def _request_in_background(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        history: list[ChatMessage],
        prompt: str,
    ) -> None:
        try:
            reply = request_chat_completion(endpoint, api_key, model, history, prompt)
            self.results.put(("success", model, reply))
        except Exception as exc:
            self.results.put(("error", "Connection error", str(exc)))

    def _check_results(self) -> None:
        try:
            while True:
                result, label, content = self.results.get_nowait()
                if result == "success":
                    self.messages.append(ChatMessage("assistant", content))
                    self._append_message(label, content, "assistant")
                    self.status_var.set("Reply received.")
                    self._save_settings()
                else:
                    self.messages.pop()
                    self._append_message(label, content, "error")
                    self.status_var.set(
                        "The request could not be completed. Check your connection and Azure settings."
                    )
                self._set_busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self._check_results)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self.endpoint_entry,
            self.model_entry,
            self.key_entry,
            self.prompt,
            self.new_chat_button,
        ):
            widget.configure(state=state)
        self.send_button.configure(state=state, text="Sending..." if busy else "Send")

    def _new_conversation(self) -> None:
        if self.busy:
            return
        self.messages.clear()
        self._show_welcome()
        self.status_var.set("Conversation cleared.")

    def _load_settings(self) -> None:
        try:
            with self.settings_path.open("r", encoding="utf-8") as settings_file:
                settings = json.load(settings_file)
            if not isinstance(settings, dict):
                raise ValueError("The saved settings file must contain a JSON object.")
            endpoint = settings.get("project_endpoint", "")
            model = settings.get("model", "")
            if not isinstance(endpoint, str) or not isinstance(model, str):
                raise ValueError("The saved endpoint and model must be strings.")
            self.endpoint_var.set(endpoint)
            self.model_var.set(model)
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.status_var.set(f"Could not load saved settings: {exc}")

    def _save_settings(self) -> None:
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            # Persist connection settings only; the API key must remain session-only.
            self.settings_path.write_text(
                json.dumps(
                    {
                        "project_endpoint": self.endpoint_var.get().strip(),
                        "model": self.model_var.get().strip(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            self.status_var.set(f"Could not save settings: {exc}")

    def _close(self) -> None:
        self._save_settings()
        self.root.quit()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    TjatterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
