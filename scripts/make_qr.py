"""End-card QR code. Reads app/data/deploy.json's URL once it exists; falls back to the local
dev URL until then, so the end card is never dead before deploy.

  python scripts/make_qr.py
"""
import json, os

import qrcode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
LOCAL_URL = "http://localhost:8000/"


def main():
    deploy_path = P("app", "data", "deploy.json")
    url = LOCAL_URL
    if os.path.exists(deploy_path):
        url = json.load(open(deploy_path)).get("url") or LOCAL_URL
    img = qrcode.make(url, border=2)
    out = P("app", "data", "qr.png")
    img.save(out)
    open(P("app", "data", "qr_url.txt"), "w").write(url)
    print(f"app/data/qr.png -> {url}")


if __name__ == "__main__":
    main()
