"""
Ping pong attendance - GitHub Actions version (no server needed).
Runs once an hour (see .github/workflows/pingpong.yml). Each run:
  1. creates / refreshes the pinned board message (next sessions, day + time)
  2. from 12:00 Stockholm time the day before a session: posts a native, non-anonymous
     Telegram poll (as a reply to the board) and pins it
  3. closes and unpins polls whose session has started
Names stay in the Telegram chat history. Only message ids are kept in state.json.
Env: BOT_TOKEN, CHAT_ID, FORCE (set to "true" to post the next session's poll now)
"""
import html
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Stockholm")
SESSIONS = {  # Monday=0 ... Sunday=6
    0: {"name": "دوشنبه", "start": time(16, 0), "end": time(17, 30)},
    3: {"name": "پنجشنبه", "start": time(19, 0), "end": time(21, 0)},
}
OPTIONS = ["میایم", "شاید بیایم", "با میهمان میایم"]
MONTHS = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن", "ژوئیه", "اوت",
          "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
POLL_HOUR = 12      # poll is posted the day before, from this hour on
FOOTER = ""         # e.g. "📍 سالن ... — آدرس"
STATE_FILE = "state.json"


def api(method, **params):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['BOT_TOKEN']}/{method}",
        data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method}: {e.read().decode()}") from None


def fa(x):
    return str(x).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def occurrences(now):
    out = []
    for i in range(8):
        d = (now + timedelta(days=i)).date()
        cfg = SESSIONS.get(d.weekday())
        if cfg:
            start = datetime.combine(d, cfg["start"], tzinfo=TZ)
            end = datetime.combine(d, cfg["end"], tzinfo=TZ)
            if end > now:
                out.append((d, cfg, start, end))
    return out


def title(d, cfg, now):
    delta = (d - now.date()).days
    tag = " (امروز)" if delta == 0 else " (فردا)" if delta == 1 else ""
    return f"{cfg['name']}{tag} {fa(d.day)} {MONTHS[d.month - 1]}"


def times(cfg):
    return f"از {fa(cfg['start'].strftime('%H:%M'))} تا {fa(cfg['end'].strftime('%H:%M'))}"


def board_text(now):
    occ = occurrences(now)
    d, cfg, start, _ = occ[0]
    lines = ["🏓 <b>برنامهٔ پینگ‌پنگ انجمن</b>", "",
             "🟢 در حال برگزاری" if now >= start else "▶️ جلسهٔ بعدی",
             f"<b>{html.escape(title(d, cfg, now))}</b>", times(cfg)]
    if len(occ) > 1:
        d2, cfg2, _, _ = occ[1]
        lines += ["", "بعد از آن:", f"<b>{html.escape(title(d2, cfg2, now))}</b>", times(cfg2)]
    if FOOTER:
        lines += ["", html.escape(FOOTER)]
    return "\n".join(lines)


def ensure_board(state, chat, now):
    text = board_text(now)
    if state.get("board_id"):
        try:
            api("editMessageText", chat_id=chat, message_id=state["board_id"],
                text=text, parse_mode="HTML")
            return
        except RuntimeError as e:
            if "not modified" in str(e):
                return
            print("board missing, recreating:", e)
    msg = api("sendMessage", chat_id=chat, text=text, parse_mode="HTML")
    state["board_id"] = msg["message_id"]
    try:
        api("pinChatMessage", chat_id=chat, message_id=msg["message_id"], disable_notification=True)
    except RuntimeError as e:
        print("could not pin board:", e)


def post_poll(state, chat, d, now):
    key = d.isoformat()
    if key in state["polls"]:
        return
    cfg = SESSIONS[d.weekday()]
    q = f"🏓 پینگ‌پنگ {title(d, cfg, now)}، {times(cfg)} — می‌آیید؟"
    msg = api("sendPoll", chat_id=chat, question=q, options=OPTIONS, is_anonymous=False,
              allows_multiple_answers=False, reply_to_message_id=state.get("board_id"),
              allow_sending_without_reply=True)
    state["polls"][key] = msg["message_id"]
    try:
        api("pinChatMessage", chat_id=chat, message_id=msg["message_id"], disable_notification=True)
    except RuntimeError as e:
        print("could not pin poll:", e)


def main():
    chat = os.environ["CHAT_ID"]
    now = datetime.now(TZ)
    state = {"board_id": None, "polls": {}}
    if os.path.exists(STATE_FILE):
        state.update(json.load(open(STATE_FILE)))

    ensure_board(state, chat, now)

    if os.environ.get("FORCE", "").lower() == "true":
        post_poll(state, chat, occurrences(now)[0][0], now)
    else:
        tomorrow = (now + timedelta(days=1)).date()
        if now.hour >= POLL_HOUR and tomorrow.weekday() in SESSIONS:
            post_poll(state, chat, tomorrow, now)

    for key, mid in list(state["polls"].items()):
        d = datetime.fromisoformat(key).date()
        start = datetime.combine(d, SESSIONS[d.weekday()]["start"], tzinfo=TZ)
        if now >= start:
            for method in ("stopPoll", "unpinChatMessage"):
                try:
                    api(method, chat_id=chat, message_id=mid)
                except RuntimeError as e:
                    print(method, "failed:", e)
            if now >= start + timedelta(days=1):
                del state["polls"][key]

    json.dump(state, open(STATE_FILE, "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
