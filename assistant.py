"""Small Windows desktop companion powered by Codex or Claude Code CLI."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

from PIL import Image, ImageTk
from google_browser import create_calendar_event, trash_calendar_event, trash_drive_folder
from notion_api import trash_page, verify_token
from token_storage import load_token, save_token
from chat_style import decode_export, parse_export, save_examples, load_examples, style_context
from calendar_alerts import CalendarAlerts
from mail_ui import MailMixin


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
RESPONSE_SCHEMA = ROOT / "response.schema.json"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MomoFriends"
SETTINGS = DATA_DIR / "settings.json"
GUIDELINES = DATA_DIR / "guidelines.md"
VOICE_STYLE = DATA_DIR / "voice-style.txt"
CHAT_STYLE = DATA_DIR / "chat-style.dpapi"
CALENDAR_ALERTS = DATA_DIR / "calendar-alerts.json"
NOTION_TOKEN = DATA_DIR / "notion-token.dpapi"
NOTION_MCP_URL = "https://mcp.notion.com/mcp"
DRIVE_URL = "https://drive.google.com/drive/u/0/my-drive"
DEFAULT_MASCOT = "face"
DEFAULT_VOICE_STYLE = (
    "말투는 친한 친구처럼 매우 장난스럽고 편하게 한다. 상황에 맞춰 문장 끝에 '~임', '~함', '~안됨~'을 "
    "자연스럽게 섞고, 물어도 알 수 없는 내용에는 '그걸 내가 어캐암~'처럼 익살스럽게 답한다. "
    "예를 들어 사용자가 '저녁 곱창 회식일정 추가해줘'라고 하면 '에바임~~~ 살쪄서 죽을거임~~~'처럼 "
    "짧게 농담할 수 있다. 다만 농담만 하고 끝내지 말고 요청한 일정 추가를 실제로 진행한 뒤 "
    "성공 여부와 날짜·시간을 같은 말투로 분명하게 알려준다. "
    "매번 같은 유행어나 농담을 반복하지 않는다. 오류·불확실성·중요한 정보는 장난스럽더라도 정확하게 전한다. "
    "사용자가 진지한 고민이나 민감한 주제를 말할 때는 농담을 줄이고 배려해서 답한다. "
)
TEXT_EXTENSIONS = {".txt", ".md", ".log", ".py", ".java", ".sql", ".json", ".xml", ".yaml", ".yml", ".html", ".css", ".js", ".ts"}
DOCUMENT_EXTENSIONS = {".pdf", ".hwp", ".hwpx", ".doc", ".docx", ".xls", ".xlsx",
                       ".ppt", ".pptx", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".csv"}
CHROME_TOOLS = ("list_pages", "new_page", "navigate_page", "select_page", "take_snapshot",
                "click", "fill", "fill_form", "type_text", "press_key", "wait_for", "handle_dialog")
NOTION_READ_TOOLS = ("notion-search", "notion-fetch", "notion-get-tool-access", "notion-get-self",
                     "notion-query-data-sources")
THEMES = {
    "살구 민트": {"bg": "#F7F5F2", "panel": "#FFFEFC", "surface": "#F7F5F2",
                 "user": "#F7E7E1", "assistant": "#E9F3F0", "accent": "#356F6B",
                 "muted": "#5E6966", "button": "#E7F0ED", "border": "#D8DEDA",
                 "text": "#273230", "send_text": "#FFFFFF"},
    "오션 블루": {"bg": "#F4F7F7", "panel": "#FFFFFF", "surface": "#F4F7F7",
                  "user": "#F7E9DC", "assistant": "#E6EFF2", "accent": "#355F77",
                  "muted": "#5E6C73", "button": "#E2EDF1", "border": "#D3E0E3",
                  "text": "#273230", "send_text": "#FFFFFF"},
    "라일락 크림": {"bg": "#F8F6F3", "panel": "#FFFFFF", "surface": "#F8F6F3",
                    "user": "#F9EEDB", "assistant": "#F0ECF6", "accent": "#66587F",
                    "muted": "#6E6975", "button": "#ECE7F2", "border": "#DED9E5",
                    "text": "#273230", "send_text": "#FFFFFF"},
    "다크 민트": {"bg": "#171F21", "panel": "#263235", "surface": "#171F21",
                   "user": "#3D3B3A", "assistant": "#26423E", "accent": "#91D9C6",
                   "muted": "#A8B9B5", "button": "#304C47", "border": "#3D5350",
                   "text": "#F2F6F4", "send_text": "#15312B"},
}


class RoundedMessage(tk.Canvas):
    """A compact chat bubble drawn at the current transcript width."""

    def __init__(self, parent: tk.Widget, who: str, message: str, is_user: bool,
                 theme: dict[str, str], max_width: int) -> None:
        super().__init__(parent, bg=theme["surface"], highlightthickness=0, bd=0)
        self.who = who
        self.message = message.strip()
        self.is_user = is_user
        self.body_font = tkfont.Font(family="Malgun Gothic", size=10)
        self.sender_font = tkfont.Font(family="Malgun Gothic", size=8, weight="bold")
        self.redraw(theme, max_width)

    def redraw(self, theme: dict[str, str], max_width: int) -> None:
        self.delete("all")
        self.configure(bg=theme["surface"])
        bubble_color = theme["user"] if self.is_user else theme["assistant"]
        max_text_width = max(130, min(410, max_width - 28))
        longest_line = max((self.body_font.measure(line) for line in self.message.splitlines()), default=0)
        text_width = max(64, min(max_text_width, longest_line + 5))
        width = text_width + 28
        top = 10 if self.is_user else 26
        content = self.create_text(14, top, text=self.message, anchor="nw",
                                   width=text_width, fill=theme["text"], font=self.body_font)
        bounds = self.bbox(content)
        height = (bounds[3] if bounds else top + 18) + 11
        radius = 17
        self.create_rectangle(radius, 0, width - radius, height, fill=bubble_color, outline="")
        self.create_rectangle(0, radius, width, height - radius, fill=bubble_color, outline="")
        for x in (0, width - 2 * radius):
            for y in (0, height - 2 * radius):
                self.create_oval(x, y, x + 2 * radius, y + 2 * radius,
                                 fill=bubble_color, outline="")
        if not self.is_user:
            self.create_text(14, 8, text=self.who, anchor="nw", fill=theme["accent"],
                             font=self.sender_font)
        self.tag_raise(content)
        self.configure(width=width, height=height)


class DeskBuddy(MailMixin):
    def __init__(self) -> None:
        self.settings = self.load_settings()
        self.theme = THEMES[self.settings["theme"]]
        self.workdir = Path(self.settings["workdir"])
        if not self.workdir.is_dir():
            self.workdir = Path.home()
            self.settings["workdir"] = str(self.workdir)
        self.root = tk.Tk()
        self.root.title(f"{self.settings['name']} · 내 비서")
        try:
            self.root.iconbitmap(str(ROOT / "momo.ico"))
        except tk.TclError:
            pass
        self.root.configure(bg=self.theme["bg"])
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            width = max(360, min(int(self.settings["window_width"]),
                                  self.root.winfo_screenwidth() - 24))
            height = max(420, min(1000, int(self.settings["window_height"]),
                                   self.root.winfo_screenheight() - 70))
        except ValueError:
            width, height = 420, 600
        self.expanded_size = (width, height)
        x = max(0, self.root.winfo_screenwidth() - width - 36)
        y = max(0, self.root.winfo_screenheight() - height - 90)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(88, 88)

        self.collapsed = False
        self.busy = False
        self.process: subprocess.Popen[str] | None = None
        self.chrome_process: subprocess.Popen[bytes] | None = None
        self.chrome_port: int | None = None
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.mail_data_dir = DATA_DIR
        self.calendar_alerts = CalendarAlerts(CALENDAR_ALERTS)
        self.history: list[tuple[str, str]] = []
        self.last_request = ""
        self.drag_x = 0
        self.drag_y = 0
        self.resize_origin: tuple[int, int, int, int, int] | None = None
        self.resize_axis = "both"
        self.message_rows: list[tuple[tk.Frame, RoundedMessage, tk.Canvas | None, bool]] = []
        self.scroll_job: str | None = None

        self.frame = tk.Frame(self.root, bg=self.theme["bg"],
                              highlightbackground=self.theme["border"], highlightthickness=1)
        self.frame.pack(fill="both", expand=True)

        self.header = tk.Frame(self.frame, bg=self.theme["bg"], height=64)
        self.header.pack(fill="x", padx=13, pady=(7, 3))
        self.header.bind("<Button-1>", self.start_drag)
        self.header.bind("<B1-Motion>", self.drag)

        self.avatar = tk.Canvas(self.header, width=44, height=44, bg=self.theme["bg"], highlightthickness=0)
        self.avatar.pack(side="left", padx=(2, 10), pady=5)
        self.avatar_image: ImageTk.PhotoImage | None = None
        self.avatar_item: int | None = None
        self.draw_avatar()
        self.avatar.bind("<Button-1>", self.toggle)

        self.title = tk.Frame(self.header, bg=self.theme["bg"])
        self.title.pack(side="left", fill="x", expand=True)
        self.eyebrow = tk.Label(self.title, text="YOUR DESKTOP FRIEND", fg=self.theme["accent"],
                                bg=self.theme["bg"], font=("Segoe UI", 8, "bold"))
        self.eyebrow.pack(anchor="w", pady=(5, 0))
        self.name_label = tk.Label(self.title, text=self.settings["name"], fg=self.theme["text"],
                                   bg=self.theme["bg"], font=("Malgun Gothic", 14, "bold"))
        self.name_label.pack(anchor="w", pady=(0, 0))
        self.status = tk.Label(self.title, text="준비됨", fg=self.theme["muted"],
                               bg=self.theme["bg"], font=("Malgun Gothic", 8))
        self.status.pack(anchor="w")
        for widget in (self.title, self.eyebrow, self.name_label, self.status):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)

        self.controls = tk.Frame(self.header, bg=self.theme["bg"])
        self.controls.pack(side="right", anchor="n", padx=2, pady=7)
        self.close_button = tk.Button(self.controls, text="×", command=self.close, fg=self.theme["muted"],
                                      bg=self.theme["bg"], activebackground=self.theme["bg"],
                                      activeforeground=self.theme["text"], relief="flat", font=("Arial", 16), bd=0)
        self.close_button.pack(side="right")
        self.fold_button = tk.Button(self.controls, text="−", command=self.toggle, fg=self.theme["muted"],
                                     bg=self.theme["bg"], activebackground=self.theme["bg"],
                                     activeforeground=self.theme["text"], relief="flat", font=("Arial", 15), bd=0)
        self.fold_button.pack(side="right", padx=2)
        self.settings_button = tk.Button(self.controls, text="⚙", command=self.show_settings,
                                         fg=self.theme["muted"], bg=self.theme["bg"],
                                         activebackground=self.theme["bg"], activeforeground=self.theme["text"],
                                         relief="flat", font=("Segoe UI Symbol", 12), bd=0)
        self.settings_button.pack(side="right", padx=2)

        self.body = tk.Frame(self.frame, bg=self.theme["bg"])
        self.body.pack(fill="both", expand=True)
        self.chat_shell = tk.Frame(self.body, bg=self.theme["surface"])
        self.chat_canvas = tk.Canvas(self.chat_shell, bg=self.theme["surface"],
                                     highlightthickness=0, bd=0)
        self.chat_canvas.pack(fill="both", expand=True)
        self.chat_inner = tk.Frame(self.chat_canvas, bg=self.theme["surface"])
        self.chat_window = self.chat_canvas.create_window((0, 0), window=self.chat_inner, anchor="nw")
        self.chat_inner.bind("<Configure>", self.update_chat_region)
        self.chat_canvas.bind("<Configure>", self.update_chat_width)
        self.chat_canvas.bind("<MouseWheel>", self.scroll_chat)
        self.chat_canvas.bind("<Prior>", lambda _event: self.chat_canvas.yview_scroll(-1, "pages"))
        self.chat_canvas.bind("<Next>", lambda _event: self.chat_canvas.yview_scroll(1, "pages"))

        self.folderbar = tk.Frame(self.body, bg=self.theme["bg"])
        self.folder_label = tk.Label(self.folderbar, text="▣  " + self.folder_caption(), anchor="w",
                                     fg=self.theme["muted"], bg=self.theme["bg"],
                                     font=("Malgun Gothic", 8))
        self.folder_label.pack(side="left", fill="x", expand=True)
        self.folder_button = tk.Button(self.folderbar, text="변경", command=self.change_folder,
                                       bg=self.theme["panel"], fg=self.theme["accent"],
                                       activebackground=self.theme["button"], activeforeground=self.theme["accent"],
                                       relief="flat", bd=0, font=("Malgun Gothic", 8))
        self.folder_button.pack(side="right", padx=(5, 0), ipadx=8, ipady=4)

        self.bottom = tk.Canvas(self.body, height=54, bg=self.theme["bg"],
                                highlightthickness=0, bd=0)
        self.entry = tk.Entry(self.bottom, bg=self.theme["panel"], fg=self.theme["text"], insertbackground=self.theme["text"],
                              font=("Malgun Gothic", 10), relief="flat", bd=0)
        self.entry.bind("<Return>", self.send)
        self.send_button = tk.Canvas(self.bottom, width=38, height=38, bg=self.theme["panel"],
                                     highlightthickness=0, bd=0, cursor="hand2")
        self.draw_send_button()
        self.send_button.bind("<Button-1>", self.send)
        self.entry_window = self.bottom.create_window(18, 27, window=self.entry, anchor="w")
        self.send_window = self.bottom.create_window(1, 27, window=self.send_button, anchor="e")
        self.bottom.bind("<Configure>", self.draw_composer)

        # Reserve the controls first; the transcript takes only the remaining space.
        self.bottom.pack(side="bottom", fill="x", padx=15, pady=(0, 18))
        self.folderbar.pack(side="bottom", fill="x", padx=16, pady=(0, 9))
        self.chat_shell.pack(side="top", fill="both", expand=True, padx=11, pady=(0, 10))
        self.resize_grip = tk.Canvas(self.frame, width=17, height=17, bg=self.theme["bg"],
                                     highlightthickness=0, cursor="size_nw_se")
        self.draw_resize_grip()
        self.resize_grip.place(relx=1, rely=1, anchor="se")
        self.resize_grip.bind("<Button-1>", self.start_resize)
        self.resize_grip.bind("<B1-Motion>", self.resize)
        self.resize_grip.bind("<ButtonRelease-1>", self.finish_resize)
        self.resize_side = tk.Canvas(self.frame, width=16, height=64, bg=self.theme["bg"],
                                     highlightthickness=0, cursor="size_we")
        self.draw_side_resize_grip()
        self.resize_side.place(relx=0, rely=0.52, anchor="w")
        self.resize_side.bind("<Button-1>", lambda event: self.start_resize(event, "left"))
        self.resize_side.bind("<B1-Motion>", self.resize)
        self.resize_side.bind("<ButtonRelease-1>", self.finish_resize)

        self.add_message(self.settings["name"], "안녕! 파일·Drive·Notion 작업을 부탁해줘.\n'오늘 브리핑해줘'라고 하면 오늘 일정을 읽어줄게.")
        self.root.after(100, self.poll_events)
        self.root.after(2000, self.poll_calendar_alerts)

    @staticmethod
    def load_settings() -> dict[str, str]:
        defaults = {"name": "모모", "theme": "살구 민트", "mascot": DEFAULT_MASCOT,
                    "workdir": str(Path.home()), "ai_backend": "auto",
                    "window_width": "420", "window_height": "600", "reminder_minutes": "10"}
        try:
            saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
            defaults.update({key: value for key, value in saved.items() if key in defaults and isinstance(value, str)})
        except (FileNotFoundError, ValueError, OSError):
            pass
        if defaults["theme"] not in THEMES:
            defaults["theme"] = "살구 민트"
        if defaults["ai_backend"] not in {"auto", "codex", "claude"}:
            defaults["ai_backend"] = "auto"
        if defaults["reminder_minutes"] not in {"0", "5", "10", "30", "60"}:
            defaults["reminder_minutes"] = "10"
        if Path(defaults["mascot"]).name == "mascot.png":
            defaults["mascot"] = DEFAULT_MASCOT
        return defaults

    def save_settings(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def folder_caption(self) -> str:
        path = str(self.workdir)
        return "📁 " + ("…" + path[-35:] if len(path) > 35 else path)

    def set_workdir(self, value: str, announce: bool = True) -> bool:
        path = Path(value.strip().strip('"')).expanduser()
        if not path.is_absolute():
            path = self.workdir / path
        path = path.resolve()
        if not path.is_dir():
            if announce:
                self.add_message(self.settings["name"], f"폴더를 찾지 못했어: {path}")
            return False
        self.workdir = path
        self.settings["workdir"] = str(path)
        self.save_settings()
        self.folder_label.configure(text="▣  " + self.folder_caption())
        if announce:
            self.add_message(self.settings["name"], f"작업 폴더를 바꿨어: {path}")
        return True

    def change_folder(self) -> None:
        chosen = filedialog.askdirectory(parent=self.root, initialdir=str(self.workdir), title="작업 폴더 선택")
        if chosen:
            self.set_workdir(chosen)

    def draw_avatar(self) -> None:
        self.avatar.delete("all")
        self.avatar_item = None
        if self.settings["mascot"] == DEFAULT_MASCOT:
            center = (39, 39) if self.collapsed else (22, 22)
            x, y = center
            radius = 31 if self.collapsed else 19
            self.avatar.create_oval(x - radius, y - radius, x + radius, y + radius,
                                    fill=self.theme["panel"], outline=self.theme["accent"], width=2)
            eye = 11 if self.collapsed else 8
            self.avatar.create_oval(x - eye, y - 4, x - eye + 3, y - 1, fill=self.theme["accent"], outline="")
            self.avatar.create_oval(x + eye - 3, y - 4, x + eye, y - 1, fill=self.theme["accent"], outline="")
            self.avatar.create_arc(x - 8, y - 3, x + 8, y + 11, start=200, extent=140,
                                   style="arc", outline=self.theme["accent"], width=2)
            return
        path = Path(self.settings["mascot"])
        try:
            with Image.open(path) as original:
                picture = original.convert("RGBA")
                size = 74 if self.collapsed else 42
                picture.thumbnail((size, size), Image.Resampling.LANCZOS)
            self.avatar_image = ImageTk.PhotoImage(picture)
            center = (39, 39) if self.collapsed else (22, 22)
            self.avatar_item = self.avatar.create_image(*center, image=self.avatar_image)
        except (OSError, ValueError):
            self.settings["mascot"] = DEFAULT_MASCOT
            self.draw_avatar()

    def show_settings(self) -> None:
        menu = tk.Menu(self.root, tearoff=False, bg=self.theme["panel"], fg=self.theme["text"],
                       activebackground=self.theme["button"], activeforeground=self.theme["text"])
        menu.add_command(label="이름 바꾸기", command=self.change_name)
        menu.add_command(label="사용자 가이드라인", command=self.edit_guidelines)
        menu.add_command(label="말투 설정", command=self.edit_voice_style)
        menu.add_command(label="카톡 말투 가져오기", command=self.import_chat_style)
        if CHAT_STYLE.exists():
            menu.add_command(label="카톡 말투 지우기", command=self.remove_chat_style)
        menu.add_command(label="Notion API 연결 설정", command=self.configure_notion)
        self.add_mail_menu(menu)
        size_menu = tk.Menu(menu, tearoff=False, bg=self.theme["panel"], fg=self.theme["text"],
                            activebackground=self.theme["button"], activeforeground=self.theme["text"])
        for label, width, height in (("작게", 380, 500), ("보통", 420, 600),
                                     ("넓게", 560, 720), ("크게", 680, 820)):
            size_menu.add_command(label=label, command=lambda w=width, h=height: self.set_window_size(w, h))
        menu.add_cascade(label="대화창 크기", menu=size_menu)
        ai_menu = tk.Menu(menu, tearoff=False, bg=self.theme["panel"], fg=self.theme["text"],
                          activebackground=self.theme["button"], activeforeground=self.theme["text"])
        for value, label in (("auto", "자동 (Codex 우선)"), ("codex", "Codex"), ("claude", "Claude Code")):
            ai_menu.add_command(label=("✓ " if self.settings["ai_backend"] == value else "  ") + label,
                                command=lambda selected=value: self.change_ai_backend(selected))
        menu.add_cascade(label="AI 엔진", menu=ai_menu)
        alert_menu = tk.Menu(menu, tearoff=False, bg=self.theme["panel"], fg=self.theme["text"],
                             activebackground=self.theme["button"], activeforeground=self.theme["text"])
        for minutes, label in (("0", "끄기"), ("5", "5분 전"), ("10", "10분 전"),
                               ("30", "30분 전"), ("60", "1시간 전")):
            alert_menu.add_command(label=("✓ " if self.settings["reminder_minutes"] == minutes else "  ") + label,
                                   command=lambda value=minutes: self.change_reminder_minutes(value))
        menu.add_cascade(label="일정 알림", menu=alert_menu)
        menu.add_command(label="기본 얼굴 사용", command=self.use_default_mascot)
        menu.add_command(label="캐릭터 이미지 바꾸기", command=self.change_mascot)
        menu.add_separator()
        for name in THEMES:
            menu.add_command(label=("✓ " if name == self.settings["theme"] else "  ") + name,
                             command=lambda selected=name: self.change_theme(selected))
        menu.tk_popup(self.settings_button.winfo_rootx(), self.settings_button.winfo_rooty() + 30)
        menu.grab_release()

    def change_name(self) -> None:
        name = simpledialog.askstring("비서 이름", "어떤 이름으로 부를까?", initialvalue=self.settings["name"], parent=self.root)
        if name and name.strip():
            self.settings["name"] = name.strip()[:20]
            self.name_label.configure(text=self.settings["name"])
            self.root.title(f"{self.settings['name']} · 내 비서")
            self.save_settings()

    def change_ai_backend(self, value: str) -> None:
        self.settings["ai_backend"] = value
        self.save_settings()
        self.add_message(self.settings["name"], "AI 엔진 설정을 저장했어. 다음 요청부터 적용할게.")

    def change_reminder_minutes(self, value: str) -> None:
        self.settings["reminder_minutes"] = value
        self.save_settings()
        self.add_message(self.settings["name"], "일정 알림을 껐어." if value == "0" else
                         f"모모에서 추가한 일정은 시작 {value}분 전에 알려줄게. 모모가 실행 중이어야 해.")
        self.check_calendar_alerts()

    def check_calendar_alerts(self) -> None:
        try:
            due = self.calendar_alerts.due(int(self.settings["reminder_minutes"]))
        except (OSError, ValueError) as exc:
            self.add_message(self.settings["name"], f"일정 알림을 확인하지 못했어: {exc}")
            return
        for item in due:
            self.show_calendar_alert(item)

    def poll_calendar_alerts(self) -> None:
        self.check_calendar_alerts()
        self.root.after(15000, self.poll_calendar_alerts)

    def show_calendar_alert(self, item: dict) -> None:
        window = tk.Toplevel(self.root)
        window.title("모모 일정 알림")
        window.configure(bg=self.theme["panel"], highlightbackground=self.theme["accent"], highlightthickness=1)
        window.attributes("-topmost", True)
        window.resizable(False, False)
        window.geometry(f"320x132+{self.root.winfo_screenwidth() - 340}+{self.root.winfo_screenheight() - 200}")
        tk.Label(window, text="◷  일정 다시 알림" if item.get("snoozed") else "◷  곧 시작하는 일정",
                 bg=self.theme["panel"], fg=self.theme["accent"],
                 font=("Malgun Gothic", 10, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        tk.Label(window, text=item["title"], bg=self.theme["panel"], fg=self.theme["text"],
                 font=("Malgun Gothic", 11, "bold"), wraplength=286, justify="left").pack(anchor="w", padx=16)
        tk.Label(window, text=f"{item['day']} {item['start']}", bg=self.theme["panel"], fg=self.theme["muted"],
                 font=("Malgun Gothic", 9)).pack(anchor="w", padx=16, pady=(2, 5))
        buttons = tk.Frame(window, bg=self.theme["panel"])
        buttons.pack(anchor="e", padx=14, pady=(0, 8))
        tk.Button(buttons, text="5분 뒤 다시", command=lambda: self.snooze_calendar_alert(item, window),
                  bg=self.theme["button"], fg=self.theme["text"], relief="flat",
                  font=("Malgun Gothic", 9)).pack(side="left", padx=(0, 8))
        tk.Button(buttons, text="확인", command=window.destroy, bg=self.theme["button"], fg=self.theme["text"],
                  relief="flat", font=("Malgun Gothic", 9)).pack(side="left")
        window.after(30000, lambda: window.destroy() if window.winfo_exists() else None)
        window.lift()
        try:
            self.root.bell()
        except tk.TclError:
            pass

    def snooze_calendar_alert(self, item: dict, window: tk.Toplevel) -> None:
        try:
            saved = self.calendar_alerts.snooze(item["title"], item["day"], item["start"])
        except (OSError, ValueError) as exc:
            self.add_message(self.settings["name"], f"다시 알림을 저장하지 못했어: {exc}")
            return
        if saved:
            window.destroy()
            self.add_message(self.settings["name"], f"'{item['title']}' 일정은 5분 뒤 다시 알려줄게.")

    def import_chat_style(self) -> None:
        filename = filedialog.askopenfilename(parent=self.root, title="카카오톡 대화 파일 선택",
                                               filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")])
        if not filename:
            return
        speaker = simpledialog.askstring("친구 표시 이름", "대화 파일에서 따라 할 친구의 카톡 표시 이름을 입력해줘.",
                                         parent=self.root)
        if speaker is None:
            return
        try:
            examples = parse_export(decode_export(Path(filename)), speaker)
        except (OSError, ValueError) as exc:
            messagebox.showerror("카톡 말투 가져오기", str(exc), parent=self.root)
            return
        sample = "\n".join("• " + item["reply"][:90] for item in examples[:2])
        accepted = messagebox.askyesno(
            "카톡 말투 가져오기",
            f"'{speaker.strip()}'의 대화 예시 {len(examples)}개를 찾았어.\n\n{sample}\n\n"
            "원본 파일은 복사하지 않아. 추린 예시는 이 Windows 계정으로 암호화해 저장하고, "
            "답변할 때 관련 예시 최대 6개를 선택한 AI 엔진에 보낼 거야. 가져올까?",
            parent=self.root)
        if not accepted:
            return
        try:
            save_examples(CHAT_STYLE, speaker.strip(), examples)
        except (OSError, ValueError) as exc:
            messagebox.showerror("카톡 말투 가져오기", str(exc), parent=self.root)
            return
        self.add_message(self.settings["name"], f"'{speaker.strip()}'의 대화 예시 {len(examples)}개를 가져왔어. 다음 답변부터 말투에 참고할게.")

    def remove_chat_style(self) -> None:
        if messagebox.askyesno("카톡 말투 지우기", "저장된 카톡 말투 예시를 지울까?", parent=self.root):
            try:
                CHAT_STYLE.unlink(missing_ok=True)
            except OSError as exc:
                messagebox.showerror("카톡 말투 지우기", str(exc), parent=self.root)
                return
            self.add_message(self.settings["name"], "저장된 카톡 말투 예시를 지웠어.")

    @staticmethod
    def read_voice_style() -> str:
        try:
            return VOICE_STYLE.read_text(encoding="utf-8").strip()[:12000]
        except FileNotFoundError:
            return DEFAULT_VOICE_STYLE
        except OSError:
            return DEFAULT_VOICE_STYLE

    def edit_voice_style(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("모모 말투 설정")
        window.configure(bg=self.theme["bg"])
        window.geometry("520x380")
        window.transient(self.root)
        window.attributes("-topmost", True)
        tk.Label(window, text="모모의 말투를 직접 바꿀 수 있어.",
                 bg=self.theme["bg"], fg=self.theme["text"], font=("Malgun Gothic", 10, "bold")).pack(anchor="w", padx=16, pady=(16, 3))
        tk.Label(window, text="카톡 대화를 가져왔다면 실제 대화 예시도 함께 참고해.",
                 bg=self.theme["bg"], fg=self.theme["muted"], font=("Malgun Gothic", 9)).pack(anchor="w", padx=16, pady=(0, 9))
        buttons = tk.Frame(window, bg=self.theme["bg"])
        buttons.pack(side="bottom", fill="x", padx=16, pady=(0, 15))
        editor = tk.Text(window, bg=self.theme["panel"], fg=self.theme["text"], insertbackground=self.theme["text"],
                         relief="flat", wrap="word", font=("Malgun Gothic", 10), padx=10, pady=10)
        editor.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        editor.insert("1.0", self.read_voice_style())

        def save() -> None:
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                VOICE_STYLE.write_text(editor.get("1.0", "end").strip(), encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("말투 설정", str(exc), parent=window)
                return
            self.add_message(self.settings["name"], "말투 설정을 저장했어. 다음 답변부터 적용할게.")
            window.destroy()

        def reset() -> None:
            try:
                VOICE_STYLE.unlink(missing_ok=True)
            except OSError as exc:
                messagebox.showerror("말투 설정", str(exc), parent=window)
                return
            self.add_message(self.settings["name"], "기본 친구 말투로 되돌렸어.")
            window.destroy()

        tk.Button(buttons, text="저장", command=save, bg=self.theme["button"], fg=self.theme["text"],
                  relief="flat", font=("Malgun Gothic", 9, "bold")).pack(side="right", ipadx=14, ipady=5)
        tk.Button(buttons, text="취소", command=window.destroy, bg=self.theme["panel"], fg=self.theme["text"],
                  relief="flat", font=("Malgun Gothic", 9)).pack(side="right", padx=8, ipadx=12, ipady=5)
        tk.Button(buttons, text="기본값 복원", command=reset, bg=self.theme["panel"], fg=self.theme["text"],
                  relief="flat", font=("Malgun Gothic", 9)).pack(side="left", ipadx=12, ipady=5)
        editor.focus_set()

    @staticmethod
    def read_guidelines() -> str:
        try:
            return GUIDELINES.read_text(encoding="utf-8").strip()[:12000]
        except (FileNotFoundError, OSError):
            return ""

    @staticmethod
    def save_guidelines(value: str) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        GUIDELINES.write_text(value.strip() + ("\n" if value.strip() else ""), encoding="utf-8")

    def edit_guidelines(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("모모 사용자 가이드라인")
        window.configure(bg=self.theme["bg"])
        window.geometry("520x380")
        window.transient(self.root)
        window.attributes("-topmost", True)
        tk.Label(window, text="모모가 매 요청에서 기억할 규칙을 적어줘.",
                 bg=self.theme["bg"], fg=self.theme["text"], font=("Malgun Gothic", 10, "bold")).pack(anchor="w", padx=16, pady=(16, 3))
        tk.Label(window, text="예: 답은 한국어로 짧게. 일정은 저장 후 확인해줘.",
                 bg=self.theme["bg"], fg=self.theme["muted"], font=("Malgun Gothic", 9)).pack(anchor="w", padx=16, pady=(0, 9))
        buttons = tk.Frame(window, bg=self.theme["bg"])
        buttons.pack(side="bottom", fill="x", padx=16, pady=(0, 15))
        editor = tk.Text(window, bg=self.theme["panel"], fg=self.theme["text"], insertbackground=self.theme["text"],
                         relief="flat", wrap="word", font=("Malgun Gothic", 10), padx=10, pady=10)
        editor.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        editor.insert("1.0", self.read_guidelines())

        def save() -> None:
            self.save_guidelines(editor.get("1.0", "end"))
            self.add_message(self.settings["name"], "사용자 가이드라인을 저장했어. 다음 요청부터 적용할게.")
            window.destroy()

        tk.Button(buttons, text="저장", command=save, bg=self.theme["button"], fg=self.theme["text"],
                  relief="flat", font=("Malgun Gothic", 9, "bold")).pack(side="right", ipadx=14, ipady=5)
        tk.Button(buttons, text="취소", command=window.destroy, bg=self.theme["panel"], fg=self.theme["text"],
                  relief="flat", font=("Malgun Gothic", 9)).pack(side="right", padx=8, ipadx=12, ipady=5)
        editor.focus_set()

    def configure_notion(self) -> None:
        token = simpledialog.askstring(
            "Notion API 연결", "Notion Integration 토큰을 입력해줘. 페이지에 Integration 접근 권한도 부여해야 해.\n기존 토큰을 유지하려면 취소해줘.",
            parent=self.root, show="●")
        if token is None:
            return
        try:
            verify_token(token)
            save_token(NOTION_TOKEN, token, "Notion")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Notion API 연결", str(exc), parent=self.root)
            return
        self.add_message(self.settings["name"], "Notion API 연결을 저장했어. 페이지 휴지통 이동에 사용할게.")

    def change_mascot(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="캐릭터 이미지 선택",
                                          filetypes=[("이미지 파일", "*.png *.jpg *.jpeg *.webp *.gif")])
        if path:
            self.settings["mascot"] = path
            self.draw_avatar()
            self.save_settings()

    def use_default_mascot(self) -> None:
        self.settings["mascot"] = DEFAULT_MASCOT
        self.draw_avatar()
        self.save_settings()

    def change_theme(self, name: str) -> None:
        self.settings["theme"] = name
        self.save_settings()
        self.theme = THEMES[name]
        bg, panel, accent, muted = (self.theme[key] for key in ("bg", "panel", "accent", "muted"))
        for widget in (self.root, self.frame, self.header, self.avatar, self.title, self.controls,
                       self.body, self.folderbar, self.resize_grip, self.resize_side):
            widget.configure(bg=bg)
        self.frame.configure(highlightbackground=self.theme["border"])
        for widget in (self.eyebrow, self.name_label, self.status):
            widget.configure(bg=bg)
        self.eyebrow.configure(fg=accent)
        self.name_label.configure(fg=self.theme["text"])
        self.status.configure(fg=muted)
        self.folder_label.configure(bg=bg, fg=muted)
        self.folder_button.configure(bg=panel, fg=accent, activebackground=self.theme["button"])
        for widget in (self.close_button, self.fold_button, self.settings_button):
            widget.configure(bg=bg, activebackground=bg, fg=muted,
                             activeforeground=self.theme["text"])
        surface = self.theme["surface"]
        self.chat_shell.configure(bg=surface)
        self.chat_canvas.configure(bg=surface)
        self.chat_inner.configure(bg=surface)
        for row, bubble, avatar, _is_user in self.message_rows:
            row.configure(bg=surface)
            bubble.redraw(self.theme, min(420, int(self.chat_canvas.winfo_width() * 0.78)))
            if avatar:
                self.draw_message_avatar(avatar)
        self.bottom.configure(bg=bg)
        self.entry.configure(bg=panel, fg=self.theme["text"], insertbackground=self.theme["text"])
        self.send_button.configure(bg=panel)
        self.draw_send_button()
        self.draw_composer()
        self.draw_resize_grip()
        self.draw_side_resize_grip()
        self.draw_avatar()

    def draw_message_avatar(self, avatar: tk.Canvas) -> None:
        avatar.delete("all")
        avatar.configure(bg=self.theme["surface"])
        avatar.create_oval(2, 2, 22, 22, fill=self.theme["panel"],
                           outline=self.theme["accent"], width=1)
        avatar.create_oval(7, 9, 9, 11, fill=self.theme["accent"], outline="")
        avatar.create_oval(15, 9, 17, 11, fill=self.theme["accent"], outline="")
        avatar.create_arc(8, 10, 16, 18, start=200, extent=140,
                           style="arc", outline=self.theme["accent"], width=1)

    def draw_send_button(self) -> None:
        self.send_button.delete("all")
        self.send_button.create_oval(1, 1, 37, 37, fill=self.theme["accent"], outline="")
        self.send_button.create_text(19, 18, text="↑", fill=self.theme["send_text"],
                                     font=("Segoe UI", 16, "bold"))

    def draw_composer(self, _event: tk.Event | None = None) -> None:
        self.bottom.delete("composer")
        width = self.bottom.winfo_width()
        height = 54
        radius = 25
        for inset, color in ((0, self.theme["border"]), (1, self.theme["panel"])):
            left, top, right, bottom = inset, inset, width - inset, height - inset
            r = radius - inset
            self.bottom.create_rectangle(left + r, top, right - r, bottom,
                                          fill=color, outline="", tags="composer")
            self.bottom.create_rectangle(left, top + r, right, bottom - r,
                                          fill=color, outline="", tags="composer")
            for x in (left, right - 2 * r):
                for y in (top, bottom - 2 * r):
                    self.bottom.create_oval(x, y, x + 2 * r, y + 2 * r,
                                             fill=color, outline="", tags="composer")
        self.bottom.tag_lower("composer")
        self.bottom.coords(self.entry_window, 18, height // 2)
        self.bottom.itemconfigure(self.entry_window, width=max(100, width - 76))
        self.bottom.coords(self.send_window, width - 8, height // 2)

    def add_message(self, who: str, message: str) -> None:
        is_user = who == "나"
        row = tk.Frame(self.chat_inner, bg=self.theme["surface"])
        previous_is_user = self.message_rows[-1][3] if self.message_rows else None
        row.pack(fill="x", padx=15, pady=(6 if previous_is_user == is_user else 14, 0))
        avatar = None
        if not is_user:
            avatar = tk.Canvas(row, width=24, height=24, highlightthickness=0,
                               bg=self.theme["surface"])
            avatar.pack(side="left", anchor="n", padx=(0, 7), pady=(3, 0))
            self.draw_message_avatar(avatar)
        bubble = RoundedMessage(row, who, message, is_user, self.theme,
                                min(420, int(self.chat_canvas.winfo_width() * 0.78)))
        bubble.pack(side="right" if is_user else "left")
        bubble.bind("<Button-3>", lambda event, value=message: self.show_message_menu(event, value))
        for widget in (row, bubble, avatar):
            if widget is None:
                continue
            widget.bind("<MouseWheel>", self.scroll_chat)
        self.message_rows.append((row, bubble, avatar, is_user))
        if self.scroll_job is not None:
            self.root.after_cancel(self.scroll_job)
        self.scroll_job = self.root.after_idle(self.scroll_to_latest)

    def scroll_to_latest(self) -> None:
        self.scroll_job = None
        self.chat_inner.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self.chat_canvas.yview_moveto(1.0)

    def show_message_menu(self, event: tk.Event, message: str) -> None:
        menu = tk.Menu(self.root, tearoff=False, bg=self.theme["panel"], fg=self.theme["text"])
        menu.add_command(label="메시지 복사", command=lambda: self.copy_message(message))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def copy_message(self, message: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(message)
        self.status.configure(text="메시지 복사됨")

    def update_chat_region(self, _event: tk.Event) -> None:
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def update_chat_width(self, event: tk.Event) -> None:
        self.chat_canvas.itemconfigure(self.chat_window, width=event.width)
        width = min(420, int(event.width * 0.78))
        for _row, bubble, _avatar, _is_user in self.message_rows:
            bubble.redraw(self.theme, width)

    def scroll_chat(self, event: tk.Event) -> str:
        self.chat_canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def draw_resize_grip(self) -> None:
        self.resize_grip.delete("all")
        color = self.theme["muted"]
        for offset in (4, 8, 12):
            self.resize_grip.create_line(16 - offset, 16, 16, 16 - offset,
                                          fill=color, width=1)

    def draw_side_resize_grip(self) -> None:
        self.resize_side.delete("all")
        color = self.theme["muted"]
        for y in (25, 32, 39):
            self.resize_side.create_oval(6, y, 10, y + 4, fill=color, outline="")

    def start_resize(self, event: tk.Event, axis: str = "both") -> None:
        if not self.collapsed:
            self.resize_axis = axis
            self.resize_origin = (event.x_root, event.y_root,
                                  self.root.winfo_width(), self.root.winfo_height(),
                                  self.root.winfo_x())

    def resize(self, event: tk.Event) -> None:
        if not self.resize_origin:
            return
        origin_x, origin_y, width, height, window_x = self.resize_origin
        if self.resize_axis == "left":
            right = window_x + width
            new_x = max(0, min(right - 360, window_x + event.x_root - origin_x))
            width = right - new_x
            self.expanded_size = (width, height)
            self.root.geometry(f"{width}x{height}+{new_x}+{self.root.winfo_y()}")
            return
        max_width = max(360, self.root.winfo_screenwidth() - self.root.winfo_x() - 12)
        max_height = max(420, self.root.winfo_screenheight() - self.root.winfo_y() - 42)
        width = max(360, min(max_width, width + event.x_root - origin_x))
        height = max(420, min(max_height, height + event.y_root - origin_y))
        self.expanded_size = (width, height)
        self.root.geometry(f"{width}x{height}")

    def finish_resize(self, _event: tk.Event) -> None:
        if self.resize_origin:
            self.resize_origin = None
            self.settings["window_width"] = str(self.expanded_size[0])
            self.settings["window_height"] = str(self.expanded_size[1])
            self.save_settings()

    def set_window_size(self, width: int, height: int) -> None:
        width = max(360, min(width, self.root.winfo_screenwidth() - 24))
        height = max(420, min(height, self.root.winfo_screenheight() - 70))
        self.expanded_size = (width, height)
        self.settings["window_width"] = str(width)
        self.settings["window_height"] = str(height)
        self.save_settings()
        if not self.collapsed:
            x = max(0, min(self.root.winfo_x(), self.root.winfo_screenwidth() - width - 16))
            y = max(0, min(self.root.winfo_y(), self.root.winfo_screenheight() - height - 48))
            self.root.geometry(f"{width}x{height}+{x}+{y}")

    def start_drag(self, event: tk.Event) -> None:
        self.drag_x = event.x_root - self.root.winfo_x()
        self.drag_y = event.y_root - self.root.winfo_y()

    def drag(self, event: tk.Event) -> None:
        self.root.geometry(f"+{event.x_root - self.drag_x}+{event.y_root - self.drag_y}")

    def toggle(self, _event: tk.Event | None = None) -> None:
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.expanded_size = (self.root.winfo_width(), self.root.winfo_height())
            self.body.pack_forget()
            self.title.pack_forget()
            self.controls.pack_forget()
            self.resize_grip.place_forget()
            self.resize_side.place_forget()
            self.header.pack_configure(padx=0, pady=0)
            self.avatar.configure(width=78, height=78)
            self.draw_avatar()
            self.avatar.pack_configure(padx=4, pady=4)
            self.root.geometry(f"88x88+{self.root.winfo_x()}+{self.root.winfo_y()}")
        else:
            self.header.pack_configure(padx=13, pady=(7, 3))
            self.avatar.configure(width=44, height=44)
            self.draw_avatar()
            self.avatar.pack_configure(padx=(2, 10), pady=5)
            self.title.pack(side="left", fill="x", expand=True)
            self.controls.pack(side="right", anchor="n", padx=2, pady=7)
            self.body.pack(fill="both", expand=True)
            self.resize_grip.place(relx=1, rely=1, anchor="se")
            self.resize_side.place(relx=0, rely=0.52, anchor="w")
            width, height = self.expanded_size
            self.root.geometry(f"{width}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}")
            self.entry.focus_set()

    def send(self, _event: tk.Event | None = None) -> None:
        request = self.entry.get().strip()
        if not request or self.busy:
            return
        self.entry.delete(0, "end")
        self.add_message("나", request)
        if self.is_mail_inbox_request(request):
            self.show_recent_mail()
            return
        if request.startswith("/remember ") or request.startswith("기억해줘: "):
            rule = request.split(" ", 1)[1].strip() if request.startswith("/remember ") else request.split(":", 1)[1].strip()
            if rule:
                current = self.read_guidelines()
                self.save_guidelines((current + "\n" if current else "") + "- " + rule)
                self.add_message(self.settings["name"], f"앞으로 기억할게: {rule}")
            return
        if request.lower() in {"/pwd", "pwd"}:
            self.add_message(self.settings["name"], str(self.workdir))
            return
        if request.lower().startswith(("/cd ", "cd ")):
            self.set_workdir(request.split(" ", 1)[1])
            return
        if request.lower().startswith(("/task", "/tasks")):
            self.add_message(self.settings["name"], "친구용 모모에는 할 일 관리 기능이 없어. 일정은 Google Calendar에 추가할 수 있어.")
            return
        self.busy = True
        self.last_request = request
        self.status.configure(text="생각하고 있어…")
        self.send_button.configure(state="disabled")
        threading.Thread(target=self.ask_ai, args=(request, self.workdir, self.history[-3:]), daemon=True).start()

    @staticmethod
    def is_today_briefing(request: str) -> bool:
        normalized = request.strip().casefold()
        return normalized == "/briefing" or bool(re.search(r"(?:오늘|금일)(?:의)?\s*브리핑", normalized))

    @staticmethod
    def is_drive_request(request: str) -> bool:
        return bool(re.search(r"(?:구글\s*)?드라이브|google\s*drive|drive\.google\.com", request, re.IGNORECASE))

    @staticmethod
    def is_drive_folder_trash_request(request: str) -> bool:
        return (DeskBuddy.is_drive_request(request)
                and bool(re.search(r"폴더", request))
                and bool(re.search(r"삭제|지워|지우|없애|휴지통", request)))

    @staticmethod
    def is_notion_request(request: str) -> bool:
        return bool(re.search(r"노션|notion", request, re.IGNORECASE))

    @staticmethod
    def is_meeting_prep(request: str) -> bool:
        return bool(re.search(r"(?:회의|미팅).{0,20}(?:준비|자료)", request))

    @staticmethod
    def find_cli(name: str) -> str | None:
        candidates = [shutil.which(name + ".cmd"), shutil.which(name + ".exe"), shutil.which(name),
                      Path(os.environ.get("APPDATA", "")) / "npm" / (name + ".cmd"),
                      Path.home() / ".local" / "bin" / (name + ".exe")]
        return next((str(path) for path in candidates if path and Path(path).is_file()), None)

    def ask_ai(self, request: str, workdir: Path | None = None,
                  history: list[tuple[str, str]] | None = None) -> None:
        workdir = workdir or self.workdir
        mail_send_request = bool(re.search(r"(?:이?메일|gmail|mailplug).{0,30}(?:보내|발송)|(?:보내|발송).{0,30}(?:이?메일|gmail|mailplug)", request, re.IGNORECASE))
        briefing = self.is_today_briefing(request)
        notion_confirmed = bool(
            history and re.search(r"^(?:ㅇ+|응+|그래|좋아|해|옮기)", request.strip())
            and re.search(r"노션|Notion", history[-1][0], re.IGNORECASE)
            and re.search(r"삭제|지워|지우|없애|휴지통", history[-1][0])
            and re.search(r"휴지통|삭제", history[-1][1]))
        notion_request = self.is_notion_request(request) or notion_confirmed
        notion_trash_request = (notion_confirmed or
                                (notion_request and bool(re.search(r"삭제|지워|지우|없애|휴지통", request))))
        notion_tools = (NOTION_READ_TOOLS
                        + (("notion-create-pages",) if not notion_trash_request and re.search(r"만들|생성|작성|추가", request) else ())
                        + (("notion-update-page",) if not notion_trash_request and re.search(r"수정|변경|고쳐|업데이트", request) else ()))
        meeting_prep = self.is_meeting_prep(request) and not notion_request
        drive_trash_request = self.is_drive_folder_trash_request(request)
        drive_request = meeting_prep or (self.is_drive_request(request) and not drive_trash_request)
        calendar_request = (briefing or meeting_prep or
                            bool(re.search(r"캘린더|calendar", request, re.IGNORECASE)) or
                            (not notion_request and bool(re.search(r"일정|스케줄", request))))
        calendar_create_request = (
            not notion_request and not drive_request and
            bool(re.search(r"추가|등록|만들|생성|잡아", request)) and
            not bool(re.search(r"할\s*일|업무|task|todo", request, re.IGNORECASE)) and
            (calendar_request or bool(re.search(
                r"(?:\d{1,2}월\s*\d{1,2}일|\d{4}-\d{2}-\d{2}).*\d{1,2}:\d{2}", request))))
        calendar_trash_request = (
            not notion_trash_request and not drive_trash_request
            and bool(re.search(r"삭제|지워|지우|없애|취소|휴지통", request))
            and (calendar_request or bool(re.search(r"약속", request))
                 or bool(history and re.search(r"캘린더|calendar|일정", history[-1][0] + history[-1][1], re.IGNORECASE))))
        model_calendar_request = calendar_request and not calendar_trash_request and not calendar_create_request
        preferred = self.settings["ai_backend"]
        backends = ("codex", "claude") if preferred == "auto" else (preferred,)
        selected = next(((backend, self.find_cli(backend)) for backend in backends
                         if self.find_cli(backend)), None)
        executable = selected[1] if selected else None
        if not executable:
            self.events.put(("error", "선택한 AI CLI를 찾지 못했어. Codex 또는 Claude Code CLI를 설치하고 로그인해줘."))
            return
        backend = selected[0]

        recent = "\n".join(f"사용자: {question}\n비서: {answer}" for question, answer in (history or []))
        guidelines = self.read_guidelines()
        voice_style = self.read_voice_style()
        try:
            conversation_style = style_context(request, load_examples(CHAT_STYLE))
        except ValueError as exc:
            self.events.put(("error", str(exc)))
            return
        prompt = (
            "너는 사용자의 데스크톱 개인 비서다. 한국어로 간결하고 정확하게 답한다. "
            + (voice_style + "\n\n" if voice_style else "")
            + ("\n\n" + conversation_style if conversation_style else "") +
            "현재 시간은 " + datetime.now().astimezone().isoformat(timespec="minutes") + "이다. "
            "현재 작업 폴더는 " + str(workdir) + "이다. 사용자의 요청에 따라 이 폴더와 명시된 경로의 파일을 찾고 읽고 수정할 수 있다. "
            "파일을 찾았다고 말하기 전에 실제 경로와 존재 여부를 확인한다. "
            "사용자가 파일을 열거나 띄워 달라고 요청하면 OS에서 직접 열지 말고 최종 응답의 open_file에 절대 경로를 넣는다. "
            "폴더를 열라는 요청도 open_file에 절대 경로를 넣는다. 실제로 열었다고 미리 말하지 않는다. "
            "열라는 요청이 없으면 open_file은 null이다. 실행 파일을 실행하지 않는다. "
            "Notion 페이지 열기 요청이 아니면 open_url은 null이다. "
            "사용자가 작업 폴더를 바꾸라고 하면 경로 존재를 확인하고 change_directory에 그 폴더의 절대 경로를 넣는다. "
            "폴더 변경 요청이 없으면 change_directory는 null이다. 앱이 다음 요청부터 그 폴더를 사용한다. "
            "작업 폴더 밖의 파일을 수정할 권한이 없으면 사용자에게 모모에서 /cd 경로로 해당 폴더를 선택하라고 안내한다. "
            "사용자가 구글 캘린더 작업을 요청하면 chrome-devtools MCP로 Google Calendar 웹 화면을 조작한다. "
            "먼저 로그인 상태를 확인하고, 로그인이나 2단계 인증이 필요하면 사용자가 직접 하도록 안내한다. "
            "로그인 상태만 묻는 경우 계정 이메일이나 일정 상세는 요청받지 않으면 답변에 쓰지 않는다. "
            "날짜나 시간이 모호해 잘못 저장할 가능성이 있으면 실행 전에 물어본다. "
            "일정을 저장했다면 화면에서 생성 여부를 확인한 뒤 완료했다고 답한다. "
            "요청받지 않은 일정은 만들거나 바꾸지 않는다. 비밀번호와 인증 코드는 요구하거나 기록하지 않는다. "
            "Google Calendar가 로그인 화면이나 제품 소개 페이지로 이동하면 MCP가 띄운 Chrome에서 사용자가 직접 로그인해야 한다고 알려준다. "
            "이전 작업이 실패한 뒤 사용자가 무엇을 해야 하냐고 묻는다면 실패 이유와 필요한 다음 행동을 구체적으로 설명한다. "
            "브라우저 연결에 실패하면 성공한 척하지 말고 원인을 말한다. "
            "이 앱에는 할 일 관리 기능이 없다. 할 일 등록이나 완료 요청은 수행하지 않고 기능이 없다고 설명한다. "
            "Drive 폴더 삭제 요청이 아니면 drive_action과 drive_target은 null이다. "
            "Notion 페이지 삭제 요청이 아니면 notion_action, notion_page_id, notion_title은 null이다. "
            "Google Calendar 일정 추가·삭제 요청이 아니면 calendar_action, calendar_title, calendar_date, calendar_start, calendar_end는 null이다. "
            "메일 발송 요청이 아니면 mail_action, mail_provider, mail_to, mail_subject, mail_body는 null이다. "
            "최종 응답은 지정된 JSON 스키마에 맞게 작성한다.\n\n"
            + ("사용자가 저장한 가이드라인:\n" + guidelines + "\n\n" if guidelines else "")
            + ("최근 대화:\n" + recent + "\n\n" if recent else "")
            + "현재 사용자 요청: " + request
        )
        if briefing:
            prompt += (
                "\n오늘 브리핑 전용 지시: 사용자가 지금 요청했으므로 이번 한 번만 조회한다. "
                "Google Calendar의 오늘 날짜 화면을 chrome-devtools MCP로 직접 확인해 오늘 일정을 시간순으로 요약한다. "
                "현재 날짜가 보이지 않으면 Calendar UI에서 오늘로 이동한 후 화면을 다시 확인한다. "
                "화면에서 확인하지 못한 일정은 추측하거나 만들어내지 않는다. "
                "캘린더 화면에서 확인된 시간 구간끼리 겹치면 알려주고, 시간 정보가 없으면 겹친다고 단정하지 않는다. "
                "일정을 생성·수정·삭제하지 않는다."
            )
        if drive_trash_request:
            prompt += (
                "\nDrive 폴더 삭제 요청: 브라우저나 MCP 도구로 직접 삭제하지 않는다. "
                "drive_action은 trash, drive_target은 사용자가 지정한 정확한 폴더 이름으로 적는다. "
                "대상 이름이 불명확하면 두 필드를 null로 두고 정확한 이름을 물어본다. "
                "모모 앱이 전용 Chrome에서 휴지통으로 이동하고 결과를 검증한다. "
                "message에서 완료했다고 미리 말하지 않는다."
            )
        if drive_request:
            prompt += (
                "\nGoogle Drive 요청: chrome-devtools MCP로 drive.google.com 웹 화면을 직접 확인한다. "
                "먼저 list_pages로 기존 Drive 탭을 찾아 선택하고, 없으면 새 Drive 탭을 연다. "
                "로그인이 필요하면 모모가 연 전용 Chrome 창에서 사용자가 직접 로그인하도록 안내한다. "
                "파일이나 폴더를 찾을 때 이름과 위치를 확인하고, 동명이인이면 임의로 선택하지 말고 후보를 알려준다. "
                "파일을 열어 달라는 요청이면 Drive 탭에서 해당 파일을 실제로 열고 화면을 확인한 뒤 답한다. "
                "폴더를 만들어 달라는 요청이면 대상 위치를 확인하고 같은 이름의 폴더가 있는지 먼저 살핀다. "
                "위치가 지정되지 않으면 내 드라이브 최상위에 만든다. 생성 후 폴더가 보이는지 다시 확인한다. "
                "부모 폴더가 모호하거나 접근 권한이 없으면 만들지 말고 사용자에게 설명한다. "
                "요청받지 않은 공유·이동·삭제·업로드는 하지 않는다. Google Drive 인증용 키나 비밀번호를 요구하지 않는다. "
                "Drive 파일은 open_file에 넣지 않는다."
            )
        if meeting_prep:
            prompt += (
                "\n회의 준비 요청: 사용자가 지정한 날짜와 시간에 맞는 Google Calendar 회의를 찾아 제목과 시간을 확인한다. "
                "후보가 여러 개면 임의로 고르지 말고 물어본다. 회의 제목·관련 단어로 Google Drive에서 자료를 검색해 관련성 높은 파일 최대 3개를 이름과 위치로 알려준다. "
                "자료가 없거나 로그인되지 않았으면 그 사실을 밝힌다. 파일·일정을 새로 만들거나 수정하지 않는다."
            )
        if notion_request:
            prompt += (
                "\nNotion 요청: 공식 notion MCP로 실제 페이지를 검색하고 필요하면 fetch로 내용을 확인한다. "
                "Notion 연결이 없거나 인증이 만료되면 성공한 척하지 말고 'codex mcp login notion' 또는 Claude Code의 /mcp 로그인을 안내한다. "
                "페이지 작성·수정은 사용자가 명시적으로 요청했을 때만 한다. 대상 페이지나 위치가 불명확하면 먼저 물어본다. "
                "페이지를 열어 달라고 하면 확인한 Notion 페이지의 https URL을 open_url에 적고, 그 외에는 null로 둔다. "
                "Notion URL을 open_file에 넣지 않는다."
            )
        if notion_trash_request:
            prompt += (
                "\nNotion 페이지 삭제 요청: Notion 도구로 직접 삭제하지 않는다. "
                "search와 fetch로 대상의 정확한 페이지 ID와 제목을 확인한다. "
                "대상이 하나로 특정되면 notion_action=trash, notion_page_id=정확한 ID, notion_title=확인한 제목으로 적는다. "
                "이벤트 페이지 제목 뒤에 시간 표기가 붙어 있으면 그 표기를 포함해도 된다. "
                "여러 후보가 있거나 대상을 특정할 수 없으면 세 필드를 null로 두고 물어본다. "
                "모모 앱이 제목을 다시 검증해 휴지통으로 옮긴다. message에서 완료했다고 미리 말하지 않는다."
            )
        if calendar_trash_request:
            prompt += (
                "\nGoogle Calendar 일정 삭제 요청: 브라우저나 캘린더 도구로 직접 삭제하지 않는다. "
                "대상 제목·날짜·시작 시각이 분명하면 calendar_action=trash, calendar_title=정확한 제목, "
                "calendar_date=YYYY-MM-DD, calendar_start=HH:MM(24시간제)로 적는다. "
                "불명확하면 네 필드를 null로 두고 필요한 정보를 물어본다. "
                "모모 앱이 전용 Chrome에서 정확한 일정을 다시 확인하고 삭제한다. message에서 완료했다고 미리 말하지 않는다."
            )
        if calendar_create_request:
            prompt += (
                "\nGoogle Calendar 일정 추가 요청: 브라우저나 캘린더 도구로 직접 추가하지 않는다. "
                "제목·날짜·시작·종료 시각이 분명하면 calendar_action=create, calendar_title=정확한 제목, "
                "calendar_date=YYYY-MM-DD, calendar_start와 calendar_end=HH:MM(24시간제)로 적는다. "
                "연도가 없으면 현재 연도를 기준으로 한다. 빠진 정보가 있으면 관련 필드를 null로 두고 물어본다. "
                "모모 앱이 전용 Chrome에서 중복 여부와 입력값을 확인한 뒤 저장한다. message에서 완료했다고 미리 말하지 않는다."
            )
        if mail_send_request:
            prompt += (
                "\n메일 발송 요청: 메일 도구나 브라우저로 직접 보내지 않는다. "
                "받는 사람의 정확한 이메일 주소, 제목, 본문이 모두 분명하면 mail_action=send, "
                "mail_to=이메일 주소, mail_subject=제목, mail_body=본문으로 적는다. "
                "사용자가 Gmail이나 메일플러그를 지정하면 mail_provider는 gmail 또는 mailplug이고, 지정하지 않으면 null이다. "
                "받는 사람을 이름만으로 추정하거나 주소가 모호하면 mail_action과 관련 필드를 null로 두고 정확한 주소를 물어본다. "
                "모모 앱이 발송 전 내용을 사용자에게 보여주고 보내기 버튼을 기다린다. message에서 보냈다고 말하지 않는다."
            )
        browser_url = None
        existing_calendar_tab = False
        existing_drive_tab = False
        if model_calendar_request or drive_request:
            if not (shutil.which("npx.cmd") or shutil.which("npx")):
                self.events.put(("error", "Google Calendar와 Drive 기능에는 Node.js의 npx가 필요해. Node.js를 설치해줘."))
                return
            try:
                browser_url = (self.ensure_calendar_browser() if model_calendar_request else
                               self.ensure_google_browser(DRIVE_URL))
                existing_calendar_tab = model_calendar_request and self.has_calendar_tab(browser_url)
                existing_drive_tab = drive_request and self.has_drive_tab(browser_url)
            except OSError as exc:
                self.events.put(("error", f"Google용 Chrome을 열지 못했어: {exc}"))
                return
        if existing_calendar_tab:
            prompt += ("\n중요: 이 Chrome에는 이미 calendar.google.com/calendar/ 경로의 Calendar 앱 탭이 열려 있다. "
                       "반드시 list_pages로 기존 탭을 찾고 select_page로 그 탭을 선택한 뒤 take_snapshot으로 확인한다. "
                       "제품 소개 탭을 보고 로그인 여부를 판단하지 않는다. "
                       + ("Calendar 탭은 재이동하지 않는다. Drive를 볼 때는 Drive 탭을 새로 열어도 된다."
                          if drive_request else "새 탭 생성이나 페이지 재이동은 하지 않는다."))
        if existing_drive_tab:
            prompt += ("\n이 Chrome에는 이미 Drive 탭이 있다. list_pages로 확인한 후 기존 탭을 선택해서 사용한다. "
                       "다른 계정의 Drive로 임의 전환하지 않는다.")
        chrome_tools = tuple(tool for tool in CHROME_TOOLS
                             if (not existing_calendar_tab or drive_request or tool not in {"new_page", "navigate_page"})
                             and (not briefing or tool in {"list_pages", "select_page", "take_snapshot",
                                                            "click", "press_key", "wait_for"}))
        if backend == "codex":
            command = [executable, "--no-daemon", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
                       "-C", str(workdir)]
        else:
            command = [executable, "-p", "--output-format", "json", "--json-schema",
                       RESPONSE_SCHEMA.read_text(encoding="utf-8"), "--permission-mode", "acceptEdits",
                       "--tools", "Read,Glob,Grep,Edit,Write", "--no-session-persistence", "--strict-mcp-config"]
        claude_servers: dict[str, dict] = {}
        claude_allowed: list[str] = []
        if browser_url:
            browser_args = ["/c", "npx", "-y", "chrome-devtools-mcp@latest", f"--browser-url={browser_url}",
                            "--no-usage-statistics", "--no-performance-crux"]
            if backend == "codex":
                command.extend(("-c", "mcp_servers.chrome-devtools.command=cmd.exe",
                                "-c", "mcp_servers.chrome-devtools.required=true",
                                "-c", "mcp_servers.chrome-devtools.startup_timeout_ms=90000",
                                "-c", "mcp_servers.chrome-devtools.enabled_tools=["
                                + ",".join(json.dumps(tool) for tool in chrome_tools) + "]"))
                command.extend(("-c", "mcp_servers.chrome-devtools.args=" + json.dumps(browser_args)))
                for tool in chrome_tools:
                    command.extend(("-c", f"mcp_servers.chrome-devtools.tools.{tool}.approval_mode=approve"))
            else:
                claude_servers["chrome-devtools"] = {"command": "cmd.exe", "args": browser_args}
                claude_allowed.extend("mcp__chrome-devtools__" + tool for tool in chrome_tools)
        if notion_request:
            if backend == "codex":
                command.extend(("-c", "mcp_servers.notion.url=" + NOTION_MCP_URL,
                                "-c", "mcp_servers.notion.required=true",
                                "-c", "mcp_servers.notion.startup_timeout_ms=90000",
                                "-c", "mcp_servers.notion.enabled_tools=["
                                + ",".join(json.dumps(tool) for tool in notion_tools) + "]"))
                for tool in notion_tools:
                    command.extend(("-c", f"mcp_servers.notion.tools.{tool}.approval_mode=approve"))
            else:
                claude_servers["notion"] = {"type": "http", "url": NOTION_MCP_URL}
                claude_allowed.extend("mcp__notion__" + tool for tool in notion_tools)
        if backend == "claude" and claude_servers:
            command.extend(("--mcp-config", json.dumps({"mcpServers": claude_servers}),
                            "--allowedTools", ",".join(claude_allowed)))
        if backend == "codex":
            command.extend(("--output-schema", str(RESPONSE_SCHEMA), "--json", "-"))
        try:
            self.process = subprocess.Popen(
                command, cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert self.process.stdin is not None
            self.process.stdin.write(prompt)
            self.process.stdin.close()
            messages: list[str] = []
            diagnostics: list[str] = []
            assert self.process.stdout is not None
            if backend == "claude":
                output = self.process.stdout.read()
                try:
                    event = json.loads(output)
                    structured = event.get("structured_output") if isinstance(event, dict) else None
                    messages.append(json.dumps(structured, ensure_ascii=False) if isinstance(structured, dict)
                                    else str(event.get("result") or ""))
                except (json.JSONDecodeError, AttributeError):
                    diagnostics.append(output[-500:])
            else:
                for line in self.process.stdout:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        diagnostics.append(line.strip())
                        diagnostics = diagnostics[-20:]
                        continue
                    item = event.get("item") or {}
                    if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                        messages.append(item.get("text", ""))
                    elif event.get("type") in {"error", "turn.failed"}:
                        issue = event.get("message") or event.get("error") or event
                        diagnostics.append(str(issue))
                        diagnostics = diagnostics[-20:]
            code = self.process.wait()
            answer = messages[-1].strip() if messages else ""
            if code != 0 and not answer:
                diagnostic = "\n".join(diagnostics)[-500:]
                if notion_request and any(word in diagnostic.casefold() for word in
                                          ("token expired", "unauthorized", "authentication", "401")):
                    answer = ("Notion 연결이 만료됐어. PowerShell에서 'codex mcp login notion'을 실행해 "
                              "브라우저 로그인을 다시 해줘." if backend == "codex" else
                              "Notion 연결이 만료됐어. Claude Code에서 /mcp를 열고 Notion에 다시 로그인해줘.")
                else:
                    answer = ("Codex" if backend == "codex" else "Claude Code") + " 실행에 실패했어. " + diagnostic
            try:
                parsed = json.loads(answer)
                if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
                    message = parsed["message"]
                    if drive_trash_request:
                        target = parsed.get("drive_target")
                        if parsed.get("drive_action") == "trash" and isinstance(target, str) and target.strip():
                            try:
                                endpoint = self.ensure_google_browser(DRIVE_URL)
                                outcome = trash_drive_folder(endpoint, target)
                            except (OSError, ValueError) as exc:
                                outcome = f"Drive 폴더 삭제 실패: {exc}"
                            message = (message + "\n" if message else "") + outcome
                        elif not target:
                            message = message or "삭제할 Drive 폴더 이름을 정확히 알려줘."
                    if notion_trash_request:
                        page_id = parsed.get("notion_page_id")
                        title = parsed.get("notion_title")
                        if parsed.get("notion_action") == "trash" and isinstance(page_id, str) and isinstance(title, str):
                            try:
                                token = load_token(NOTION_TOKEN, "Notion")
                                if not token:
                                    raise ValueError("톱니 → Notion API 연결 설정에서 Integration 토큰을 저장해줘.")
                                outcome = trash_page(token, page_id, title)
                            except (OSError, ValueError) as exc:
                                outcome = f"Notion 페이지 삭제 실패: {exc}"
                            message = (message + "\n" if message else "") + outcome
                        elif not page_id:
                            message = message or "삭제할 Notion 페이지를 정확히 알려줘."
                    calendar_change = None
                    if calendar_trash_request:
                        title = parsed.get("calendar_title")
                        day = parsed.get("calendar_date")
                        start = parsed.get("calendar_start")
                        if (parsed.get("calendar_action") == "trash" and
                                all(isinstance(value, str) and value.strip() for value in (title, day, start))):
                            try:
                                endpoint = self.ensure_calendar_browser()
                                outcome = trash_calendar_event(endpoint, title, day, start)
                                if outcome.startswith("Google Calendar의 ") and "삭제하고" in outcome:
                                    calendar_change = {"action": "remove", "title": title, "day": day, "start": start}
                            except (OSError, ValueError) as exc:
                                outcome = f"캘린더 일정 삭제 실패: {exc}"
                            message = (message + "\n" if message else "") + outcome
                        elif not title or not day or not start:
                            message = message or "삭제할 일정의 제목, 날짜, 시작 시각을 알려줘."
                    if calendar_create_request:
                        title = parsed.get("calendar_title")
                        day = parsed.get("calendar_date")
                        start = parsed.get("calendar_start")
                        end = parsed.get("calendar_end")
                        if (parsed.get("calendar_action") == "create" and
                                all(isinstance(value, str) and value.strip()
                                    for value in (title, day, start, end))):
                            try:
                                endpoint = self.ensure_calendar_browser()
                                outcome = create_calendar_event(endpoint, title, day, start, end)
                                if outcome.startswith("Google Calendar에 ") or "일정이 이미 캘린더에 있어." in outcome:
                                    calendar_change = {"action": "add", "title": title, "day": day, "start": start}
                            except (OSError, ValueError) as exc:
                                outcome = f"캘린더 일정 추가 실패: {exc}"
                            message = (message + "\n" if message else "") + outcome
                        elif not title or not day or not start or not end:
                            message = message or "추가할 일정의 제목, 날짜, 시작·종료 시각을 알려줘."
                    self.events.put(("result", json.dumps({"message": message,
                                                           "open_file": parsed.get("open_file"),
                                                           "open_url": parsed.get("open_url"),
                                                           "change_directory": parsed.get("change_directory"),
                                                           "calendar_change": calendar_change,
                                                           "mail_action": parsed.get("mail_action") if mail_send_request else None,
                                                           "mail_provider": parsed.get("mail_provider"),
                                                           "mail_to": parsed.get("mail_to"),
                                                           "mail_subject": parsed.get("mail_subject"),
                                                           "mail_body": parsed.get("mail_body"),
                                                           "requested_open": bool(re.search(r"열어|띄워|보여줘", request))},
                                                          ensure_ascii=False)))
                else:
                    self.events.put(("answer", answer or "응답을 받지 못했어. 다시 시도해줘."))
            except json.JSONDecodeError:
                self.events.put(("answer", answer or "응답을 받지 못했어. 다시 시도해줘."))
        except Exception as exc:
            self.events.put(("error", f"AI를 실행하지 못했어: {exc}"))
        finally:
            self.process = None

    def ensure_calendar_browser(self) -> str:
        return self.ensure_google_browser("https://calendar.google.com/")

    @staticmethod
    def existing_google_browser(profile: Path) -> str | None:
        """Find a surviving dedicated Chrome from an earlier Momo process."""
        script = ("Get-CimInstance Win32_Process -Filter \"name = 'chrome.exe'\" | "
                  "Where-Object { $_.CommandLine -and $_.CommandLine -notmatch '--type=' } | "
                  "Select-Object -ExpandProperty CommandLine")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        for command_line in result.stdout.splitlines():
            port = re.search(r"--remote-debugging-port=(\d+)", command_line)
            directory = re.search(r'--user-data-dir=(?:"([^"]+)"|(\S+))', command_line)
            if not port or not directory:
                continue
            try:
                if Path(directory.group(1) or directory.group(2)).resolve() != profile.resolve():
                    continue
                endpoint = f"http://127.0.0.1:{int(port.group(1))}"
                with urllib.request.urlopen(endpoint + "/json/version", timeout=1):
                    return endpoint
            except (OSError, TimeoutError, ValueError):
                continue
        return None

    def ensure_google_browser(self, start_url: str) -> str:
        if self.chrome_process and self.chrome_process.poll() is None and self.chrome_port:
            return f"http://127.0.0.1:{self.chrome_port}"

        chrome = next((path for path in (
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        ) if path.is_file()), None)
        if chrome is None:
            raise OSError("Google Chrome이 설치되어 있지 않아.")

        profile = DATA_DIR / "chrome-profile"
        profile.mkdir(parents=True, exist_ok=True)
        existing = self.existing_google_browser(profile)
        if existing:
            self.chrome_port = int(existing.rsplit(":", 1)[1])
            return existing
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]

        self.chrome_process = subprocess.Popen(
            [str(chrome), f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
             f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
             start_url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        endpoint = f"http://127.0.0.1:{port}"
        for _ in range(40):
            if self.chrome_process.poll() is not None:
                existing = self.existing_google_browser(profile)
                if existing:
                    self.chrome_port = int(existing.rsplit(":", 1)[1])
                    self.chrome_process = None
                    return existing
                raise OSError("Chrome 창이 시작 직후 종료됐어.")
            try:
                with urllib.request.urlopen(endpoint + "/json/version", timeout=0.5):
                    self.chrome_port = port
                    self.events.put(("note", "Google용 Chrome을 열었어. 처음 사용한다면 그 창에서 구글 계정에 직접 로그인해줘."))
                    return endpoint
            except (OSError, TimeoutError):
                time.sleep(0.25)
        raise OSError("Chrome 원격 연결이 준비되지 않았어.")

    @staticmethod
    def has_calendar_tab(endpoint: str) -> bool:
        return DeskBuddy.has_google_tab(endpoint, "calendar.google.com")

    @staticmethod
    def has_drive_tab(endpoint: str) -> bool:
        return DeskBuddy.has_google_tab(endpoint, "drive.google.com")

    @staticmethod
    def has_google_tab(endpoint: str, host: str) -> bool:
        try:
            with urllib.request.urlopen(endpoint + "/json/list", timeout=3) as response:
                pages = json.load(response)
        except (OSError, ValueError):
            return False
        for page in pages:
            if page.get("type") != "page":
                continue
            url = urllib.parse.urlsplit(page.get("url", ""))
            if url.hostname == host and url.path.startswith(
                "/calendar/" if host == "calendar.google.com" else "/drive/"):
                return True
        return False

    def poll_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "result":
                    result = json.loads(value)
                    message = result["message"]
                    if result.get("mail_action") == "send":
                        message = self.show_mail_preview({"provider": result.get("mail_provider"),
                                                          "to": result.get("mail_to"),
                                                          "subject": result.get("mail_subject"),
                                                          "body": result.get("mail_body")})
                    change = result.get("calendar_change")
                    if change:
                        try:
                            if change["action"] == "add":
                                saved = self.calendar_alerts.add(change["title"], change["day"], change["start"])
                                if saved and self.settings["reminder_minutes"] != "0":
                                    message += f"\n모모가 실행 중이면 {self.settings['reminder_minutes']}분 전에 알려줄게."
                            elif change["action"] == "remove":
                                self.calendar_alerts.remove(change["title"], change["day"], change["start"])
                        except (OSError, ValueError) as exc:
                            message += f"\n이 PC의 일정 알림을 저장하지 못했어: {exc}"
                    if result["change_directory"]:
                        changed = self.set_workdir(result["change_directory"], announce=False)
                        message += (f"\n작업 폴더: {self.workdir}" if changed else
                                    f"\n작업 폴더를 바꾸지 못했어: {result['change_directory']}")
                    if result["requested_open"] and result["open_file"]:
                        message += "\n" + self.open_file(result["open_file"])
                    if result["requested_open"] and result.get("open_url"):
                        message += "\n" + self.open_web_url(result["open_url"])
                    self.add_message(self.settings["name"], message)
                    if change and change["action"] == "add":
                        self.check_calendar_alerts()
                else:
                    message = value
                    self.add_message(self.settings["name"], value)
                if kind in ("answer", "error", "result"):
                    if self.last_request:
                        self.history.append((self.last_request, message))
                        self.history = self.history[-6:]
                        self.last_request = ""
                    self.busy = False
                    self.status.configure(text="부르면 도와줄게")
                    self.send_button.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_events)

    @staticmethod
    def open_web_url(value: str) -> str:
        url = urllib.parse.urlsplit(value)
        host = (url.hostname or "").lower()
        allowed = host in {"notion.so", "notion.com", "notion.site"} or host.endswith(
            (".notion.so", ".notion.com", ".notion.site"))
        if url.scheme != "https" or not allowed or url.username or url.password:
            return "Notion 페이지를 열지 못했어. 주소를 확인해줘."
        try:
            os.startfile(value)
            return "Notion 페이지를 브라우저에서 열었어."
        except OSError as exc:
            return f"Notion 페이지를 열지 못했어: {exc}"

    @staticmethod
    def open_file(value: str) -> str:
        path = Path(value)
        if not path.is_absolute() or not path.exists():
            return f"파일 열기에 실패했어. 경로를 확인해줘: {value}"
        suffix = path.suffix.lower()
        try:
            if path.is_dir():
                os.startfile(path)
                return f"폴더를 열었어: {path}"
            if suffix in TEXT_EXTENSIONS:
                subprocess.Popen(["notepad.exe", str(path)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return f"파일을 열었어: {path}"
            if suffix in DOCUMENT_EXTENSIONS:
                os.startfile(path)
                return f"파일을 열었어: {path}"
            subprocess.Popen(["explorer.exe", "/select,", str(path)],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return f"실행하지 않고 파일 위치를 보여줬어: {path}"
        except OSError as exc:
            return f"파일 열기에 실패했어: {exc}"

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
        if self.chrome_process and self.chrome_process.poll() is None:
            self.chrome_process.terminate()
        self.root.destroy()

    def run(self) -> None:
        self.entry.focus_set()
        self.root.mainloop()


if __name__ == "__main__":
    DeskBuddy().run()
