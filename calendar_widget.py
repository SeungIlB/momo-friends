"""Small read-only calendar kept at the back of the desktop window stack."""

from __future__ import annotations

import calendar
import queue
import threading
from datetime import date, timedelta
from tkinter import Button, Frame, Label, Toplevel

import win32con
import win32gui

from calendar_feed import fetch_events


class CalendarWidget:
    WIDTH = 322
    HEIGHT = 366

    def __init__(self, root, theme: dict[str, str], get_url, on_connect, on_close,
                 on_move, position: tuple[int, int] | None = None) -> None:
        self.root = root
        self.theme = theme
        self.get_url = get_url
        self.on_connect = on_connect
        self.on_close = on_close
        self.on_move = on_move
        self.month = date.today().replace(day=1)
        self.selected = date.today()
        self.rows: list[dict[str, str]] = []
        self.day_buttons: dict[date, Button] = {}
        self.local_changes: list[dict[str, str]] = []
        self.feed_cache: dict[str, dict[str, object]] = {}
        self.feed_connected = False
        self.pending: queue.Queue[tuple[str, object]] = queue.Queue()
        self.loading = False
        self.refresh_requested = False
        self.request_id = 0
        self.drag_offset: tuple[int, int] | None = None
        self.window = Toplevel(root)
        self.window.title("모모 캘린더")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", False)
        x, y = position or (24, max(24, root.winfo_screenheight() - self.HEIGHT - 78))
        self.window.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self.window.configure(bg=theme["border"])
        self.window.protocol("WM_DELETE_WINDOW", on_close)
        self.window.bind("<ButtonRelease-1>", self._finish_drag)

        panel = Frame(self.window, bg=theme["panel"])
        panel.pack(fill="both", expand=True, padx=1, pady=1)
        header = Frame(panel, bg=theme["panel"])
        header.pack(fill="x", padx=16, pady=(13, 7))
        title = Label(header, text="MY CALENDAR", bg=theme["panel"], fg=theme["accent"],
                      font=("Segoe UI", 9, "bold"))
        title.pack(side="left")
        self._bind_drag(header)
        self._bind_drag(title)
        Button(header, text="×", command=on_close, relief="flat", bd=0,
               bg=theme["panel"], fg=theme["muted"], font=("Segoe UI", 14)).pack(side="right")
        nav = Frame(panel, bg=theme["panel"])
        nav.pack(fill="x", padx=16, pady=(1, 8))
        Button(nav, text="‹", command=lambda: self.change_month(-1), relief="flat", bd=0,
               bg=theme["panel"], fg=theme["accent"], font=("Segoe UI", 17)).pack(side="left")
        self.month_label = Label(nav, bg=theme["panel"], fg=theme["text"],
                                 font=("Malgun Gothic", 12, "bold"))
        self.month_label.pack(side="left", expand=True)
        Button(nav, text="›", command=lambda: self.change_month(1), relief="flat", bd=0,
               bg=theme["panel"], fg=theme["accent"], font=("Segoe UI", 17)).pack(side="right")
        Button(nav, text="↻", command=self.refresh, relief="flat", bd=0,
               bg=theme["panel"], fg=theme["accent"], font=("Segoe UI", 12)).pack(side="right", padx=5)
        self.grid = Frame(panel, bg=theme["panel"])
        for column in range(7):
            self.grid.grid_columnconfigure(column, weight=1, uniform="calendar-day")
        self.grid.pack(fill="x", padx=13)
        self.agenda = Frame(panel, bg=theme["panel"])
        self.agenda.pack(fill="both", expand=True, padx=16, pady=(8, 4))
        self.status = Label(panel, text="", anchor="w", bg=theme["panel"], fg=theme["muted"],
                            font=("Malgun Gothic", 8))
        self.status.pack(fill="x", padx=16, pady=(0, 12))
        self._render()
        self.window.bind("<<CalendarFeedLoaded>>", self._poll)
        self.window.after(100, self._maintain_bottom)
        self.refresh()

    def _bind_drag(self, widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._drag)
        widget.bind("<ButtonRelease-1>", self._finish_drag)

    def _start_drag(self, event) -> None:
        self.drag_offset = (event.x_root - self.window.winfo_x(),
                            event.y_root - self.window.winfo_y())

    def _drag(self, event) -> None:
        if self.drag_offset:
            x = event.x_root - self.drag_offset[0]
            y = event.y_root - self.drag_offset[1]
            self.window.geometry(f"+{x}+{y}")

    def _finish_drag(self, _event=None) -> None:
        if self.drag_offset:
            self.drag_offset = None
            self.on_move(self.window.winfo_x(), self.window.winfo_y())
            self.window.after(30, self._send_bottom)

    def _send_bottom(self) -> None:
        if not self.window.winfo_exists():
            return
        try:
            hwnd = win32gui.GetAncestor(self.window.winfo_id(), win32con.GA_ROOT)
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if not style & win32con.WS_EX_TOOLWINDOW:
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_TOOLWINDOW)
            win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                                  win32con.SWP_NOACTIVATE | win32con.SWP_NOOWNERZORDER)
        except (OSError, AttributeError):
            pass

    def _maintain_bottom(self) -> None:
        if self.window.winfo_exists():
            self._send_bottom()
            self.window.after(15000, self._maintain_bottom)

    def change_month(self, offset: int) -> None:
        year = self.month.year + (self.month.month - 1 + offset) // 12
        month = (self.month.month - 1 + offset) % 12 + 1
        self.month = date(year, month, 1)
        self.selected = self.month
        self._render()
        self.refresh()
        self.window.after(30, self._send_bottom)

    def _render(self) -> None:
        self.month_label.configure(text=f"{self.month.year}년 {self.month.month}월")
        for child in self.grid.winfo_children():
            child.destroy()
        for col, label in enumerate(("월", "화", "수", "목", "금", "토", "일")):
            Label(self.grid, text=label, bg=self.theme["panel"], fg=self.theme["muted"],
                  font=("Malgun Gothic", 8)).grid(row=0, column=col, sticky="nsew", pady=(0, 4))
        marked = {row["day"] for row in self.rows}
        self.day_buttons = {}
        for row_index, week in enumerate(calendar.Calendar().monthdatescalendar(self.month.year, self.month.month), 1):
            for col, day in enumerate(week):
                active = day == self.selected
                text = str(day.day) + (" •" if day.isoformat() in marked else "")
                button = Button(self.grid, text=text, relief="flat", bd=0,
                       bg=self.theme["button"] if active else self.theme["panel"],
                       fg=self.theme["accent"] if active else
                       (self.theme["text"] if day.month == self.month.month else self.theme["muted"]),
                       font=("Malgun Gothic", 8, "bold" if active else "normal"),
                       command=lambda value=day: self.select_day(value))
                button.grid(row=row_index, column=col, sticky="nsew", pady=1)
                self.day_buttons[day] = button
        self._render_agenda()

    def _update_day_markers(self) -> None:
        marked = {row["day"] for row in self.rows}
        for day, button in self.day_buttons.items():
            button.configure(text=str(day.day) + (" •" if day.isoformat() in marked else ""))

    def _style_day_button(self, day: date) -> None:
        button = self.day_buttons.get(day)
        if button is None:
            return
        active = day == self.selected
        button.configure(
            bg=self.theme["button"] if active else self.theme["panel"],
            fg=self.theme["accent"] if active else
            (self.theme["text"] if day.month == self.month.month else self.theme["muted"]),
            font=("Malgun Gothic", 8, "bold" if active else "normal"),
        )

    def select_day(self, day: date) -> None:
        if day.year != self.month.year or day.month != self.month.month:
            self.month = day.replace(day=1)
            self.selected = day
            self._render()
            self.refresh()
        else:
            previous = self.selected
            self.selected = day
            self._style_day_button(previous)
            self._style_day_button(day)
            self._render_agenda()
        self.window.after(30, self._send_bottom)

    def apply_change(self, change: dict[str, str]) -> None:
        """Update the widget immediately after Momo confirms a Calendar write."""
        self.local_changes.append(change)
        self.rows = self._with_local_changes(self.rows)
        self._render()

    def _with_local_changes(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        result = list(rows)
        for change in self.local_changes:
            title, day, start = change["title"], change["day"], change["start"]
            result = [row for row in result if not (row["title"] == title and
                      row["day"] == day and row["time"] == start)]
            if change["action"] == "add":
                result.append({"day": day, "time": start, "title": title, "sort": start})
        result.sort(key=lambda row: (row["day"], row["sort"], row["title"]))
        return result

    def _render_agenda(self) -> None:
        for child in self.agenda.winfo_children():
            child.destroy()
        Label(self.agenda, text=f"{self.selected.month}/{self.selected.day} 일정", bg=self.theme["panel"],
              fg=self.theme["text"], font=("Malgun Gothic", 9, "bold"), anchor="w").pack(fill="x")
        today = [row for row in self.rows if row["day"] == self.selected.isoformat()]
        if not today:
            Label(self.agenda, text="일정 없음" if self.feed_connected else "캘린더 연결 후 일정 표시",
                  bg=self.theme["panel"], fg=self.theme["muted"],
                  font=("Malgun Gothic", 9), anchor="w").pack(fill="x", pady=6)
            if not self.feed_connected:
                Button(self.agenda, text="캘린더 연결", command=self.on_connect, relief="flat",
                       bg=self.theme["button"], fg=self.theme["accent"],
                       font=("Malgun Gothic", 9, "bold")).pack(anchor="w", pady=3)
        for row in today[:4]:
            Label(self.agenda, text=f"{row['time']}  {row['title']}", bg=self.theme["panel"],
                  fg=self.theme["text"], font=("Malgun Gothic", 9), anchor="w")\
                .pack(fill="x", pady=2)
        if len(today) > 4:
            Label(self.agenda, text=f"+ {len(today) - 4}개 더 있음", bg=self.theme["panel"],
                  fg=self.theme["muted"], font=("Malgun Gothic", 8), anchor="w").pack(fill="x")

    def refresh(self) -> None:
        self.request_id += 1
        if self.loading:
            self.refresh_requested = True
            return
        try:
            urls = self.get_url()
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return
        if isinstance(urls, str):
            urls = [urls] if urls else []
        if not urls:
            self.feed_connected = False
            self.status.configure(text="톱니 → 캘린더 위젯에 캘린더 추가")
            self._render_agenda()
            return
        self.feed_connected = True
        weeks = calendar.Calendar().monthdatescalendar(self.month.year, self.month.month)
        first, last = weeks[0][0], weeks[-1][-1] + timedelta(days=1)
        request_id = self.request_id
        self.loading = True
        self.status.configure(text="일정 확인 중…")

        def work() -> None:
            rows: list[dict[str, str]] = []
            errors: list[str] = []
            for url in urls:
                try:
                    rows.extend(fetch_events(url, first, last, self.feed_cache.setdefault(url, {})))
                except ValueError as exc:
                    errors.append(str(exc))
            if rows or len(errors) < len(urls):
                rows.sort(key=lambda row: (row["day"], row["sort"], row["title"]))
                self.pending.put(("rows", (rows, len(errors), request_id)))
            else:
                self.pending.put(("error", (errors[0], request_id)))
            try:
                self.window.event_generate("<<CalendarFeedLoaded>>", when="tail")
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _poll(self, _event=None) -> None:
        if not self.window.winfo_exists():
            return
        try:
            while True:
                kind, value = self.pending.get_nowait()
                self.loading = False
                if kind == "rows":
                    rows, failed, request_id = value
                    if request_id != self.request_id:
                        if self.refresh_requested:
                            self.refresh_requested = False
                            self.refresh()
                        continue
                    rows = self._with_local_changes(rows)
                    changed = rows != self.rows
                    self.rows = rows
                    self.status.configure(text="일부 캘린더 연결 실패" if failed else "모모 일정 변경 시 바로 반영")
                    if changed:
                        self._update_day_markers()
                    self._render_agenda()
                else:
                    error, request_id = value
                    if request_id != self.request_id:
                        if self.refresh_requested:
                            self.refresh_requested = False
                            self.refresh()
                        continue
                    self.status.configure(text=error)
                if self.refresh_requested:
                    self.refresh_requested = False
                    self.refresh()
        except queue.Empty:
            pass

    def destroy(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()
