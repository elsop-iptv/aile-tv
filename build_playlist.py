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
BELGESEL = ["TRTBelgesel.tr", "TGRTBelgesel.tr", "CiftciTV.tr", "ARDalpha.de", "phoenix.de", "arte.de", "ZDFinfo.de",
            "GZT.tr", "AgroTV.tr"]
# ARD/ZDF grubunda durur, ayrica Almanca haber grubunda da gosterilir
DE_NEWS_ALSO = {"phoenix.de", "tagesschau24.de"}
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
    {"channel": "LifeTV.tr", "url": "https://live.artidijitalmedya.com/artidijital_lifetv/lifetv/playlist.m3u8", "quality": "720p"},
    {"channel": "EuronewsGerman.fr", "url": "https://cdn-euronews.akamaized.net/live/eds/euronews-de/25027/index.m3u8", "quality": "720p"},
    {"channel": "EuronewsEnglish.fr", "url": "https://cdn-euronews.akamaized.net/live/eds/euronews-en/25002/index.m3u8", "quality": "720p"},
    # "extra": her zaman ek secenek olarak eklenir (ABD'den 403 verse de Turkiye/Almanya'dan calisabilir)
    {"channel": "NTV.tr", "url": "https://dogus.daioncdn.net/ntv/ntv.m3u8?app=ntv_web", "quality": "", "extra": True},
    # Resmi TRT / CNN Turk yayinlari: sadece Turkiye IP'si ile acilir (NordVPN -> Turkiye)
    {"channel": "TRTBelgesel.tr", "url": "https://tv-trtbelgesel.medya.trt.com.tr/master.m3u8", "quality": "720p", "extra": True},
    {"channel": "TRTCocuk.tr", "url": "https://tv-trtcocuk.medya.trt.com.tr/master.m3u8", "quality": "1080p", "extra": True},
    {"channel": "TRTSpor.tr", "url": "https://trt.daioncdn.net/trtspor/master.m3u8?app=web&platform=trtspor", "quality": "720p", "extra": True},
    {"channel": "TRTSporYildiz.tr", "url": "https://trt.daioncdn.net/trtspor-yildiz/master.m3u8?app=web&platform=trtspor", "quality": "1080p", "extra": True},
    # DW: Almanca DW TV 2023'te, DW Deutsch+ 2024'te kapandi; DW Turkce sadece YouTube (M3U oynatamaz) -> resmi DW English
    {"channel": "DWEnglish.de", "url": "https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/master.m3u8", "quality": "1080p"},
    # Almanca kamu / bilgi kanallari (Isvicre, Bundestag). ORF 2 / ORF III: Avusturya disinda bolge kisitli -> cikarildi
    {"channel": "SRFinfo.ch", "url": "https://r.eu.cdn-redge.media/livehls/oeu/mt/live/srf_info/live.livx/playlist.m3u8", "quality": "720p"},
    {"channel": "Parlamentsfernsehen2.de", "url": "https://cldf-hlsgw.r53.cdn.tv1.eu/1000153copo/hk2.m3u8", "quality": "1080p"},
    {"channel": "Parlamentsfernsehen3.de", "url": "https://cldf-hlsgw.r53.cdn.tv1.eu/1000153copo/hk3.m3u8", "quality": "1080p"},
    {"channel": "Parlamentsfernsehen4.de", "url": "https://cldf-hlsgw.r53.cdn.tv1.eu/1000153copo/hk4.m3u8", "quality": "1080p"},
    # ORF Kids: iptv-org'da sadece .mpd var
    {"channel": "ORFKids.at", "url": "https://web12.mdn.ors.at/orf/web12/qxa/manifest.m3u8", "quality": "720p"},
    # Almanya'dan Turkce yayin yapan kanallar (gurbetci TV / radyo)
    {"channel": "KanalAvrupa.de", "url": "https://cdn-kanalavrupa.yayin.com.tr/kanalavrupa/index.m3u8", "quality": "1080p"},
    {"channel": "YOLTV.de", "url": "https://live.yoltv.com/hls/stream.m3u8", "quality": "720p"},
    {"channel": "MetropolFM.radio.de", "url": "https://stream.metropolfm.de/metropolfm/mp3-128", "quality": ""},
]

# Almanca Pluto TV kanallari (iptv-org'da kanal eslesmesi yok / yanlis ulke-dil): (id, ad, kategori, grup, pluto id)
DE_KINDER = "DE · Kinder"
_DE_PLUTO = [
    ("TotallyTurtles.de", "Totally Turtles", "kids", DE_KINDER, "5d6792bd6be2998ad0ccce30"),
    ("iCarly.de", "iCarly", "kids", DE_KINDER, "5e8b580a233dc90007f0cb9d"),
    ("NickelodeonToons.de", "Nickelodeon Toons", "kids", DE_KINDER, "5ede448d3d50590007a4419e"),
    ("NickelodeonTeen.de", "Nickelodeon Teen", "kids", DE_KINDER, "5f0d668b872e4400073acc68"),
    ("Zoey101.de", "Zoey 101", "kids", DE_KINDER, "63c69e6c4207be0007f73c22"),
    ("DieThundermans.de", "Die Thundermans", "kids", DE_KINDER, "6447df8cd3fdde0008f1f627"),
    ("PlutoTVHistory.de", "Pluto TV History", "documentary", DE_DOKU, "5d767b1c126c65d0a307355f"),
    ("PlutoTVScience.de", "Pluto TV Science", "documentary", DE_DOKU, "5d767b4889bca2ce7b73ef2e"),
    ("BBCEarth.de", "BBC Earth", "documentary", DE_DOKU, "6a9a89f6ff94431f8bb895d4"),
    ("SpiegelTV.de", "SPIEGEL TV", "documentary", DE_DOKU, "6576c20fb3801200084786c9"),
    ("FlussMonster.de", "Fluss-Monster", "documentary", DE_DOKU, "62a0b2aff4cf470007e47e29"),
    ("FarmlandTV.de", "Farmland TV", "documentary", DE_DOKU, "663a15d7cb3ea10008edac88"),
    ("SpaceLive.de", "Space Live", "documentary", DE_DOKU, "69a554497ed3b3fff0b9ca80"),
    ("PlutoTVSport.de", "Pluto TV Sport", "sports", DE_SPORT, "608030eff4b6f70007e1684c"),
    ("PlutoTVMotor.de", "Pluto TV Motor", "sports", DE_SPORT, "6080345ebb49b90007ce0baf"),
]
for _cid, _name, _cat, _grp, _pid in _DE_PLUTO:
    EXTRA_STREAMS.append({"channel": _cid, "url": f"https://jmp2.uk/plu-{_pid}.m3u8", "quality": ""})

# iptv-org'da ulke disi (FR) olan veya hic olmayan kanallar: grup elle verilir
RADYO_GROUP = "Radyo · TRT"
RADYO_AVRUPA = "Radyo · Avrupa"
_TRT_RADIO = [
    ("trtfm", "TRT FM"), ("trtradyo1", "TRT Radyo 1"), ("trtradyo3", "TRT Radyo 3"), ("trtturku", "TRT Türkü"),
    ("trtnagme", "TRT Nağme"), ("trtradyohaber", "TRT Radyo Haber"), ("trtradyo6", "TRT Radyo 6"),
    ("trtantalya", "TRT Antalya"), ("trtcukurova", "TRT Çukurova"), ("trterzurum", "TRT Erzurum"),
    ("trtgap", "TRT GAP"), ("trttrabzon", "TRT Trabzon"), ("trtmemleketimfm", "TRT Memleketim FM"),
]
EXTRA_CHANNELS = {
    "EuronewsGerman.fr": {"group": "DE · Nachrichten"},
    "EuronewsEnglish.fr": {"group": EN_GROUP},
    "DWEnglish.de": {"id": "DWEnglish.de", "name": "DW English", "country": "DE", "categories": ["news"], "group": EN_GROUP},
    "ORFKids.at": {"id": "ORFKids.at", "name": "ORF Kids", "country": "AT", "side": "DE", "categories": ["kids"], "group": DE_KINDER},
    "SRFinfo.ch": {"id": "SRFinfo.ch", "name": "SRF info", "country": "CH", "side": "DE", "categories": ["news"], "group": "DE · Nachrichten"},
    "Parlamentsfernsehen2.de": {"group": "DE · Nachrichten"},
    "Parlamentsfernsehen3.de": {"group": "DE · Nachrichten"},
    "Parlamentsfernsehen4.de": {"group": "DE · Nachrichten"},
    "KanalAvrupa.de": {"id": "KanalAvrupa.de", "name": "Kanal Avrupa", "country": "DE", "side": "TR", "categories": ["general"], "group": "TR · Ulusal / Eglence"},
    "YOLTV.de": {"id": "YOLTV.de", "name": "YOL TV", "country": "DE", "side": "TR", "categories": ["culture"], "group": "TR · Kultur / Yasam"},
    "MetropolFM.radio.de": {"id": "MetropolFM.radio.de", "name": "Metropol FM (Berlin)", "country": "DE", "side": "TR", "categories": ["music"], "group": RADYO_AVRUPA},
}
for _cid, _name, _cat, _grp, _pid in _DE_PLUTO:
    EXTRA_CHANNELS[_cid] = {"id": _cid, "name": _name, "country": "DE", "side": "DE", "categories": [_cat], "group": _grp}

# Ek kanallar (resmi / ucretsiz yayinlar): (id, ad, url, kalite, ulke, taraf, kategori, grup)
TR_EKONOMI, TR_YEREL = "TR · Ekonomi", "TR · Yerel"
SANAT_GROUP = "Sanat / Arts"
INT_SPORT = "Sport (International)"
_TB = "https://edge1.taksimbilisim.com/{}/bant1/playlist.m3u8"
_NEW_CHANNELS = [
    # TRT / tabii
    ("TabiiTV.tr", "tabii TV", "https://ceokzokgtd.erbvr.com/tabiitv/tabiitv.m3u8", "1080p", "TR", "TR", "general", "TR · TRT"),
    ("TRTWorld.tr", "TRT World", "https://tv-trtworld.medya.trt.com.tr/master.m3u8", "", "TR", "TR", "news", "TR · TRT"),
    ("TRTKurdi.tr", "TRT Kurdî", "https://tv-trtkurdi.medya.trt.com.tr/master.m3u8", "", "TR", "TR", "general", "TR · TRT"),
    # Belgesel
    ("GZT.tr", "GZT", "https://gzttv-live.lg.mncdn.com/gzttv-live/gzttv/playlist.m3u8", "1080p", "TR", "TR", "documentary", TR_BELGESEL),
    ("AgroTV.tr", "Agro TV", "https://agro.fatihdemirsoy.com:8181/memfs/master.m3u8", "1080p", "TR", "TR", "documentary", TR_BELGESEL),
    # Ekonomi / Haber
    ("APara.tr", "A Para", "https://rnttwmjcin.turknet.ercdn.net/lcpmvefbyo/apara/apara.m3u8", "1080p", "TR", "TR", "business", TR_EKONOMI),
    ("TV100.tr", "TV100", "https://tv.ensonhaber.com/tv100/tv100.m3u8", "", "TR", "TR", "news", "TR · Haber"),
    # Yerel (Ordu & Rize once)
    ("AltasTV.tr", "Altaş TV (Ordu)", _TB.format("altastv"), "720p", "TR", "TR", "general", TR_YEREL),
    ("TV52.tr", "TV 52 (Ordu)", _TB.format("tv52"), "720p", "TR", "TR", "general", TR_YEREL),
    ("CayTV.tr", "Çay TV (Rize)", _TB.format("caytv"), "720p", "TR", "TR", "general", TR_YEREL),
    ("ETVManisa.tr", "ETV Manisa", _TB.format("manisaetv"), "1080p", "TR", "TR", "general", TR_YEREL),
    ("IcelTV.tr", "İçel TV", _TB.format("iceltv"), "1080p", "TR", "TR", "general", TR_YEREL),
    ("Kanal32.tr", "Kanal 32", _TB.format("kanal32"), "720p", "TR", "TR", "general", TR_YEREL),
    ("LineTV.tr", "Line TV", _TB.format("linetv"), "720p", "TR", "TR", "general", TR_YEREL),
    ("MTurkTV.tr", "Muğla Türk TV", _TB.format("muglaturk"), "720p", "TR", "TR", "general", TR_YEREL),
    ("GuneydoguTV.tr", "Güneydoğu TV", _TB.format("gtv"), "720p", "TR", "TR", "general", TR_YEREL),
    ("KanalUrfa.tr", "Kanal Urfa", _TB.format("kanalurfa"), "", "TR", "TR", "general", TR_YEREL),
    ("TV1.tr", "TV1", _TB.format("tv1"), "720p", "TR", "TR", "general", TR_YEREL),
    ("NaturalTV.tr", "Natural TV", _TB.format("naturaltv"), "1080p", "TR", "TR", "documentary", TR_BELGESEL),
    # Sanat / Arts
    ("ClassicArtsShowcase.us", "Classic Arts Showcase", "https://classicarts.akamaized.net/hls/live/1024257/CAS/master.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    ("StingrayClassica.us", "Stingray Classica", "https://lotus.stingray.com/manifest/classica-cla008-montreal/samsungtvplus/master.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    ("PeacefulPiano.us", "Peaceful Piano", "https://lotus.stingray.com/manifest/ose-807ads-montreal/samsungtvplus/master.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    ("Qello.us", "Qello Concerts", "https://lotus.stingray.com/manifest/qello-qello001-montreal/samsungtvplus/master.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    ("QwestTVJazz.us", "Qwest TV Jazz", "https://qwestjazz-rakuten.amagi.tv/hls/amagi_hls_data_rakutenAA-qwestjazz-rakuten/CDN/master.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    ("BobRoss.us", "Bob Ross", "https://wurlcineverse.global.transmit.live/hls/678863ef58870f59fceabf94/v1/cinedigm_entertainment_corp_thebobrosschannel_1/vizio_us/latest/main/hls/playlist.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    ("CraftsyTV.us", "Craftsy TV", "https://linear-492.frequency.stream/dist/stirr/492/hls/master/playlist.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    ("5MinuteCraft.us", "5-Minute Crafts", "https://soul-5mincrafteng-rakuten.amagi.tv/playlist.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    ("DIYArt.us", "DIY Art", "https://streams2.sofast.tv/v1/master/611d79b11b77e2f571934fd80ca1413453772ac7/2cafac16-f982-4563-9951-ccd6ab0c2c6b/manifest.m3u8", "", "US", "TR", "culture", SANAT_GROUP),
    # Almanca spor
    ("RedBullTV.de", "Red Bull TV", "https://rbmn-live.akamaized.net/hls/live/590964/BoRB-AT/master.m3u8", "", "DE", "DE", "sports", DE_SPORT),
    ("FIFAPlusDE.de", "FIFA+ (Deutsch)", "https://4397879b.wurl.com/master/f36d25e7e52f1ba8d7e56eb859c636563214f541/UmFrdXRlblRWLWRlX0ZJRkFQbHVzR2VybWFuX0hMUw/playlist.m3u8", "", "DE", "DE", "sports", DE_SPORT),
    ("Motorvision.de", "Motorvision", "https://mvg-mv.otteravision.com/mvg/mv/mv_1080p.m3u8", "1080p", "DE", "DE", "sports", DE_SPORT),
    # Uluslararasi spor (Ingilizce)
    ("FIFAPlusEN.us", "FIFA+ (English)", "https://95cedebd.wurl.com/master/f36d25e7e52f1ba8d7e56eb859c636563214f541/Vml6aW9fRklGQVBsdXNFbmdsaXNoX0hMUw/playlist.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("EurovisionSport.us", "Eurovision Sport", "https://amg26268-amg26268c34-amgplt0018.playout.now3.amagi.tv/ts-us-e2-n1/playlist/amg26268-amg26268c34-amgplt0018/playlist.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("RallyTV.us", "Rally TV", "https://rally-tv-live.akamaized.net/hls/live/2117704/RallyTV-Pri/master.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("PGATour.us", "PGA Tour", "https://d11k1mnrgfposz.cloudfront.net/playlist.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("NHL.us", "NHL Channel", "https://nhl-firetv.amagi.tv/playlist.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("Stadium.us", "Stadium", "https://wurl120sports.global.transmit.live/hls/6865b0ce3b41686108809e5a/v1/stadium_gracenote/vizio_us/latest/main/hls/playlist.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("FuboSports.us", "Fubo Sports", "https://dnf08l6u6uxnz.cloudfront.net/master.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("Overtime.us", "Overtime", "https://d1a8aq6t30gkqj.cloudfront.net/v1/amc_overtime_1/samsungheadend_us/latest/main/hls/playlist_hd.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("MonsterJam.us", "Monster Jam", "https://wurlspacemob.global.transmit.live/hls/6791101f0b2848c81efe74d7/v1/answermedia_monsterjam_1/vizio_us/latest/main/hls/playlist.m3u8", "", "US", "DE", "sports", INT_SPORT),
    ("NHRA.us", "NHRA", "https://d265y4sk8257lt.cloudfront.net/nh.m3u8", "", "US", "DE", "sports", INT_SPORT),
]
for _cid, _name, _url, _q, _country, _side, _cat, _grp in _NEW_CHANNELS:
    EXTRA_STREAMS.append({"channel": _cid, "url": _url, "quality": _q})
    EXTRA_CHANNELS[_cid] = {"id": _cid, "name": _name, "country": _country, "side": _side, "categories": [_cat], "group": _grp}
# iptv-org'da haber kategorisi eksik olan haber kanallari
NEWS_OVERRIDE = {
    "NTV.tr": "TR · Haber", "SozcuTV.tr": "TR · Haber", "Tele1.tr": "TR · Haber", "TVNET.tr": "TR · Haber",
    "ntv.de": "DE · Nachrichten",
    # Ekonomi kanallari
    "BloombergHT.tr": TR_EKONOMI, "CNBCe.tr": TR_EKONOMI, "FinansTurkTV.tr": TR_EKONOMI, "Ekoturk.tr": TR_EKONOMI,
}
# propaganda / yabanci dilli haber kanallari
EXCLUDE_IDS = {"RTDE.ru", "RTDE.de", "MekameleenTV.tr", "AlmahriahTV.tr", "DW.de",  # DW.de: Arapca yayin
               "CuriosityChannel.de"}  # aslinda SPIEGEL TV Pluto yayini (asagida SPIEGEL TV olarak var)
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

# Yayin dili filtresi: Almanca (Isvicre/Bavyera/Luksemburg lehceleri dahil) ve Turkce
LANG_OK = {"deu", "tur", "gsw", "bar", "ltz"}
# iptv-org'da dili yanlis girilmis ama Almanca oldugu dogrulanmis kanallar (su an bos)
LANG_ALLOW_IDS = set()

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
              "TR · Muzik", "TR · Dini", "TR · Kultur / Yasam", TR_EKONOMI, TR_YEREL]
_DE_GROUPS = ["DE · ARD / ZDF / Offentlich", "DE · Nachrichten", "DE · Kinder", "DE · Filme / Serien",
              "DE · Unterhaltung", DE_DOKU, DE_SPORT, "DE · Musik", "DE · Religion", "DE · Regional", "DE · Sonstige"]
# Favoriler en ustte; sonra Turkce gruplar kendi icinde, Almanca gruplar kendi icinde alfabetik
GROUP_ORDER = (["★ Favoriler"] + sorted(_TR_GROUPS, key=str.casefold) + sorted(_DE_GROUPS, key=str.casefold)
               + [EN_GROUP, RADYO_GROUP, RADYO_AVRUPA, SANAT_GROUP, INT_SPORT])


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
            ok = b"#EXTM3U" in head or "video" in ctype or "audio" in ctype or "mpegurl" in ctype.lower() or head[:1] == b"G"
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
    langs, feed_langs, main_langs = {}, {}, {}
    try:
        for f in fetch_json("feeds.json"):
            fl = set(f.get("languages") or [])
            langs.setdefault(f.get("channel"), set()).update(fl)
            feed_langs[(f.get("channel"), f.get("id"))] = fl
            if f.get("is_main"):
                main_langs[f.get("channel")] = fl
    except Exception:
        pass

    def stream_ok_lang(s):
        # Yayin bazinda dil: Pluto FR/IT/ES vb. Almanca listeye karismasin
        if s in EXTRA_STREAMS or s.get("channel") in LANG_ALLOW_IDS:
            return True
        L = feed_langs.get((s.get("channel"), s.get("feed"))) if s.get("feed") else None
        if L is None:
            L = main_langs.get(s.get("channel"), set())
        return not L or bool(L & LANG_OK)
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
    candidates = [s for s in streams + EXTRA_STREAMS
                  if s.get("channel") in wanted and not is_blocked(s["url"]) and stream_ok_lang(s)]
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
        if groups[-1] in (SANAT_GROUP, INT_SPORT):  # kendi grubunda kalir, kopyalanmaz
            return [(g, ch, s) for g in groups]
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
        if cid in DE_NEWS_ALSO and "DE · Nachrichten" not in groups:
            groups.append("DE · Nachrichten")
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
