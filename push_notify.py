#!/usr/bin/env python3
"""
แจ้งเตือนเด้งขึ้นมือถือ (Web Push ผ่าน live.atlog.asia/api/push/notify) — เรียกหลังส่งเมลสำเร็จ
ล้ม/ไม่ได้ตั้งโทเค็น = ข้ามเงียบๆ ไม่กระทบเมล
env: PUSH_TOKEN (GitHub secret — ตรงกับ push_config.json บน Mac mini) · SCAN_API_BASE
"""
import json
import os
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def notify(title, body, url="/", tag="signal"):
    tok = os.environ.get("PUSH_TOKEN", "").strip()
    base = os.environ.get("SCAN_API_BASE", "https://live.atlog.asia").rstrip("/")
    if not tok:
        print("push: ไม่มี PUSH_TOKEN — ข้าม")
        return None
    try:
        req = urllib.request.Request(
            base + "/api/push/notify",
            data=json.dumps({"title": title, "body": body, "url": url, "tag": tag}, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "X-Push-Token": tok, "User-Agent": UA})
        r = json.loads(urllib.request.urlopen(req, timeout=40).read())
        print("push:", {k: r.get(k) for k in ("devices", "sent", "removed", "errors")})
        return r
    except Exception as e:
        print("push error:", str(e)[:150])
        return None


def short_list(items, n=6):
    items = list(items)
    return ", ".join(items[:n]) + (" +%d" % (len(items) - n) if len(items) > n else "")
