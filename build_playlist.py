"""Aile icin ucretsiz Turk + Alman kanallari M3U listesi olusturur.

Kaynak: iptv-org (https://github.com/iptv-org/iptv) - herkese acik, ucretsiz yayinlar.
- Mustehcen (NSFW / xxx) kanallar ve teleshopping cikarilir.
- Her kanal icin linkler test edilir; calisan en yuksek kaliteli link secilir.
- Calismayan kanallar listeye girmez.

Kullanim:  python build_playlist.py            -> playlist.m3u
"""
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://iptv-org.github.io/api/"
COUNTRIES = {"TR", "DE"}
BLOCKED_CATEGORIES = {"xxx", "shop"}
FAVORITES = ["TRT1.tr", "CNNTurk.tr", "TVNET.tr"]  # en cok izlenenler, en ustte
# Dizi, film ve yarisma kanallari: ayrica kendi grubunda da gosterilir.
# Su an calisan yayini olmayanlar (Show, NOW, Beyaz, Teve2) bulunursa kendiliginden eklenir.
DIZI_FILM = [
    "TRT1.tr", "ATV.tr", "KanalD.tr", "StarTV.tr", "TV8.tr", "Kanal7.tr", "ShowTV.tr", "NOWTV.tr", "FOXTV.tr",
    "BeyazTV.tr", "Teve2.tr", "TV360.tr", "KanalDDrama.tr", "EuroD.tr", "EuroStar.tr", "Kanal7Avrupa.tr",
    "ATVAvrupa.tr", "ShowTurk.tr", "ShowMax.tr", "GrandCinema.tr", "TRT2.tr", "TGRTBelgesel.tr",
]
DIZI_GROUP = "TR · Dizi / Film / Yarisma"
DEFAULT_UA = "Mozilla/5.0 (Linux; Android 12; Google TV) AppleWebKit/537.36 Chrome/120 Safari/537.36"
TIMEOUT = 10
# GitHub sunuculari ABD'de: orada 403 (bolge kisitlamasi) veren link evde calisabilir.
# GEO_TOLERANT=1 iken, baska calisan linki olmayan kanallarda 403 veren link de tutulur.
GEO_TOLERANT = os.environ.get("GEO_TOLERANT") == "1"

# iptv-org'da olmayan / ek resmi yayinlar
EXTRA_STREAMS = [
    {"channel": "TVNET.tr", "url": "https://tvnet-live.lg.mncdn.com/tvnet-live/tvnet/playlist.m3u8", "quality": "1080p"},
]

# Aile filtresi: isimde bunlar gecen kanallar listeye girmez (cocuklar icin)
BLOCKED_NAMES = re.compile(
    r"adult|erotic|erotik|sexy|\bsex|xxx|18\+|playboy|hustler|redlight|\bvenus\b|"
    r"south park|comedy central|horror|grusel|thriller|crime|krimi|"
    r"poker|casino|lotto|\bbet\b|wett|\bastro|esoteri|teleshop|\bshop|qvc|\bhse\b|1-2-3|"
    r"horreur|gore|slasher|zombie|psycho|\b666\b|dating|passione|letali|shore|incinta|embarazada|"
    r"l word|big brother|criminal|mystery|conspiracy|investigation|alien|sonnenklar",
    re.I,
)

# Almanya listesinde yer alan ama Italyanca/Ispanyolca/Fransizca olan kanallar (gereksiz kalabalik)
# Ucretli (abonelikli) kanallar ve Turkce/Almanca olmayan yayinlar: hic eklenmez.
PAID_OR_FOREIGN = re.compile(
    r"^(Sky |Sky$|Nicktoons|Nick Jr|GEM |GEM$|Curiosity NOW|Ost West|Disney|beIN|S Sport|Tivibu|Digiturk|"
    r"Exxen|BluTV|DAZN|MagentaMusik)", re.I)

FOREIGN_NAMES = re.compile(
    r"de Pluto|by Pluto|x Pluto|Pluto TV (Alberto|Animales|Animaux|Aventure|Catastrofes|Christmas tutto|Cine |"
    r"Cinema |Cocina|Comedia|Comedie|Cucina|Cuisine|Diseno|Documentari|Film |French|Gasolina|Histoire|Historia|"
    r"Impacto|Natura|Polar|Scherzi|Serie Sci|Series |Storia|Telenovelas|Telerealite|Toto|Viaggi|Bud)|"
    r"Cin Cin|Il Testimone|Tout le monde|Bob Esponja|Verguenza|Sophia TV (Espanol|Francais)|"
    r"^Pluto TV (Cine|Comedies Cultes)",
    re.I,
)

DE_PUBLIC = re.compile(
    r"^(Das Erste|ARD|ZDF|3sat|arte|ARTE|phoenix|KiKA|ONE|tagesschau|BR |BR$|WDR|NDR|SWR|MDR|hr|HR|rbb|RBB|SR |ARD-alpha|Radio Bremen|Deutsche Welle|DW)"
)


def fetch_json(name):
    with urllib.request.urlopen(API + name, timeout=60) as r:
        return json.load(r)


def quality_rank(q):
    m = re.match(r"(\d+)", q or "")
    return int(m.group(1)) if m else 0


def group_for(ch):
    cats = set(ch.get("categories") or [])
    name = ch["name"]
    if ch["country"] == "TR":
        if name.upper().startswith("TRT") or "TRT" in (ch.get("owners") or []) or ch.get("network") == "TRT":
            return "TR · TRT"
        if cats & {"kids", "animation"}:
            return "TR · Cocuk"
        if "news" in cats or "business" in cats:
            return "TR · Haber"
        if cats & {"general", "entertainment", "series", "movies", "comedy"} or not cats:
            return "TR · Ulusal / Eglence"
        if "sports" in cats:
            return "TR · Spor"
        return "TR · Diger"
    # Almanya
    if cats & {"kids", "animation"}:
        return "DE · Kinder"
    if DE_PUBLIC.match(name):
        return "DE · ARD / ZDF / Offentlich"
    if "news" in cats or "business" in cats:
        return "DE · Nachrichten"
    if "sports" in cats:
        return "DE · Sport"
    return "DE · Sonstige"


GROUP_ORDER = [
    "★ Favoriler", DIZI_GROUP, "TR · TRT", "TR · Haber", "TR · Cocuk", "TR · Ulusal / Eglence", "TR · Spor", "TR · Diger",
    "DE · ARD / ZDF / Offentlich", "DE · Nachrichten", "DE · Kinder", "DE · Sport", "DE · Sonstige",
]


def check(stream):
    """2 = calisiyor, 1 = bolge kisitlamasi olabilir (403/451), 0 = calismiyor."""
    headers = {"User-Agent": stream.get("user_agent") or DEFAULT_UA}
    if stream.get("referrer"):
        headers["Referer"] = stream["referrer"]
    try:
        req = urllib.request.Request(stream["url"], headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if r.status != 200:
                return 0
            head = r.read(4096)
            ctype = r.headers.get("Content-Type", "")
            ok = b"#EXTM3U" in head or "video" in ctype or "mpegurl" in ctype.lower() or head[:1] == b"G"
            return 2 if ok else 0
    except urllib.error.HTTPError as e:
        return 1 if GEO_TOLERANT and e.code in (403, 451) else 0
    except Exception:
        return 0


def main(out_path="playlist.m3u"):
    print("Veri indiriliyor...")
    channels = {c["id"]: c for c in fetch_json("channels.json")}
    streams = fetch_json("streams.json")
    logos = {}
    try:
        for l in fetch_json("logos.json"):
            logos.setdefault(l["channel"], l["url"])
    except Exception:
        pass

    wanted = {
        cid: c for cid, c in channels.items()
        if c.get("country") in COUNTRIES
        and not c.get("is_nsfw")
        and not c.get("closed")
        and not (set(c.get("categories") or []) & BLOCKED_CATEGORIES)
        and not BLOCKED_NAMES.search(c["name"])
        and not FOREIGN_NAMES.search(c["name"])
        and not PAID_OR_FOREIGN.search(c["name"])
    }
    candidates = [s for s in streams + EXTRA_STREAMS if s.get("channel") in wanted]
    print(f"{len(wanted)} kanal, {len(candidates)} link test ediliyor...")

    with ThreadPoolExecutor(max_workers=40) as ex:
        results = list(ex.map(check, candidates))

    best, score = {}, {}
    for s, ok in zip(candidates, results):
        if not ok:
            continue
        cid = s["channel"]
        key = (ok, quality_rank(s.get("quality")))
        if cid not in best or key > score[cid]:
            best[cid], score[cid] = s, key

    entries = []
    for cid, s in best.items():
        ch = wanted[cid]
        groups = [group_for(ch)]
        if cid in FAVORITES:
            groups.insert(0, "★ Favoriler")
        if cid in DIZI_FILM or (ch["country"] == "TR" and set(ch.get("categories") or []) & {"series", "movies"}):
            groups.append(DIZI_GROUP)
        if group_for(ch) == "TR · TRT" and set(ch.get("categories") or []) & {"kids", "animation"}:
            groups.append("TR · Cocuk")
        for g in groups:
            entries.append((g, ch, s))

    def sort_key(e):
        g, ch, _ = e
        fav = FAVORITES.index(ch["id"]) if g == "★ Favoriler" and ch["id"] in FAVORITES else 0
        if g == DIZI_GROUP:
            fav = DIZI_FILM.index(ch["id"]) if ch["id"] in DIZI_FILM else len(DIZI_FILM)
        return (GROUP_ORDER.index(g), fav, ch["name"].lower())

    entries.sort(key=sort_key)

    lines = ['#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/tr.xml,https://iptv-org.github.io/epg/guides/de.xml"']
    for g, ch, s in entries:
        q = f" ({s['quality']})" if s.get("quality") else ""
        logo = logos.get(ch["id"], "")
        lines.append(f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-logo="{logo}" group-title="{g}",{ch["name"]}{q}')
        if s.get("referrer"):
            lines.append(f"#EXTVLCOPT:http-referrer={s['referrer']}")
        if s.get("user_agent"):
            lines.append(f"#EXTVLCOPT:http-user-agent={s['user_agent']}")
        lines.append(s["url"])

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    from collections import Counter
    counts = Counter(g for g, _, _ in entries)
    geo = sum(1 for k in score.values() if k[0] == 1)
    extra = f"  (bolge kisitli olabilir: {geo})" if geo else ""
    print(f"\nCalisan kanal: {len(best)} / {len(wanted)}  ->  {out_path}{extra}")
    for g in GROUP_ORDER:
        if counts[g]:
            print(f"  {g}: {counts[g]}".encode("ascii", "replace").decode())
    missing = [f for f in FAVORITES if f not in best]
    if missing:
        print("UYARI - calismayan favoriler:", ", ".join(missing))


if __name__ == "__main__":
    main(*sys.argv[1:])
