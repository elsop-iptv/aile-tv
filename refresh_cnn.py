"""CNN Turk'un resmi sitesinden yeni (anahtarli) yayin linkini alir ve playlist.m3u'ya yazar.

Sitenin linki yaklasik 3 saat gecerli, bu yuzden GitHub her 2 saatte bir bunu calistirir.
Link birkac kalite icerir (192p..1080p), oynatici internet hizina gore kendisi secer.
Link alinamazsa liste hic degistirilmez.
"""
import json
import re
import sys
import urllib.request

API = "https://www.cnnturk.com/api/cnnvideo/media?id=62d6814670380e2cdc7c124c&isMobile=false"
NAME = "CNN Turk (Otomatik kalite)"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
PLAYLIST = sys.argv[1] if len(sys.argv) > 1 else "playlist.m3u"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.cnnturk.com/canli-yayin"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read().decode("utf-8", "replace")


def fresh_url():
    _, body = get(API)
    data = json.loads(body)
    text = json.dumps(data)
    path = re.search(r'"SecurePath":\s*"([^"]+)"', text)
    base = re.search(r'"ServiceUrl":\s*"([^"]+)"', text)
    if not path or not base:
        raise RuntimeError("API yanitinda link yok")
    url = base.group(1).rstrip("/") + "/" + path.group(1)
    status, m3u = get(url)
    if status != 200 or "#EXTM3U" not in m3u:
        raise RuntimeError(f"Link acilmadi (HTTP {status})")
    return url


def main():
    try:
        url = fresh_url()
    except Exception as e:  # liste oldugu gibi kalir
        print("CNN Turk linki alinamadi, liste degismedi:", e)
        return 0
    with open(PLAYLIST, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, i = [], 0
    while i < len(lines):  # eski otomatik kayitlari sil
        if lines[i].startswith("#EXTINF") and lines[i].endswith("," + NAME):
            i += 2
            continue
        out.append(lines[i])
        i += 1
    result, added = [], 0
    for j, line in enumerate(out):
        result.append(line)
        # her CNN Turk kaydinin ustune (ayni grupta) otomatik kaydi ekle
        if line.startswith("#EXTINF") and 'tvg-id="CNNTurk.tr"' in line and j + 1 < len(out):
            result.insert(len(result) - 1, line.rsplit(",", 1)[0] + "," + NAME)
            result.insert(len(result) - 1, url)
            added += 1
    with open(PLAYLIST, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(result) + "\n")
    print(f"CNN Turk linki yenilendi ({added} yerde)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
