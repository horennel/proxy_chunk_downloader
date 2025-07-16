import subprocess
import re
import os
import threading
import time
from collections import deque

from bark_python import BarkClient, CBCStrategy

# 正则表达式用于提取通知中的字符串内容
string_pattern = re.compile(r'string "(.*?)"')

# 保存最近几条通知内容及时间戳
recent_notifications = deque(maxlen=10)  # 最多保留10条通知


def is_duplicate(app, title, body, window=2):
    """检查是否在过去 window 秒内已经收到相同的通知"""
    key = f"{app}:{title}:{body}"
    now = time.time()
    for ts, k in recent_notifications:
        if k == key and now - ts < window:
            return True
    recent_notifications.append((now, key))
    return False


def monitor_notifications():
    process = subprocess.Popen(
        ['dbus-monitor', "interface='org.freedesktop.Notifications'"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1
    )

    buffer = []
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue

        buffer.append(line)

        # 开始新的一条通知
        if 'member=Notify' in line:
            buffer.clear()
            buffer.append(line)
        elif len(buffer) >= 8:  # 通常一条完整 Notify 在 8 行左右
            strings = string_pattern.findall("\n".join(buffer))

            if len(strings) >= 4:
                app = strings[0]
                title = strings[2]
                body = strings[3]

                if not is_duplicate(app, title, body):
                    client.send_notification(
                        title=f"🌈 {app}的通知",
                        body=f"{title}\n{body}",
                        sound="shake",
                        icon=os.getenv('BARK_ICON')
                    )
                    print(f"[{app}] {title} - {body}")

            buffer.clear()


def run_monitor_in_thread():
    t = threading.Thread(target=monitor_notifications, daemon=True)
    t.start()
    print("✅ 正在监听系统通知（时间+内容去重）...")


if __name__ == '__main__':
    client = BarkClient(device_key=os.getenv('BARK_DEVICE_KEY'), api_url=os.getenv('BARK_URL'))
    client.set_encryption(
        key=os.getenv('BARK_KEY'),
        iv=os.getenv('BARK_IV'),
        strategy_cls=CBCStrategy
    )

    run_monitor_in_thread()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 已退出监听")
