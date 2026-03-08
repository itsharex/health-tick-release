#!/usr/bin/env python3
"""健康打卡 (HealthTick) - macOS 菜单栏健康提醒应用"""

import json
import os
import random
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, date, timedelta
from ctypes import c_uint64, c_double, CDLL

import objc
import rumps
from AppKit import (
    NSWindow, NSTextField, NSButton, NSSlider, NSTextView,
    NSScrollView, NSFont, NSColor, NSBackingStoreBuffered,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSMakeRect, NSBezelStyleRounded,
    NSApp, NSFloatingWindowLevel, NSScreenSaverWindowLevel,
    NSScreen, NSPanel, NSTextAlignmentCenter, NSView,
)
from Foundation import NSObject

# --- 路径 ---
DATA_DIR = os.path.expanduser("~/.health-tick")
DB_FILE = os.path.join(DATA_DIR, "data.db")
STATS_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.html")

# --- 默认配置 ---
DEFAULT_CONFIG = {
    "work_minutes": 60,
    "break_minutes": 2,
    "daily_goal": 8,
    "reminders": '["该起来走走了", "该喝水了"]',
}

ICON_WORKING = "🟢"
ICON_BREAK = "🟡"
ICON_PAUSED = "⏸"
ICON_WAITING = "🔴"

# --- 徽章定义 ---
BADGES = [
    (7, "初心者", "连续达标 7 天"),
    (14, "习惯养成", "连续达标 14 天"),
    (30, "健康达人", "连续达标 30 天"),
    (60, "钢铁意志", "连续达标 60 天"),
    (100, "传奇坚持", "连续达标 100 天"),
]

# ===================== 用户空闲检测 =====================

# 通过 IOKit 获取用户空闲时间（秒），无需额外权限
_iokit = CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
_cf = CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

_iokit.IOServiceGetMatchingService.restype = c_uint64
_iokit.IORegistryEntryCreateCFProperty.restype = c_uint64
_cf.CFNumberGetValue.restype = c_uint64


def get_idle_seconds():
    """获取用户空闲时间（秒）：无鼠标/键盘活动的时间"""
    try:
        # 使用 ioreg 命令获取，更稳定
        result = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
            capture_output=True, text=True, timeout=2,
        )
        for line in result.stdout.split("\n"):
            if "HIDIdleTime" in line:
                # 值是纳秒
                val = int(line.split("=")[-1].strip())
                return val / 1_000_000_000
    except Exception:
        pass
    return 0


# ===================== 数据层 =====================

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    ensure_data_dir()
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_records_date ON records(date);
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    for key, value in DEFAULT_CONFIG.items():
        conn.execute(
            "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
    conn.commit()
    conn.close()


def load_config():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    conn.close()
    cfg = {}
    for key, value in rows:
        if key in ("work_minutes", "break_minutes", "daily_goal"):
            cfg[key] = int(value)
        elif key == "reminders":
            cfg[key] = json.loads(value)
        else:
            cfg[key] = value
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = int(v) if k in ("work_minutes", "break_minutes", "daily_goal") else v
    return cfg


def save_config(config):
    conn = get_db()
    for key, value in config.items():
        db_value = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value)
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, db_value),
        )
    conn.commit()
    conn.close()


def add_record():
    conn = get_db()
    conn.execute(
        "INSERT INTO records (timestamp, date) VALUES (?, ?)",
        (datetime.now().isoformat(), date.today().isoformat()),
    )
    conn.commit()
    conn.close()


def today_count():
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM records WHERE date = ?",
        (date.today().isoformat(),),
    ).fetchone()[0]
    conn.close()
    return count


def streak_days(daily_goal):
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) as cnt FROM records GROUP BY date ORDER BY date DESC"
    ).fetchall()
    conn.close()
    if not rows or rows[0][0] != date.today().isoformat():
        return 0
    streak = 0
    for _, cnt in rows:
        if cnt >= daily_goal:
            streak += 1
        else:
            break
    return streak


def max_streak_days(daily_goal):
    """历史最长连续达标天数"""
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) as cnt FROM records GROUP BY date ORDER BY date"
    ).fetchall()
    conn.close()
    if not rows:
        return 0
    max_s = 0
    cur_s = 0
    prev_date = None
    for row_date, cnt in rows:
        d = date.fromisoformat(row_date)
        if cnt >= daily_goal:
            if prev_date and (d - prev_date).days == 1:
                cur_s += 1
            else:
                cur_s = 1
            max_s = max(max_s, cur_s)
        else:
            cur_s = 0
        prev_date = d
    return max_s


def recent_7_days_counts():
    today = date.today()
    start = (today - timedelta(days=6)).isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) FROM records WHERE date >= ? GROUP BY date",
        (start,),
    ).fetchall()
    conn.close()
    count_map = dict(rows)
    result = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        result.append((d, count_map.get(d, 0)))
    return result


def week_completion_rate(daily_goal):
    """本周达标率"""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) FROM records WHERE date >= ? GROUP BY date",
        (monday.isoformat(),),
    ).fetchall()
    conn.close()
    days_passed = (today - monday).days + 1
    days_completed = sum(1 for _, cnt in rows if cnt >= daily_goal)
    return days_completed, days_passed


def month_completion_rate(daily_goal):
    """本月达标率"""
    today = date.today()
    first_day = today.replace(day=1)
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) FROM records WHERE date >= ? GROUP BY date",
        (first_day.isoformat(),),
    ).fetchall()
    conn.close()
    days_passed = (today - first_day).days + 1
    days_completed = sum(1 for _, cnt in rows if cnt >= daily_goal)
    return days_completed, days_passed


def days_since_last_goal(daily_goal):
    """距离上次达标过了几天（0=今天达标了）"""
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) as cnt FROM records GROUP BY date ORDER BY date DESC"
    ).fetchall()
    conn.close()
    today = date.today()
    for row_date, cnt in rows:
        if cnt >= daily_goal:
            return (today - date.fromisoformat(row_date)).days
    return -1


def get_all_records_for_stats():
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) as cnt FROM records GROUP BY date ORDER BY date"
    ).fetchall()
    conn.close()
    return [{"date": row[0], "count": row[1]} for row in rows]


# ===================== 弹窗 =====================

def show_break_alert_repeat(reminder_text, callback, stop_event):
    """显示休息提醒，若用户不响应则每15秒重复提示音"""
    subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
    script = f'''
    tell application "System Events"
        activate
        display alert "健康打卡" message "{reminder_text}" as warning buttons {{"好的，我去休息"}} default button 1
    end tell
    '''
    # 后台线程重复播放提示音
    def repeat_sound():
        while not stop_event.is_set():
            stop_event.wait(15)
            if not stop_event.is_set():
                subprocess.Popen(["afplay", "/System/Library/Sounds/Ping.aiff"])

    sound_thread = threading.Thread(target=repeat_sound, daemon=True)
    sound_thread.start()

    subprocess.run(["osascript", "-e", script], capture_output=True)
    stop_event.set()
    callback()


def show_confirm_dialog():
    script = '''
    tell application "System Events"
        display dialog "休息结束啦！准备好继续工作了吗？" buttons {"我回来了"} default button 1 with title "健康打卡" with icon note
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


# ===================== 休息遮罩窗口 =====================

class BreakOverlayManager:
    """休息期间的全屏半透明遮罩，监督用户真的离开电脑"""

    def __init__(self):
        self.windows = []
        self.active = False
        self.check_thread = None
        self.remaining_seconds = 0
        self.countdown_label = None
        self.message_label = None
        self.warning_label = None

    def show(self, break_seconds):
        self.remaining_seconds = break_seconds
        self.active = True
        self._create_overlay()
        self.check_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.check_thread.start()

    def hide(self):
        self.active = False
        for w in self.windows:
            try:
                w.orderOut_(None)
            except Exception:
                pass
        self.windows.clear()

    def _create_overlay(self):
        for screen in NSScreen.screens():
            frame = screen.frame()
            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                frame,
                NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
                NSBackingStoreBuffered,
                False,
            )
            panel.setLevel_(NSScreenSaverWindowLevel)
            panel.setOpaque_(False)
            panel.setAlphaValue_(0.85)
            panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.05, 0.08, 0.05, 0.85
            ))
            panel.setIgnoresMouseEvents_(False)
            panel.setCanBecomeKeyWindow_(True)

            content = panel.contentView()
            w = frame.size.width
            h = frame.size.height
            cy = h / 2

            # 标题
            title = NSTextField.alloc().initWithFrame_(NSMakeRect(0, cy + 80, w, 50))
            title.setStringValue_("休息时间")
            title.setBezeled_(False)
            title.setDrawsBackground_(False)
            title.setEditable_(False)
            title.setSelectable_(False)
            title.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.9, 0.4, 1.0))
            title.setFont_(NSFont.boldSystemFontOfSize_(42))
            title.setAlignment_(NSTextAlignmentCenter)
            content.addSubview_(title)

            # 倒计时
            countdown = NSTextField.alloc().initWithFrame_(NSMakeRect(0, cy - 10, w, 80))
            countdown.setStringValue_(self._fmt(self.remaining_seconds))
            countdown.setBezeled_(False)
            countdown.setDrawsBackground_(False)
            countdown.setEditable_(False)
            countdown.setSelectable_(False)
            countdown.setTextColor_(NSColor.whiteColor())
            countdown.setFont_(NSFont.monospacedSystemFontOfSize_weight_(64, 0.3))
            countdown.setAlignment_(NSTextAlignmentCenter)
            content.addSubview_(countdown)
            if self.countdown_label is None:
                self.countdown_label = countdown

            # 提示文字
            msg = NSTextField.alloc().initWithFrame_(NSMakeRect(0, cy - 80, w, 30))
            msg.setStringValue_("请离开电脑，起来走走")
            msg.setBezeled_(False)
            msg.setDrawsBackground_(False)
            msg.setEditable_(False)
            msg.setSelectable_(False)
            msg.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.7, 0.7, 0.7, 1.0))
            msg.setFont_(NSFont.systemFontOfSize_(18))
            msg.setAlignment_(NSTextAlignmentCenter)
            content.addSubview_(msg)
            if self.message_label is None:
                self.message_label = msg

            # 警告文字（检测到操作时显示）
            warn = NSTextField.alloc().initWithFrame_(NSMakeRect(0, cy - 130, w, 30))
            warn.setStringValue_("")
            warn.setBezeled_(False)
            warn.setDrawsBackground_(False)
            warn.setEditable_(False)
            warn.setSelectable_(False)
            warn.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.4, 0.3, 1.0))
            warn.setFont_(NSFont.boldSystemFontOfSize_(16))
            warn.setAlignment_(NSTextAlignmentCenter)
            content.addSubview_(warn)
            if self.warning_label is None:
                self.warning_label = warn

            panel.makeKeyAndOrderFront_(None)
            self.windows.append(panel)

        NSApp.activateIgnoringOtherApps_(True)

    def _fmt(self, secs):
        m, s = divmod(max(0, int(secs)), 60)
        return f"{m:02d}:{s:02d}"

    def _monitor_loop(self):
        """每秒更新倒计时，检测用户是否在操作电脑"""
        while self.active and self.remaining_seconds > 0:
            time.sleep(1)
            self.remaining_seconds -= 1

            # 更新倒计时显示
            if self.countdown_label:
                try:
                    self.countdown_label.setStringValue_(self._fmt(self.remaining_seconds))
                except Exception:
                    pass

            # 检测用户活动
            idle = get_idle_seconds()
            if idle < 3 and self.remaining_seconds > 0:
                if self.warning_label:
                    try:
                        self.warning_label.setStringValue_("检测到操作！请放下手中的工作，休息一下")
                    except Exception:
                        pass
                # 重新播放提示音
                subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
            else:
                if self.warning_label:
                    try:
                        self.warning_label.setStringValue_("")
                    except Exception:
                        pass


# ===================== 设置窗口 =====================

def make_label(text, frame, size=13, bold=False):
    label = NSTextField.alloc().initWithFrame_(frame)
    label.setStringValue_(text)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    label.setFont_(font)
    return label


class SettingsWindowController(NSObject):
    @objc.python_method
    def initWithConfig_onSave_(self, config, on_save):
        self = objc.super(SettingsWindowController, self).init()
        self.config = config.copy()
        self.on_save = on_save
        self.window = None
        self.work_slider = None
        self.break_slider = None
        self.goal_slider = None
        self.work_label = None
        self.break_label = None
        self.goal_label = None
        self.text_view = None
        return self

    @objc.python_method
    def show(self):
        if self.window and self.window.isVisible():
            self.window.makeKeyAndOrderFront_(None)
            return

        W, H = 420, 540
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(200, 200, W, H), style, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("健康打卡 - 设置")
        self.window.setLevel_(NSFloatingWindowLevel)
        self.window.center()

        content = self.window.contentView()
        y = H - 50

        content.addSubview_(make_label("工作时长", NSMakeRect(20, y, 100, 20), size=14, bold=True))
        y -= 35
        self.work_slider = NSSlider.alloc().initWithFrame_(NSMakeRect(20, y, 280, 24))
        self.work_slider.setMinValue_(5)
        self.work_slider.setMaxValue_(120)
        self.work_slider.setIntValue_(self.config["work_minutes"])
        self.work_slider.setContinuous_(True)
        self.work_slider.setTarget_(self)
        self.work_slider.setAction_(self.workSliderChanged_)
        content.addSubview_(self.work_slider)
        self.work_label = make_label(f"{self.config['work_minutes']} 分钟", NSMakeRect(310, y, 90, 24), size=14)
        content.addSubview_(self.work_label)
        y -= 45

        content.addSubview_(make_label("休息时长", NSMakeRect(20, y, 100, 20), size=14, bold=True))
        y -= 35
        self.break_slider = NSSlider.alloc().initWithFrame_(NSMakeRect(20, y, 280, 24))
        self.break_slider.setMinValue_(1)
        self.break_slider.setMaxValue_(15)
        self.break_slider.setIntValue_(self.config["break_minutes"])
        self.break_slider.setContinuous_(True)
        self.break_slider.setTarget_(self)
        self.break_slider.setAction_(self.breakSliderChanged_)
        content.addSubview_(self.break_slider)
        self.break_label = make_label(f"{self.config['break_minutes']} 分钟", NSMakeRect(310, y, 90, 24), size=14)
        content.addSubview_(self.break_label)
        y -= 45

        content.addSubview_(make_label("每日目标", NSMakeRect(20, y, 100, 20), size=14, bold=True))
        y -= 35
        self.goal_slider = NSSlider.alloc().initWithFrame_(NSMakeRect(20, y, 280, 24))
        self.goal_slider.setMinValue_(1)
        self.goal_slider.setMaxValue_(20)
        self.goal_slider.setIntValue_(self.config["daily_goal"])
        self.goal_slider.setContinuous_(True)
        self.goal_slider.setTarget_(self)
        self.goal_slider.setAction_(self.goalSliderChanged_)
        content.addSubview_(self.goal_slider)
        self.goal_label = make_label(f"{self.config['daily_goal']} 次", NSMakeRect(310, y, 90, 24), size=14)
        content.addSubview_(self.goal_label)
        y -= 50

        content.addSubview_(make_label("提醒内容（每行一条，随机选取）", NSMakeRect(20, y, 380, 20), size=14, bold=True))
        y -= 140
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, y, 380, 130))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(2)
        self.text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 360, 130))
        self.text_view.setFont_(NSFont.systemFontOfSize_(13))
        self.text_view.setString_("\n".join(self.config["reminders"]))
        scroll.setDocumentView_(self.text_view)
        content.addSubview_(scroll)

        save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 110, 15, 90, 32))
        save_btn.setTitle_("保存")
        save_btn.setBezelStyle_(NSBezelStyleRounded)
        save_btn.setTarget_(self)
        save_btn.setAction_(self.saveClicked_)
        content.addSubview_(save_btn)

        cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 210, 15, 90, 32))
        cancel_btn.setTitle_("取消")
        cancel_btn.setBezelStyle_(NSBezelStyleRounded)
        cancel_btn.setTarget_(self)
        cancel_btn.setAction_(self.cancelClicked_)
        content.addSubview_(cancel_btn)

        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    @objc.IBAction
    def workSliderChanged_(self, sender):
        val = int(sender.intValue())
        self.work_label.setStringValue_(f"{val} 分钟")
        self.config["work_minutes"] = val

    @objc.IBAction
    def breakSliderChanged_(self, sender):
        val = int(sender.intValue())
        self.break_label.setStringValue_(f"{val} 分钟")
        self.config["break_minutes"] = val

    @objc.IBAction
    def goalSliderChanged_(self, sender):
        val = int(sender.intValue())
        self.goal_label.setStringValue_(f"{val} 次")
        self.config["daily_goal"] = val

    @objc.IBAction
    def saveClicked_(self, sender):
        text = str(self.text_view.string())
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            self.config["reminders"] = lines
        self.on_save(self.config)
        self.window.close()

    @objc.IBAction
    def cancelClicked_(self, sender):
        self.window.close()


# ===================== 主应用 =====================

class HealthTickApp(rumps.App):
    def __init__(self):
        super().__init__("健康打卡", title=ICON_WORKING, quit_button=None)

        self.config = load_config()
        self.overlay = BreakOverlayManager()

        # 状态机: working → alerting → breaking → waiting → working
        self.state = "working"
        self.target_time = time.time() + self.config["work_minutes"] * 60
        self.paused_state = None
        self.paused_remaining = 0
        self.alert_stop_event = None

        # --- 菜单项 ---
        self.status_item = rumps.MenuItem("", callback=None)
        self.status_item.set_callback(None)
        self.timer_item = rumps.MenuItem("", callback=None)
        self.timer_item.set_callback(None)
        self.sep1 = rumps.separator

        self.today_item = rumps.MenuItem("", callback=None)
        self.today_item.set_callback(None)
        self.goal_item = rumps.MenuItem("", callback=None)
        self.goal_item.set_callback(None)
        self.streak_item = rumps.MenuItem("", callback=None)
        self.streak_item.set_callback(None)
        self.badge_item = rumps.MenuItem("", callback=None)
        self.badge_item.set_callback(None)
        self.week_item = rumps.MenuItem("", callback=None)
        self.week_item.set_callback(None)
        self.rate_item = rumps.MenuItem("", callback=None)
        self.rate_item.set_callback(None)
        self.encourage_item = rumps.MenuItem("", callback=None)
        self.encourage_item.set_callback(None)
        self.sep2 = rumps.separator

        self.pause_item = rumps.MenuItem("暂停", callback=self.toggle_pause)
        self.reset_item = rumps.MenuItem("重置", callback=self.reset_timer)
        self.sep3 = rumps.separator

        self.settings_item = rumps.MenuItem("设置", callback=self.open_settings)
        self.settings_controller = None

        self.achievement_item = rumps.MenuItem("查看成就", callback=self.open_stats)
        self.quit_item = rumps.MenuItem("退出", callback=self.quit_app)

        self.menu = [
            self.status_item,
            self.timer_item,
            self.sep1,
            self.today_item,
            self.goal_item,
            self.streak_item,
            self.badge_item,
            self.week_item,
            self.rate_item,
            self.encourage_item,
            self.sep2,
            self.pause_item,
            self.reset_item,
            self.sep3,
            self.settings_item,
            self.achievement_item,
            None,
            self.quit_item,
        ]

        self._update_status_display()
        self._update_stats_display()

        self.tick_timer = rumps.Timer(self._on_tick, 1)
        self.tick_timer.start()

    def _on_tick(self, _):
        self.tick()

    # --- 显示 ---

    def _remaining_seconds(self):
        return max(0, int(self.target_time - time.time()))

    def _format_time(self, seconds=None):
        if seconds is None:
            seconds = self._remaining_seconds()
        m, s = divmod(seconds, 60)
        return f"{m:02d}:{s:02d}"

    def _update_status_display(self):
        labels = {
            "working": ("工作中", ICON_WORKING),
            "alerting": ("该休息了！", ICON_BREAK),
            "breaking": ("休息中", ICON_BREAK),
            "waiting": ("等待确认...", ICON_WAITING),
            "paused": ("已暂停", ICON_PAUSED),
        }
        label, icon = labels.get(self.state, ("", ICON_WORKING))
        self.status_item.title = label
        self.title = icon

        if self.state == "paused":
            self.pause_item.title = "继续"
        else:
            self.pause_item.title = "暂停"

    def _update_stats_display(self):
        tc = today_count()
        goal = self.config["daily_goal"]
        progress = min(tc, goal)
        bar = "■" * progress + "□" * (goal - progress)

        self.today_item.title = f"今日: {tc} 次"
        self.goal_item.title = f"目标: {bar} {progress}/{goal}"

        cur_streak = streak_days(goal)
        self.streak_item.title = f"连续达标: {cur_streak} 天"

        # 徽章
        earned = [b for b in BADGES if cur_streak >= b[0] or max_streak_days(goal) >= b[0]]
        if earned:
            latest = earned[-1]
            self.badge_item.title = f"徽章: {latest[1]} ({latest[2]})"
        else:
            next_badge = BADGES[0]
            self.badge_item.title = f"徽章: 距「{next_badge[1]}」还差 {next_badge[0] - cur_streak} 天"

        # 近7天
        week = recent_7_days_counts()
        week_str = " ".join(str(c) for _, c in week)
        self.week_item.title = f"近7天: {week_str}"

        # 完成率
        w_done, w_total = week_completion_rate(goal)
        m_done, m_total = month_completion_rate(goal)
        self.rate_item.title = f"达标率: 本周 {w_done}/{w_total} | 本月 {m_done}/{m_total}"

        # 鼓励文案
        gap = days_since_last_goal(goal)
        if gap == 0:
            self.encourage_item.title = "今日已达标，继续保持！"
        elif gap == -1:
            self.encourage_item.title = "还没有达标记录，今天开始吧！"
        elif gap == 1:
            self.encourage_item.title = "昨天达标了，今天也加油！"
        elif gap <= 3:
            self.encourage_item.title = f"已经 {gap} 天没达标了，重新开始！"
        else:
            self.encourage_item.title = f"距上次达标已 {gap} 天，今天是新的开始！"

    # --- 计时 ---

    def tick(self):
        if self.state in ("paused", "alerting", "waiting"):
            return

        remaining = self._remaining_seconds()
        self.timer_item.title = self._format_time(remaining)

        if remaining <= 0:
            if self.state == "working":
                self._on_work_done()
            elif self.state == "breaking":
                self._on_break_done()

    def _on_work_done(self):
        self.state = "alerting"
        self.timer_item.title = "00:00"
        self._update_status_display()

        reminder = random.choice(self.config["reminders"])
        self.alert_stop_event = threading.Event()

        def alert_then_break():
            show_break_alert_repeat(reminder, self._start_break, self.alert_stop_event)

        threading.Thread(target=alert_then_break, daemon=True).start()

    def _start_break(self):
        break_secs = self.config["break_minutes"] * 60
        self.state = "breaking"
        self.target_time = time.time() + break_secs
        self._update_status_display()
        # 显示全屏遮罩
        self.overlay.show(break_secs)

    def _on_break_done(self):
        self.state = "waiting"
        self.timer_item.title = "00:00"
        self._update_status_display()

        # 隐藏遮罩
        self.overlay.hide()

        add_record()
        self._update_stats_display()

        def confirm_then_work():
            show_confirm_dialog()
            self._resume_work()

        threading.Thread(target=confirm_then_work, daemon=True).start()

    def _resume_work(self):
        self.state = "working"
        self.target_time = time.time() + self.config["work_minutes"] * 60
        self._update_status_display()
        self.timer_item.title = self._format_time()

    # --- 菜单操作 ---

    def toggle_pause(self, _):
        if self.state == "paused" and self.paused_state:
            self.state = self.paused_state
            self.paused_state = None
            self.target_time = time.time() + self.paused_remaining
            self._update_status_display()
        elif self.state in ("working", "breaking"):
            self.paused_remaining = self._remaining_seconds()
            self.paused_state = self.state
            self.state = "paused"
            self._update_status_display()

    def reset_timer(self, _):
        self.state = "working"
        self.paused_state = None
        self.target_time = time.time() + self.config["work_minutes"] * 60
        self._update_status_display()
        self.timer_item.title = self._format_time()

    def open_settings(self, _):
        def on_save(new_config):
            self.config = new_config
            save_config(self.config)
            self._update_stats_display()
            if self.state == "working":
                self.target_time = time.time() + self.config["work_minutes"] * 60
                self.timer_item.title = self._format_time()

        self.settings_controller = SettingsWindowController.alloc().initWithConfig_onSave_(self.config, on_save)
        self.settings_controller.show()

    def open_stats(self, _):
        stats = get_all_records_for_stats()
        data_json = json.dumps(
            {
                "records": stats,
                "daily_goal": self.config["daily_goal"],
                "badges": BADGES,
                "max_streak": max_streak_days(self.config["daily_goal"]),
                "current_streak": streak_days(self.config["daily_goal"]),
            },
            ensure_ascii=False,
        )
        try:
            with open(STATS_HTML, "r", encoding="utf-8") as f:
                html = f.read()
        except FileNotFoundError:
            rumps.alert("错误", f"找不到热力图文件:\n{STATS_HTML}")
            return
        injected = html.replace(
            "</head>",
            f"<script>window.__HEALTH_TICK_DATA__ = {data_json};</script>\n</head>",
        )
        tmp_path = os.path.join(DATA_DIR, "stats_view.html")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(injected)
        subprocess.run(["open", tmp_path])

    def quit_app(self, _):
        self.overlay.hide()
        rumps.quit_application()


if __name__ == "__main__":
    init_db()
    HealthTickApp().run()
