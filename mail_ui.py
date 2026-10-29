"""Shared mail account and send confirmation UI for both Momo editions."""

from __future__ import annotations

import smtplib
import threading
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from mail_service import (connect_gmail, load_private, recent_gmail, recent_mailplug,
                          save_private, send_gmail, send_mailplug, validate_recipients,
                          verify_mailplug)


class MailMixin:
    mail_data_dir: Path

    @staticmethod
    def is_mail_inbox_request(request: str) -> bool:
        text = request.strip().casefold()
        return text == "/inbox" or (not re.search(r"보내|발송", text) and bool(re.search(
            r"(?:최근|받은|새|안\s*읽은).{0,8}(?:이?메일)|(?:이?메일).{0,8}(?:확인|조회|읽어)", text)))

    @property
    def gmail_token_path(self) -> Path:
        return self.mail_data_dir / "gmail-token.dpapi"

    @property
    def mailplug_account_path(self) -> Path:
        return self.mail_data_dir / "mailplug-account.dpapi"

    def add_mail_menu(self, parent: tk.Menu) -> None:
        menu = tk.Menu(parent, tearoff=False, bg=self.theme["panel"], fg=self.theme["text"],
                       activebackground=self.theme["button"], activeforeground=self.theme["text"])
        menu.add_command(label="Gmail 연결", command=self.configure_gmail)
        menu.add_command(label="메일플러그 연결", command=self.configure_mailplug)
        menu.add_command(label="최근 받은 메일", command=self.show_recent_mail)
        menu.add_separator()
        if self.gmail_token_path.exists():
            menu.add_command(label="Gmail 연결 해제", command=lambda: self.disconnect_mail("gmail"))
        if self.mailplug_account_path.exists():
            menu.add_command(label="메일플러그 연결 해제", command=lambda: self.disconnect_mail("mailplug"))
        parent.add_cascade(label="메일 계정", menu=menu)

    def _mail_busy(self) -> bool:
        if self.busy:
            return False
        self.busy = True
        self.status.configure(text="메일 처리 중…")
        self.send_button.configure(state="disabled")
        return True

    def configure_gmail(self) -> None:
        if self.busy:
            return
        filename = filedialog.askopenfilename(parent=self.root, title="Google OAuth 데스크톱 클라이언트 JSON 선택",
                                               filetypes=[("JSON 파일", "*.json")])
        if not filename or not self._mail_busy():
            return
        self.add_message(self.settings["name"], "Gmail 로그인 창을 열게. 계정을 선택하고 권한을 허용해줘.")

        def connect() -> None:
            try:
                address = connect_gmail(Path(filename), self.gmail_token_path)
                self.events.put(("answer", f"Gmail {address} 계정을 연결했어."))
            except Exception as exc:
                self.events.put(("error", f"Gmail 연결 실패: {exc}"))

        threading.Thread(target=connect, daemon=True).start()

    def configure_mailplug(self) -> None:
        if self.busy:
            return
        try:
            current = load_private(self.mailplug_account_path)
        except ValueError as exc:
            messagebox.showerror("메일플러그 연결", str(exc), parent=self.root)
            return
        address = simpledialog.askstring("메일플러그 연결", "메일플러그 이메일 주소를 입력해줘.",
                                         initialvalue=current.get("address", ""), parent=self.root)
        if address is None:
            return
        password = simpledialog.askstring("메일플러그 연결", "메일플러그에서 만든 앱 비밀번호를 입력해줘.",
                                          show="●", parent=self.root)
        if password is None or not self._mail_busy():
            return

        def connect() -> None:
            try:
                verify_mailplug(address.strip(), password)
                save_private(self.mailplug_account_path, {"address": address.strip(), "app_password": password})
                self.events.put(("answer", f"메일플러그 {address.strip()} 계정을 연결했어."))
            except (OSError, ValueError, smtplib.SMTPException) as exc:
                self.events.put(("error", f"메일플러그 연결 실패: {exc}"))

        threading.Thread(target=connect, daemon=True).start()

    def disconnect_mail(self, provider: str) -> None:
        label = "Gmail" if provider == "gmail" else "메일플러그"
        if not messagebox.askyesno("메일 연결 해제", f"이 PC에 저장된 {label} 연결을 지울까?", parent=self.root):
            return
        path = self.gmail_token_path if provider == "gmail" else self.mailplug_account_path
        try:
            path.unlink(missing_ok=True)
            self.add_message(self.settings["name"], f"{label} 연결을 지웠어.")
        except OSError as exc:
            messagebox.showerror("메일 연결 해제", str(exc), parent=self.root)

    def show_recent_mail(self) -> None:
        if not self._mail_busy():
            return
        providers = [name for name, path in (("Gmail", self.gmail_token_path),
                                             ("메일플러그", self.mailplug_account_path)) if path.exists()]
        if not providers:
            self.events.put(("answer", "톱니 → 메일 계정에서 Gmail이나 메일플러그를 먼저 연결해줘."))
            return

        def read() -> None:
            sections = []
            for provider in providers:
                try:
                    messages = (recent_gmail(self.gmail_token_path) if provider == "Gmail" else
                                recent_mailplug(self.mailplug_account_path))
                    lines = [f"{item['subject'][:90]} — {item['from'][:90]}" +
                             (f"\n  {item['snippet'][:120]}" if item["snippet"] else "") for item in messages]
                    sections.append(provider + " 최근 받은 메일:\n" + ("\n".join(lines) if lines else "없음"))
                except Exception as exc:
                    sections.append(f"{provider} 받은 메일을 읽지 못했어: {exc}")
            self.events.put(("answer", "\n\n".join(sections)))

        threading.Thread(target=read, daemon=True).start()

    def show_mail_preview(self, value: dict) -> str:
        available = [name for name, path in (("gmail", self.gmail_token_path),
                                              ("mailplug", self.mailplug_account_path)) if path.exists()]
        provider = value.get("provider")
        if provider and provider not in available:
            return f"{provider} 계정이 연결되지 않았어. 톱니 → 메일 계정에서 먼저 연결해줘."
        if not available:
            return "메일 계정이 없어. 톱니 → 메일 계정에서 Gmail이나 메일플러그를 연결해줘."
        if not value.get("to") or not value.get("subject") or not value.get("body"):
            return "메일을 보내려면 받는 사람의 정확한 이메일 주소, 제목, 본문을 알려줘."
        window = tk.Toplevel(self.root)
        window.title("메일 발송 전 확인")
        window.geometry("560x470")
        window.configure(bg=self.theme["bg"])
        window.transient(self.root)
        window.attributes("-topmost", True)
        form = tk.Frame(window, bg=self.theme["bg"])
        form.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(form, text="메일 발송 전 확인", bg=self.theme["bg"], fg=self.theme["text"],
                 font=("Malgun Gothic", 12, "bold")).pack(anchor="w", pady=(0, 10))
        selected = tk.StringVar(value=provider or available[0])
        tk.Label(form, text="보내는 계정", bg=self.theme["bg"], fg=self.theme["muted"]).pack(anchor="w")
        tk.OptionMenu(form, selected, *available).pack(anchor="w", pady=(0, 8))
        tk.Label(form, text="받는 사람", bg=self.theme["bg"], fg=self.theme["muted"]).pack(anchor="w")
        to_entry = tk.Entry(form, bg=self.theme["panel"], fg=self.theme["text"], insertbackground=self.theme["text"])
        to_entry.pack(fill="x", ipady=5, pady=(0, 8))
        to_entry.insert(0, value["to"])
        tk.Label(form, text="제목", bg=self.theme["bg"], fg=self.theme["muted"]).pack(anchor="w")
        subject_entry = tk.Entry(form, bg=self.theme["panel"], fg=self.theme["text"], insertbackground=self.theme["text"])
        subject_entry.pack(fill="x", ipady=5, pady=(0, 8))
        subject_entry.insert(0, value["subject"])
        tk.Label(form, text="본문", bg=self.theme["bg"], fg=self.theme["muted"]).pack(anchor="w")
        body_editor = tk.Text(form, bg=self.theme["panel"], fg=self.theme["text"], insertbackground=self.theme["text"],
                              wrap="word", relief="flat")
        body_editor.pack(fill="both", expand=True, pady=(0, 10))
        body_editor.insert("1.0", value["body"])
        buttons = tk.Frame(form, bg=self.theme["bg"])
        buttons.pack(fill="x")

        def send() -> None:
            try:
                to = to_entry.get().strip()
                validate_recipients(to)
                subject = subject_entry.get().strip()
                body = body_editor.get("1.0", "end").strip()
                if not subject or not body:
                    raise ValueError("제목과 본문을 입력해줘.")
            except ValueError as exc:
                messagebox.showerror("메일 발송 전 확인", str(exc), parent=window)
                return
            account = selected.get()
            window.destroy()

            def deliver() -> None:
                try:
                    if account == "gmail":
                        send_gmail(self.gmail_token_path, to, subject, body)
                    else:
                        send_mailplug(self.mailplug_account_path, to, subject, body)
                    self.events.put(("answer", f"{account}에서 '{subject}' 메일을 {to}로 보냈어."))
                except Exception as exc:
                    self.events.put(("error", f"메일을 보내지 못했어: {exc}"))

            threading.Thread(target=deliver, daemon=True).start()

        tk.Button(buttons, text="보내기", command=send, bg=self.theme["button"], fg=self.theme["text"],
                  relief="flat", font=("Malgun Gothic", 10, "bold")).pack(side="right", ipadx=14, ipady=5)
        tk.Button(buttons, text="취소", command=window.destroy, bg=self.theme["panel"], fg=self.theme["text"],
                  relief="flat").pack(side="right", padx=(0, 8), ipadx=12, ipady=5)
        return "메일 내용을 확인하고 보내기 버튼을 눌러줘. 아직 발송하지 않았어."
