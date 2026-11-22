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
import urllib.parse
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
    "ATVAvrupa.tr", "ShowTurk.tr", "ShowMax.tr", "GrandCinema.tr", "TRT2.tr", "TGRTBelgesel.tr", "TV4.tr",
    "360.tr", "Tivi6.tr", "TV41.tr", "Kanal15.tr", "ASTV.tr", "Kanal26.tr", "ESTV.tr", "LiderHaber.tr",
]
DIZI_GROUP = "TR · Dizi / Film / Yarisma"
# Her grup tek dilli: Turkce kanallar "TR ·", Almanca kanallar "DE ·" gruplarinda.
# Belgesel ve spor kanallari ayrica kendi dilinin belgesel / spor grubunda da gosterilir.
TR_BELGESEL, DE_DOKU = "TR · Belgesel", "DE · Doku"
TR_SPOR, DE_SPORT = "TR · Spor", "DE · Sport"
EN_GROUP = "EN · News"
EN_ALSO = {"TRTWorld.tr"}  # TRT'de de durur, ayrica Ingilizce haber grubunda
SPOR_NAME = re.compile(r"Spor|Sport|TJK|Motor", re.I)
BELGESEL = ["TRTBelgesel.tr", "TGRTBelgesel.tr", "CiftciTV.tr", "ARDalpha.de", "phoenix.de", "arte.de", "CuriosityChannel.de"]
DEFAULT_UA = "Mozilla/5.0 (Linux; Android 12; Google TV) AppleWebKit/537.36 Chrome/120 Safari/537.36"
TIMEOUT = 10
# GitHub sunuculari ABD'de: orada 403 (bolge kisitlamasi) veren link evde calisabilir.
# GEO_TOLERANT=1 iken, baska calisan linki olmayan kanallarda 403 veren link de tutulur.
GEO_TOLERANT = os.environ.get("GEO_TOLERANT") == "1"
# Listeye hic alinmayacak link parcalari (su an bos).
# TRT Belgesel/Cocuk/Spor ve CNN Turk 720p yurt disinda 403 verir; evde NordVPN (Turkiye) ile acilir,
# bu yuzden asagida EXTRA_STREAMS'e "extra" olarak eklendi.
BLOCKED_URL_PATTERNS = []


def is_blocked(url):
    return any(p in url for p in BLOCKED_URL_PATTERNS)

# iptv-org'da olmayan / ek resmi yayinlar
EXTRA_STREAMS = [
    {"channel": "TVNET.tr", "url": "https://tvnet-live.lg.mncdn.com/tvnet-live/tvnet/playlist.m3u8", "quality": "1080p"},
    {"channel": "EuronewsGerman.fr", "url": "https://cdn-euronews.akamaized.net/live/eds/euronews-de/25027/index.m3u8", "quality": "720p"},
    {"channel": "EuronewsEnglish.fr", "url": "https://cdn-euronews.akamaized.net/live/eds/euronews-en/25002/index.m3u8", "quality": "720p"},
    # "extra": her zaman ek secenek olarak eklenir (ABD'den 403 verse de Turkiye/Almanya'dan calisabilir)
    {"channel": "NTV.tr", "url": "https://dogus.daioncdn.net/ntv/ntv.m3u8?app=ntv_web", "quality": "", "extra": True},
    # Resmi TRT / CNN Turk yayinlari: sadece Turkiye IP'si ile acilir (NordVPN -> Turkiye)
    {"channel": "TRTBelgesel.tr", "url": "https://tv-trtbelgesel.medya.trt.com.tr/master.m3u8", "quality": "720p", "extra": True},
    {"channel": "TRTCocuk.tr", "url": "https://tv-trtcocuk.medya.trt.com.tr/master.m3u8", "quality": "1080p", "extra": True},
    {"channel": "TRTSpor.tr", "url": "https://trt.daioncdn.net/trtspor/master.m3u8?app=web&platform=trtspor", "quality": "720p", "extra": True},
    {"channel": "TRTSporYildiz.tr", "url": "https://trt.daioncdn.net/trtspor-yildiz/master.m3u8?app=web&platform=trtspor", "quality": "1080p", "extra": True},
]

# iptv-org'da ulke disi (FR) olan veya hic olmayan kanallar: grup elle verilir
RADYO_GROUP = "Radyo · TRT"
_TRT_RADIO = [
    ("trtfm", "TRT FM"), ("trtradyo1", "TRT Radyo 1"), ("trtradyo3", "TRT Radyo 3"), ("trtturku", "TRT Türkü"),
    ("trtnagme", "TRT Nağme"), ("trtradyohaber", "TRT Radyo Haber"), ("trtradyo6", "TRT Radyo 6"),
    ("trtantalya", "TRT Antalya"), ("trtcukurova", "TRT Çukurova"), ("trterzurum", "TRT Erzurum"),
    ("trtgap", "TRT GAP"), ("trttrabzon", "TRT Trabzon"), ("trtmemleketimfm", "TRT Memleketim FM"),
]
EXTRA_CHANNELS = {
    "EuronewsGerman.fr": {"group": "DE · Nachrichten"},
    "EuronewsEnglish.fr": {"group": EN_GROUP},
}
# iptv-org'da haber kategorisi eksik olan haber kanallari
NEWS_OVERRIDE = {
    "NTV.tr": "TR · Haber", "SozcuTV.tr": "TR · Haber", "Tele1.tr": "TR · Haber", "TVNET.tr": "TR · Haber",
    "ntv.de": "DE · Nachrichten",
}
# propaganda / yabanci dilli haber kanallari
EXCLUDE_IDS = {"RTDE.ru", "RTDE.de", "MekameleenTV.tr", "AlmahriahTV.tr"}
for _rid, _name in _TRT_RADIO:
    _cid = f"{_rid}.radio.tr"
    EXTRA_CHANNELS[_cid] = {"id": _cid, "name": _name, "country": "TR", "categories": ["music"], "group": RADYO_GROUP}
    EXTRA_STREAMS.append({"channel": _cid, "url": f"https://radio-{_rid}.live.trt.com.tr/master.m3u8", "quality": ""})

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
    r"Exxen|BluTV|DAZN(?!.*(Pluto|FAST))|Magenta|Eurosport|Sportdigital|Sport1\+|Motorvision\+|FC Bayern|Al-Zahra|Al Zahra|Thaqalayn)", re.I)

FOREIGN_NAMES = re.compile(
    r"de Pluto|by Pluto|^(?!DAZN).*x Pluto|Pluto TV (Alberto|Animales|Animaux|Aventure|Catastrofes|Christmas tutto|Cine |"
    r"Cinema |Cocina|Comedia|Comedie|Cucina|Cuisine|Diseno|Documentari|Film |French|Gasolina|Histoire|Historia|"
    r"Impacto|Natura|Polar|Scherzi|Serie Sci|Series |Storia|Telenovelas|Telerealite|Toto|Viaggi|Bud)|"
    r"Cin Cin|Il Testimone|Tout le monde|Bob Esponja|Verguenza|Sophia TV (Espanol|Francais)|"
    r"^Pluto TV (Cine|Comedies Cultes)",
    re.I,
)

# Turkce/Almanca olmayan diller: bu dillerde yayin yapan kanallar listeye girmez
FOREIGN_LANGS = {"rus", "kur", "ara", "fas", "zza", "kmr", "ckb"}
DE_RELIGION = re.compile(r"Bibel|EWTN|Sophia|Light Channel|Neu Jerusalem|EchtJetzt|K-TV|Hope Channel", re.I)
DE_REGIONAL = re.compile(
    r"^(OK |OK-|Offener Kanal|Regio|Sachsen|Niederbayern|Oberpfalz|Allg|Altenburg|Augsburg|Erz|Filstal|Franken|MDF|"
    r"M[uü]nchen|RFH|Saarland|TV ?38|TVA|TV Ingolstadt|TV Mainfranken|TV Oberfranken|noa4|telt|Alex|PUNKTum|RBW|"
    r"Seenluft|labor14|NRWision|iSTUFF|KulturMD|RiC|Unserding|RAN1|L-TV|Hamburg|Rhein|Berlin)", re.I)

DE_PUBLIC = re.compile(
    r"^(Das Erste|ARD|ZDF|3sat|arte|ARTE|phoenix|KiKA|ONE|tagesschau|BR |BR$|WDR|NDR|SWR|MDR|hr|HR|rbb|RBB|SR |ARD-alpha|Radio Bremen|Deutsche Welle|DW)"
)


def fetch_json(name):
    with urllib.request.urlopen(API + name, timeout=60) as r:
        return json.load(r)


def quality_rank(q):
    m = re.match(r"(\d+)", q or "")
    return int(m.group(1)) if m else 0


TR_DINI = re.compile(r"^(Diyanet|Lalegul|Lalegül|Semerkand|Vav TV|Dost TV|Ulke TV|Ülke TV|Hilal|Mesaj TV|Rehber TV|Berat TV)", re.I)


def is_sport(ch):
    return bool(set(ch.get("categories") or []) & {"sports", "auto"}) or bool(SPOR_NAME.search(ch["name"]))


def is_trt(ch):
    return ch["name"].upper().startswith("TRT") or "TRT" in (ch.get("owners") or []) or ch.get("network") == "TRT"


def side_of(ch):
    """Kanalin dil tarafi: 'TR' (Turkce) veya 'DE' (Almanca)."""
    return ch.get("side") or ch.get("country")


def group_for(ch):
    if ch.get("group"):
        return ch["group"]
    cats = set(ch.get("categories") or [])
    name = ch["name"]
    if side_of(ch) == "TR":
        if is_trt(ch):
            return "TR · TRT"
        if is_sport(ch):
            return TR_SPOR
        if cats & {"kids", "animation"}:
            return "TR · Cocuk"
        if "religious" in cats or TR_DINI.search(name):
            return "TR · Dini"
        if cats & {"news", "business", "legislative", "weather"}:
            return "TR · Haber"
        if "documentary" in cats or ch["id"] in BELGESEL:
            return TR_BELGESEL
        if "music" in cats:
            return "TR · Muzik"
        if cats & {"general", "entertainment", "series", "movies", "comedy", "classic"} or not cats:
            return "TR · Ulusal / Eglence"
        return "TR · Kultur / Yasam"
    # Almanca
    if cats & {"kids", "animation"}:
        return "DE · Kinder"
    if DE_PUBLIC.match(name):
        return "DE · ARD / ZDF / Offentlich"
    if cats & {"news", "business", "legislative", "weather"}:
        return "DE · Nachrichten"
    if is_sport(ch):
        return DE_SPORT
    if "documentary" in cats or ch["id"] in BELGESEL:
        return DE_DOKU
    if "music" in cats:
        return "DE · Musik"
    if "religious" in cats or DE_RELIGION.search(name):
        return "DE · Religion"
    if DE_REGIONAL.search(name) or "general" in cats:
        return "DE · Regional"
    if cats & {"movies", "series", "comedy", "classic"}:
        return "DE · Filme / Serien"
    if cats & {"entertainment", "lifestyle", "culture", "education", "family", "travel", "cooking", "outdoor"} or not cats:
        return "DE · Unterhaltung"
    return "DE · Sonstige"


_TR_GROUPS = ["TR · TRT", "TR · Haber", "TR · Cocuk", DIZI_GROUP, "TR · Ulusal / Eglence", TR_SPOR, TR_BELGESEL,
              "TR · Muzik", "TR · Dini", "TR · Kultur / Yasam"]
_DE_GROUPS = ["DE · ARD / ZDF / Offentlich", "DE · Nachrichten", "DE · Kinder", "DE · Filme / Serien",
              "DE · Unterhaltung", DE_DOKU, DE_SPORT, "DE · Musik", "DE · Religion", "DE · Regional", "DE · Sonstige"]
# Favoriler en ustte; sonra Turkce gruplar kendi icinde, Almanca gruplar kendi icinde alfabetik
GROUP_ORDER = (["★ Favoriler"] + sorted(_TR_GROUPS, key=str.casefold) + sorted(_DE_GROUPS, key=str.casefold)
               + [EN_GROUP, RADYO_GROUP])


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


def fetch_text(stream):
    headers = {"User-Agent": stream.get("user_agent") or DEFAULT_UA}
    if stream.get("referrer"):
        headers["Referer"] = stream["referrer"]
    req = urllib.request.Request(stream["url"], headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.geturl(), r.read(65536).decode("utf-8", "replace")


def variants(stream):
    """Ana (master) listedeki kalite secenekleri: [(yukseklik, url)]. Ses ayri ise bos doner."""
    try:
        base, text = fetch_text(stream)
    except Exception:
        return []
    if "#EXT-X-STREAM-INF" not in text or "TYPE=AUDIO" in text:
        return []
    out, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        uri = next((l.strip() for l in lines[i + 1:] if l.strip() and not l.startswith("#")), None)
        if not uri:
            continue
        m = re.search(r"RESOLUTION=\d+x(\d+)", line)
        h = int(m.group(1)) if m else 0
        if not h:
            m = re.search(r"(\d{3,4})p", uri)
            h = int(m.group(1)) if m else 0
        if h:
            out.append((h, urllib.parse.urljoin(base, uri)))
    return out


def fallback_for(best_s, alts):
    """Iyi kalite secilen kanal icin 720p (veya daha dusuk) yedek yayin bulur."""
    v = variants(best_s)
    if v and max(h for h, _ in v) > 720:
        # sid= iceren linkler oturuma bagli, kisa surede gecersiz olur
        low = [x for x in v if x[0] <= 720 and "sid=" not in x[1]]
        if low:
            h, url = max(low)
            fb = dict(best_s, url=url, quality=f"{h}p")
            if check(fb) == 2:
                # ana link uyarlamali (master): en yuksek kalitesiyle etiketle
                best_s["quality"] = f"{max(h for h, _ in v)}p"
                return fb
    # iptv-org'daki baska bir 720p ve alti link
    low = [s for s in alts if s["url"] != best_s["url"] and 0 < quality_rank(s.get("quality")) <= 720]
    if low and quality_rank(best_s.get("quality")) > 720:
        return max(low, key=lambda s: quality_rank(s.get("quality")))
    return None


def main(out_path="playlist.m3u"):
    print("Veri indiriliyor...")
    channels = {c["id"]: c for c in fetch_json("channels.json")}
    for cid, extra in EXTRA_CHANNELS.items():
        channels[cid] = dict(channels.get(cid) or {}, **extra)
    for cid, grp in NEWS_OVERRIDE.items():
        if cid in channels:
            channels[cid] = dict(channels[cid], group=grp)
    for cid in EXCLUDE_IDS:
        channels.pop(cid, None)
    # Dil bilgisi (feeds.json): Almanya'dan Turkce yayin yapanlar TR tarafina,
    # Turkce/Almanca olmayan dillerde yayin yapanlar listeden cikar.
    langs = {}
    try:
        for f in fetch_json("feeds.json"):
            langs.setdefault(f.get("channel"), set()).update(f.get("languages") or [])
    except Exception:
        pass
    for cid in list(channels):
        c = channels[cid]
        if c.get("country") not in COUNTRIES or cid in EXTRA_CHANNELS or c["name"].startswith("Pluto"):
            continue
        L = langs.get(cid, set())
        if L and not L & {"tur", "deu"} and L & FOREIGN_LANGS and not is_trt(c):
            channels.pop(cid)
            continue
        side = "TR" if "tur" in L else ("DE" if "deu" in L else c["country"])
        channels[cid] = dict(c, side=side)
    streams = fetch_json("streams.json")
    logos = {}
    try:
        for l in fetch_json("logos.json"):
            logos.setdefault(l["channel"], l["url"])
    except Exception:
        pass

    wanted = {
        cid: c for cid, c in channels.items()
        if (c.get("country") in COUNTRIES or cid in EXTRA_CHANNELS)
        and not c.get("is_nsfw")
        and not c.get("closed")
        and not (set(c.get("categories") or []) & BLOCKED_CATEGORIES)
        and not BLOCKED_NAMES.search(c["name"])
        and not FOREIGN_NAMES.search(c["name"])
        and not PAID_OR_FOREIGN.search(c["name"])
    }
    candidates = [s for s in streams + EXTRA_STREAMS if s.get("channel") in wanted and not is_blocked(s["url"])]
    print(f"{len(wanted)} kanal, {len(candidates)} link test ediliyor...")

    with ThreadPoolExecutor(max_workers=40) as ex:
        results = list(ex.map(check, candidates))

    best, score, working, forced = {}, {}, {}, {}
    for s, ok in zip(candidates, results):
        if s.get("extra"):
            # ABD sunucusundan acilmasa bile her zaman tutulur (evde VPN/Turkiye IP ile acilir)
            forced.setdefault(s["channel"], []).append(s)
            continue
        if not ok:
            continue
        cid = s["channel"]
        if ok == 2:
            working.setdefault(cid, []).append(s)
        key = (ok, quality_rank(s.get("quality")))
        if cid not in best or key > score[cid]:
            best[cid], score[cid] = s, key

    print("Yedek (720p) secenekler araniyor...")
    cids = list(best)
    with ThreadPoolExecutor(max_workers=40) as ex:
        fbs = dict(zip(cids, ex.map(lambda c: fallback_for(best[c], working.get(c, [])), cids)))

    def _entries_for(cid, s):
        ch = wanted[cid]
        groups = [group_for(ch)]
        if cid in FAVORITES:
            groups.insert(0, "★ Favoriler")
        tr = side_of(ch) == "TR"
        if tr and (cid in DIZI_FILM or set(ch.get("categories") or []) & {"series", "movies"}):
            groups.append(DIZI_GROUP)
        if side_of(ch) in COUNTRIES and (cid in BELGESEL or "documentary" in (ch.get("categories") or [])):
            g = TR_BELGESEL if tr else DE_DOKU
            if g not in groups:
                groups.append(g)
        if side_of(ch) in COUNTRIES and is_sport(ch):
            g = TR_SPOR if tr else DE_SPORT
            if g not in groups:
                groups.append(g)
        if cid in EN_ALSO:
            groups.append(EN_GROUP)
        if group_for(ch) == "TR · TRT" and set(ch.get("categories") or []) & {"kids", "animation"}:
            groups.append("TR · Cocuk")
        return [(g, ch, s) for g in groups]

    # Sadece "extra" linki olan kanallar (orn. TRT Belgesel ABD'den hic acilmazsa) yine de listeye girer
    for cid, xs in forced.items():
        best.setdefault(cid, xs[0])

    entries = []
    for cid, main_s in best.items():
        streams_for = [main_s] + ([fbs[cid]] if fbs.get(cid) else [])
        seen = {x["url"] for x in streams_for}
        streams_for += [x for x in forced.get(cid, []) if x["url"] not in seen]
        for s in streams_for:
            entries.extend(_entries_for(cid, s))

    # Ayni grupta birebir ayni olanlari sil: ayni kanal + ayni kalite ya da ayni URL
    uniq, seen_q, seen_u = [], set(), set()
    for g, ch, s in entries:
        kq, ku = (g, ch["id"], s.get("quality") or ""), (g, s["url"])
        if kq in seen_q or ku in seen_u:
            continue
        seen_q.add(kq)
        seen_u.add(ku)
        uniq.append((g, ch, s))
    entries = uniq

    def sort_key(e):
        # Grup sirasi, sonra kanal adina gore alfabetik, ayni kanalda yuksek kalite once
        g, ch, s = e
        return (GROUP_ORDER.index(g), ch["name"].casefold(), ch["id"], -quality_rank(s.get("quality")))

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
