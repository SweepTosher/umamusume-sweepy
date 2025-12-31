import os
import re
import json
import time
import requests
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from tqdm import tqdm
except Exception:
    tqdm = None

userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

def isJapanese(s: str) -> bool:
    return bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff]', s or ''))

def zeroStats() -> Dict[str, float]:
    return {
        'Friendship': 0.0,
        'Guts': 0.0,
        'HP': 0.0,
        'Max Energy': 0.0,
        'Mood': 0.0,
        'Power': 0.0,
        'Skill': 0.0,
        'Skill Hint': 0.0,
        'Skill Pts': 0.0,
        'Speed': 0.0,
        'Stamina': 0.0,
        'Wisdom': 0.0,
    }

def toNum(val: Any) -> float:
    if not isinstance(val, (int, float, str)):
        return 0.0
    s = str(val).strip()
    m = re.search(r'[-+]?\d+(?:\.\d+)?', s)
    return float(m.group(0)) if m else 0.0

def getStatKey(t: str) -> Optional[str]:
    return {
        'pt': 'Skill Pts',
        'sp': 'Speed',
        'st': 'Stamina',
        'po': 'Power',
        'gu': 'Guts',
        'in': 'Wisdom',
        'hp': 'HP',
        'en': 'HP', 
        'me': 'Max Energy',
        'mo': 'Mood',
        'sk': 'Skill',
        'hi': 'Skill Hint',
        'bo': 'Friendship',
    }.get(t)

def computeStatsFromResults(results: List[Dict[str, Any]]) -> Dict[str, float]:
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    
    for v in results or []:
        k = getStatKey(v.get('t'))
        if not k:
            continue
        value = toNum(v.get('v'))
        
        if v.get('t') in ('sk', 'hi', 'bo') and value == 0:
            value = 1.0
            
        sums[k] = sums.get(k, 0.0) + value
        counts[k] = counts.get(k, 0) + 1
    
    stats = zeroStats()
    for k, total in sums.items():
        c = counts.get(k, 1)
        avg = total / c
        stats[k] = round(avg, 1) if not float(avg).is_integer() else float(int(avg))
    
    return stats

def fetchCharacterPageHtml(url: str) -> str:
    res = requests.get(url, headers={
        'User-Agent': userAgent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }, timeout=30)
    res.raise_for_status()
    return res.text

def parseNextDataCharacter(html: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    soup = BeautifulSoup(html, 'html.parser')
    script = soup.select_one('#__NEXT_DATA__')
    
    if not script or not script.string:
        return None, None
    
    try:
        data = json.loads(script.string)
    except Exception:
        return None, None
    
    pageProps = data.get('props', {}).get('pageProps', {}) or {}
    itemData = pageProps.get('itemData')
    eventData = pageProps.get('eventData') or {}
    
    payload: Optional[Dict[str, Any]] = None
    v = eventData.get('en')
    if isinstance(v, str) and v.strip():
        try:
            payload = json.loads(v)
        except Exception:
            payload = None
    elif isinstance(v, dict):
        payload = v
    
    return payload, itemData

def formatCharacterEvents(payload: Dict[str, Any]) -> Dict[str, Any]:
    formatted: Dict[str, Any] = {}
    
    for key in ('version', 'wchoice', 'outings', 'secret'):
        arr = payload.get(key)
        if not isinstance(arr, list):
            continue
        
        for event in arr:
            eventName = str(event.get('n', 'Unknown Event')).strip()
            if isJapanese(eventName):
                continue
            choices = event.get('c', []) if isinstance(event.get('c'), list) else []
            
            if len(choices) < 2:
                continue
            
            if eventName not in formatted:
                formatted[eventName] = {'choices': {}, 'stats': {}}
            
            for i, v in enumerate(choices, start=1):
                raw = str(v.get('o', '')).strip()
                label = raw if raw and not isJapanese(raw) else f'Choice {i}'
                results = v.get('r', []) if isinstance(v.get('r'), list) else []
                s = computeStatsFromResults(results)
                
                formatted[eventName]['choices'][str(i)] = label
                formatted[eventName]['stats'][str(i)] = s
    
    return formatted

def dateReached(releaseEn: Optional[str]) -> bool:
    if not releaseEn or releaseEn.strip() == '???':
        return False
    
    s = releaseEn.strip()
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s)
    if not m:
        return True
    
    try:
        y, mth, d = map(int, m.groups())
        return date(y, mth, d) <= date.today()
    except Exception:
        return True

def processCharacterUrl(url: str) -> Optional[Dict[str, Any]]:
    html = fetchCharacterPageHtml(url)
    payload, itemData = parseNextDataCharacter(html)
    if not payload:
        return None
    
    releaseEn = itemData.get('release_en') if isinstance(itemData, dict) else None
    if not dateReached(releaseEn):
        return None
    
    return formatCharacterEvents(payload)

def fetchSupportList() -> List[Dict[str, Any]]:
    res = requests.get('https://umapyoi.net/api/v1/support', headers={
        'User-Agent': userAgent,
        'Accept': 'application/json',
    }, timeout=30)
    res.raise_for_status()
    data = res.json()
    return data if isinstance(data, list) else []

def fetchSupportPageHtml(supportId: Any) -> Tuple[str, str]:
    url = f'https://umapyoi.net/api/v1/support/{supportId}/gametora'
    res = requests.get(url, headers={
        'User-Agent': userAgent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }, timeout=30)
    res.raise_for_status()
    return res.text, url

def parseNextDataSupport(html: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    soup = BeautifulSoup(html, 'html.parser')
    script = soup.select_one('#__NEXT_DATA__')
    if not script or not script.string:
        return None, None
    try:
        data = json.loads(script.string)
    except Exception:
        return None, None
    pageProps = data.get('props', {}).get('pageProps', {}) or {}
    itemData = pageProps.get('itemData')
    eventData = pageProps.get('eventData') or {}
    payload: Optional[Dict[str, Any]] = None
    v = eventData.get('en')
    if isinstance(v, str) and v.strip():
        try:
            payload = json.loads(v)
        except Exception:
            payload = None
    elif isinstance(v, dict):
        payload = v
    return payload, itemData

def formatSupportEvents(payload: Dict[str, Any]) -> Dict[str, Any]:
    formatted: Dict[str, Any] = {}
    for arr in (payload or {}).values():
        if not isinstance(arr, list):
            continue
        for event in arr:
            if not isinstance(event, dict):
                continue
            eventName = event.get('n', 'Unknown Event')
            if isJapanese(eventName):
                continue
            choices = event.get('c', []) if isinstance(event.get('c'), list) else []
            if len(choices) < 2:
                continue
            if eventName not in formatted:
                formatted[eventName] = {'choices': {}, 'stats': {}}
            for i, v in enumerate(choices, start=1):
                raw = str(v.get('o', '')).strip()
                label = raw if raw and not isJapanese(raw) else f'Choice {i}'
                results = v.get('r', []) if isinstance(v.get('r'), list) else []
                s = computeStatsFromResults(results)
                formatted[eventName]['choices'][str(i)] = label
                formatted[eventName]['stats'][str(i)] = s
    return formatted

def processSupportId(supportId: Any) -> Optional[Dict[str, Any]]:
    html, url = fetchSupportPageHtml(supportId)
    payload, itemData = parseNextDataSupport(html)
    if not payload:
        return None
    releaseEn = itemData.get('release_en') if isinstance(itemData, dict) else None
    if releaseEn == '???':
        return None
    return formatSupportEvents(payload)

def mergeAggregated(aggregated: Dict[str, Any], newData: Dict[str, Any]) -> None:
    for eventName, eventData in newData.items():
        if eventName not in aggregated:
            aggregated[eventName] = {
                'choices': {},
                'stats_sum': {},
                'stats_count': {},
            }
        for choiceNum, label in eventData['choices'].items():
            existing = aggregated[eventName]['choices'].get(choiceNum)
            if not existing:
                aggregated[eventName]['choices'][choiceNum] = label
            elif existing != label:
                aggregated[eventName]['choices'][choiceNum] = f'Choice {choiceNum}'
        for choiceNum, stats in eventData['stats'].items():
            if choiceNum not in aggregated[eventName]['stats_sum']:
                aggregated[eventName]['stats_sum'][choiceNum] = zeroStats()
                aggregated[eventName]['stats_count'][choiceNum] = 0
            for statName, value in stats.items():
                aggregated[eventName]['stats_sum'][choiceNum][statName] += value
            aggregated[eventName]['stats_count'][choiceNum] += 1

def finalizeAverages(aggregated: Dict[str, Any]) -> Dict[str, Any]:
    final: Dict[str, Any] = {}
    
    for eventName, eventData in aggregated.items():
        final[eventName] = {
            'choices': eventData['choices'],
            'stats': {}
        }
        
        for choiceNum in eventData['stats_sum']:
            count = eventData['stats_count'][choiceNum]
            if count == 0:
                continue
            
            stats = {}
            for statName, total in eventData['stats_sum'][choiceNum].items():
                avg = total / count
                stats[statName] = round(avg, 1) if not float(avg).is_integer() else float(int(avg))
            
            final[eventName]['stats'][choiceNum] = stats
    
    return final

def runEventsEn() -> None:
    aggregated: Dict[str, Any] = {}

    try:
        supportList = fetchSupportList()
    except Exception as e:
        print(f"Failed to fetch support list: {e}")
        supportList = []

    charUrls = [
        'https://gametora.com/umamusume/characters/100101-special-week',
        'https://gametora.com/umamusume/characters/100102-special-week',
        'https://gametora.com/umamusume/characters/100103-special-week',
        'https://gametora.com/umamusume/characters/100201-silence-suzuka',
        'https://gametora.com/umamusume/characters/100202-silence-suzuka',
        'https://gametora.com/umamusume/characters/100301-tokai-teio',
        'https://gametora.com/umamusume/characters/100302-tokai-teio',
        'https://gametora.com/umamusume/characters/100303-tokai-teio',
        'https://gametora.com/umamusume/characters/100401-maruzensky',
        'https://gametora.com/umamusume/characters/100402-maruzensky',
        'https://gametora.com/umamusume/characters/100403-maruzensky',
        'https://gametora.com/umamusume/characters/100501-fuji-kiseki',
        'https://gametora.com/umamusume/characters/100502-fuji-kiseki',
        'https://gametora.com/umamusume/characters/100601-oguri-cap',
        'https://gametora.com/umamusume/characters/100602-oguri-cap',
        'https://gametora.com/umamusume/characters/100701-gold-ship',
        'https://gametora.com/umamusume/characters/100702-gold-ship',
        'https://gametora.com/umamusume/characters/100703-gold-ship',
        'https://gametora.com/umamusume/characters/100801-vodka',
        'https://gametora.com/umamusume/characters/100802-vodka',
        'https://gametora.com/umamusume/characters/100901-daiwa-scarlet',
        'https://gametora.com/umamusume/characters/100902-daiwa-scarlet',
        'https://gametora.com/umamusume/characters/101001-taiki-shuttle',
        'https://gametora.com/umamusume/characters/101002-taiki-shuttle',
        'https://gametora.com/umamusume/characters/101101-grass-wonder',
        'https://gametora.com/umamusume/characters/101102-grass-wonder',
        'https://gametora.com/umamusume/characters/101103-grass-wonder',
        'https://gametora.com/umamusume/characters/101201-hishi-amazon',
        'https://gametora.com/umamusume/characters/101202-hishi-amazon',
        'https://gametora.com/umamusume/characters/101301-mejiro-mcqueen',
        'https://gametora.com/umamusume/characters/101302-mejiro-mcqueen',
        'https://gametora.com/umamusume/characters/101303-mejiro-mcqueen',
        'https://gametora.com/umamusume/characters/101401-el-condor-pasa',
        'https://gametora.com/umamusume/characters/101402-el-condor-pasa',
        'https://gametora.com/umamusume/characters/101501-tm-opera-o',
        'https://gametora.com/umamusume/characters/101502-tm-opera-o',
        'https://gametora.com/umamusume/characters/101601-narita-brian',
        'https://gametora.com/umamusume/characters/101602-narita-brian',
        'https://gametora.com/umamusume/characters/101701-symboli-rudolf',
        'https://gametora.com/umamusume/characters/101702-symboli-rudolf',
        'https://gametora.com/umamusume/characters/101801-air-groove',
        'https://gametora.com/umamusume/characters/101802-air-groove',
        'https://gametora.com/umamusume/characters/101901-agnes-digital',
        'https://gametora.com/umamusume/characters/101902-agnes-digital',
        'https://gametora.com/umamusume/characters/102001-seiun-sky',
        'https://gametora.com/umamusume/characters/102002-seiun-sky',
        'https://gametora.com/umamusume/characters/102101-tamamo-cross',
        'https://gametora.com/umamusume/characters/102102-tamamo-cross',
        'https://gametora.com/umamusume/characters/102201-fine-motion',
        'https://gametora.com/umamusume/characters/102202-fine-motion',
        'https://gametora.com/umamusume/characters/102301-biwa-hayahide',
        'https://gametora.com/umamusume/characters/102302-biwa-hayahide',
        'https://gametora.com/umamusume/characters/102303-biwa-hayahide',
        'https://gametora.com/umamusume/characters/102401-mayano-top-gun',
        'https://gametora.com/umamusume/characters/102402-mayano-top-gun',
        'https://gametora.com/umamusume/characters/102403-mayano-top-gun',
        'https://gametora.com/umamusume/characters/102501-manhattan-cafe',
        'https://gametora.com/umamusume/characters/102502-manhattan-cafe',
        'https://gametora.com/umamusume/characters/102601-mihono-bourbon',
        'https://gametora.com/umamusume/characters/102602-mihono-bourbon',
        'https://gametora.com/umamusume/characters/102701-mejiro-ryan',
        'https://gametora.com/umamusume/characters/102702-mejiro-ryan',
        'https://gametora.com/umamusume/characters/102801-hishi-akebono',
        'https://gametora.com/umamusume/characters/102901-yukino-bijin',
        'https://gametora.com/umamusume/characters/102902-yukino-bijin',
        'https://gametora.com/umamusume/characters/103001-rice-shower',
        'https://gametora.com/umamusume/characters/103002-rice-shower',
        'https://gametora.com/umamusume/characters/103003-rice-shower',
        'https://gametora.com/umamusume/characters/103101-ines-fujin',
        'https://gametora.com/umamusume/characters/103102-ines-fujin',
        'https://gametora.com/umamusume/characters/103103-ines-fujin',
        'https://gametora.com/umamusume/characters/103201-agnes-tachyon',
        'https://gametora.com/umamusume/characters/103202-agnes-tachyon',
        'https://gametora.com/umamusume/characters/103203-agnes-tachyon',
        'https://gametora.com/umamusume/characters/103301-admire-vega',
        'https://gametora.com/umamusume/characters/103302-admire-vega',
        'https://gametora.com/umamusume/characters/103401-inari-one',
        'https://gametora.com/umamusume/characters/103402-inari-one',
        'https://gametora.com/umamusume/characters/103501-winning-ticket',
        'https://gametora.com/umamusume/characters/103502-winning-ticket',
        'https://gametora.com/umamusume/characters/103503-winning-ticket',
        'https://gametora.com/umamusume/characters/103601-air-shakur',
        'https://gametora.com/umamusume/characters/103602-air-shakur',
        'https://gametora.com/umamusume/characters/103701-eishin-flash',
        'https://gametora.com/umamusume/characters/103702-eishin-flash',
        'https://gametora.com/umamusume/characters/103703-eishin-flash',
        'https://gametora.com/umamusume/characters/103801-curren-chan',
        'https://gametora.com/umamusume/characters/103802-curren-chan',
        'https://gametora.com/umamusume/characters/103901-kawakami-princess',
        'https://gametora.com/umamusume/characters/103902-kawakami-princess',
        'https://gametora.com/umamusume/characters/104001-gold-city',
        'https://gametora.com/umamusume/characters/104002-gold-city',
        'https://gametora.com/umamusume/characters/104003-gold-city',
        'https://gametora.com/umamusume/characters/104101-sakura-bakushin-o',
        'https://gametora.com/umamusume/characters/104102-sakura-bakushin-o',
        'https://gametora.com/umamusume/characters/104201-seeking-the-pearl',
        'https://gametora.com/umamusume/characters/104202-seeking-the-pearl',
        'https://gametora.com/umamusume/characters/104301-shinko-windy',
        'https://gametora.com/umamusume/characters/104401-sweep-tosho',
        'https://gametora.com/umamusume/characters/104402-sweep-tosho',
        'https://gametora.com/umamusume/characters/104501-super-creek',
        'https://gametora.com/umamusume/characters/104502-super-creek',
        'https://gametora.com/umamusume/characters/104503-super-creek',
        'https://gametora.com/umamusume/characters/104601-smart-falcon',
        'https://gametora.com/umamusume/characters/104602-smart-falcon',
        'https://gametora.com/umamusume/characters/104603-smart-falcon',
        'https://gametora.com/umamusume/characters/104701-zenno-rob-roy',
        'https://gametora.com/umamusume/characters/104702-zenno-rob-roy',
        'https://gametora.com/umamusume/characters/104801-tosen-jordan',
        'https://gametora.com/umamusume/characters/104802-tosen-jordan',
        'https://gametora.com/umamusume/characters/104901-nakayama-festa',
        'https://gametora.com/umamusume/characters/105001-narita-taishin',
        'https://gametora.com/umamusume/characters/105002-narita-taishin',
        'https://gametora.com/umamusume/characters/105003-narita-taishin',
        'https://gametora.com/umamusume/characters/105101-nishino-flower',
        'https://gametora.com/umamusume/characters/105102-nishino-flower',
        'https://gametora.com/umamusume/characters/105201-haru-urara',
        'https://gametora.com/umamusume/characters/105202-haru-urara',
        'https://gametora.com/umamusume/characters/105301-bamboo-memory',
        'https://gametora.com/umamusume/characters/105302-bamboo-memory',
        'https://gametora.com/umamusume/characters/105401-biko-pegasus',
        'https://gametora.com/umamusume/characters/105501-marvelous-sunday',
        'https://gametora.com/umamusume/characters/105601-matikanefukukitaru',
        'https://gametora.com/umamusume/characters/105602-matikanefukukitaru',
        'https://gametora.com/umamusume/characters/105701-mr-cb',
        'https://gametora.com/umamusume/characters/105702-mr-cb',
        'https://gametora.com/umamusume/characters/105801-meisho-doto',
        'https://gametora.com/umamusume/characters/105802-meisho-doto',
        'https://gametora.com/umamusume/characters/105901-mejiro-dober',
        'https://gametora.com/umamusume/characters/105902-mejiro-dober',
        'https://gametora.com/umamusume/characters/106001-nice-nature',
        'https://gametora.com/umamusume/characters/106002-nice-nature',
        'https://gametora.com/umamusume/characters/106003-nice-nature',
        'https://gametora.com/umamusume/characters/106101-king-halo',
        'https://gametora.com/umamusume/characters/106102-king-halo',
        'https://gametora.com/umamusume/characters/106103-king-halo',
        'https://gametora.com/umamusume/characters/106201-matikanetannhauser',
        'https://gametora.com/umamusume/characters/106202-matikanetannhauser',
        'https://gametora.com/umamusume/characters/106301-ikuno-dictus',
        'https://gametora.com/umamusume/characters/106401-mejiro-palmer',
        'https://gametora.com/umamusume/characters/106402-mejiro-palmer',
        'https://gametora.com/umamusume/characters/106501-daitaku-helios',
        'https://gametora.com/umamusume/characters/106502-daitaku-helios',
        'https://gametora.com/umamusume/characters/106601-twin-turbo',
        'https://gametora.com/umamusume/characters/106701-satono-diamond',
        'https://gametora.com/umamusume/characters/106702-satono-diamond',
        'https://gametora.com/umamusume/characters/106703-satono-diamond',
        'https://gametora.com/umamusume/characters/106801-kitasan-black',
        'https://gametora.com/umamusume/characters/106802-kitasan-black',
        'https://gametora.com/umamusume/characters/106803-kitasan-black',
        'https://gametora.com/umamusume/characters/106901-sakura-chiyono-o',
        'https://gametora.com/umamusume/characters/106902-sakura-chiyono-o',
        'https://gametora.com/umamusume/characters/107001-sirius-symboli',
        'https://gametora.com/umamusume/characters/107002-sirius-symboli',
        'https://gametora.com/umamusume/characters/107101-mejiro-ardan',
        'https://gametora.com/umamusume/characters/107102-mejiro-ardan',
        'https://gametora.com/umamusume/characters/107201-yaeno-muteki',
        'https://gametora.com/umamusume/characters/107202-yaeno-muteki',
        'https://gametora.com/umamusume/characters/107301-tsurumaru-tsuyoshi',
        'https://gametora.com/umamusume/characters/107401-mejiro-bright',
        'https://gametora.com/umamusume/characters/107402-mejiro-bright',
        'https://gametora.com/umamusume/characters/107601-sakura-laurel',
        'https://gametora.com/umamusume/characters/107701-narita-top-road',
        'https://gametora.com/umamusume/characters/107702-narita-top-road',
        'https://gametora.com/umamusume/characters/107801-yamanin-zephyr',
        'https://gametora.com/umamusume/characters/107802-yamanin-zephyr',
        'https://gametora.com/umamusume/characters/107901-furioso',
        'https://gametora.com/umamusume/characters/108001-transcend',
        'https://gametora.com/umamusume/characters/108101-espoir-city',
        'https://gametora.com/umamusume/characters/108201-north-flight',
        'https://gametora.com/umamusume/characters/108301-symboli-kris-s',
        'https://gametora.com/umamusume/characters/108302-symboli-kris-s',
        'https://gametora.com/umamusume/characters/108401-tanino-gimlet',
        'https://gametora.com/umamusume/characters/108402-tanino-gimlet',
        'https://gametora.com/umamusume/characters/108501-daiichi-ruby',
        'https://gametora.com/umamusume/characters/108502-daiichi-ruby',
        'https://gametora.com/umamusume/characters/108601-mejiro-ramonu',
        'https://gametora.com/umamusume/characters/108602-mejiro-ramonu',
        'https://gametora.com/umamusume/characters/108701-aston-machan',
        'https://gametora.com/umamusume/characters/108702-aston-machan',
        'https://gametora.com/umamusume/characters/108801-satono-crown',
        'https://gametora.com/umamusume/characters/108802-satono-crown',
        'https://gametora.com/umamusume/characters/108901-cheval-grand',
        'https://gametora.com/umamusume/characters/108902-cheval-grand',
        'https://gametora.com/umamusume/characters/109001-verxina',
        'https://gametora.com/umamusume/characters/109101-vivlos',
        'https://gametora.com/umamusume/characters/109102-vivlos',
        'https://gametora.com/umamusume/characters/109301-ksmiracle',
        'https://gametora.com/umamusume/characters/109302-ksmiracle',
        'https://gametora.com/umamusume/characters/109401-jungle-pocket',
        'https://gametora.com/umamusume/characters/109601-no-reason',
        'https://gametora.com/umamusume/characters/109701-still-in-love',
        'https://gametora.com/umamusume/characters/109801-copano-rickey',
        'https://gametora.com/umamusume/characters/109802-copano-rickey',
        'https://gametora.com/umamusume/characters/109901-hokko-tarumae',
        'https://gametora.com/umamusume/characters/109902-hokko-tarumae',
        'https://gametora.com/umamusume/characters/110001-wonder-acute',
        'https://gametora.com/umamusume/characters/110201-sounds-of-earth',
        'https://gametora.com/umamusume/characters/110401-katsuragi-ace',
        'https://gametora.com/umamusume/characters/110402-katsuragi-ace',
        'https://gametora.com/umamusume/characters/110501-neo-universe',
        'https://gametora.com/umamusume/characters/110502-neo-universe',
        'https://gametora.com/umamusume/characters/110601-hishi-miracle',
        'https://gametora.com/umamusume/characters/110602-hishi-miracle',
        'https://gametora.com/umamusume/characters/110701-tap-dance-city',
        'https://gametora.com/umamusume/characters/110702-tap-dance-city',
        'https://gametora.com/umamusume/characters/110801-duramente',
        'https://gametora.com/umamusume/characters/110901-rhein-kraft',
        'https://gametora.com/umamusume/characters/110902-rhein-kraft',
        'https://gametora.com/umamusume/characters/111001-cesario',
        'https://gametora.com/umamusume/characters/111002-cesario',
        'https://gametora.com/umamusume/characters/111101-air-messiah',
        'https://gametora.com/umamusume/characters/111301-fusaichi-pandora',
        'https://gametora.com/umamusume/characters/111501-orfevre',
        'https://gametora.com/umamusume/characters/111601-gentildonna',
        'https://gametora.com/umamusume/characters/111701-win-variation',
        'https://gametora.com/umamusume/characters/111901-dream-journey',
        'https://gametora.com/umamusume/characters/112001-calstone-light-o',
        'https://gametora.com/umamusume/characters/112101-durandal',
        'https://gametora.com/umamusume/characters/112401-bubble-gum-fellow',
        'https://gametora.com/umamusume/characters/112701-fenomeno',
        'https://gametora.com/umamusume/characters/113101-gran-alegria',
        'https://gametora.com/umamusume/characters/113201-loves-only-you',
        'https://gametora.com/umamusume/characters/113301-chrono-genesis',
    ]

    totalTasks = len(supportList) + len(charUrls)
    if totalTasks == 0:
        finalOut = finalizeAverages(aggregated)
        with open('events_en.json', 'w', encoding='utf-8') as f:
            json.dump(finalOut, f, ensure_ascii=False, indent=2)
        print(f'Saved: events_en.json ({len(finalOut)} events)')
        return

    maxWorkers = min(16, max(4, os.cpu_count() or 8))
    bar = tqdm(total=totalTasks, desc="Processing") if tqdm else None

    def processTask(future):
        nonlocal aggregated
        try:
            result = future.result()
            if result:
                mergeAggregated(aggregated, result)
        except Exception:
            pass
        if bar:
            bar.update(1)

    with ThreadPoolExecutor(max_workers=maxWorkers) as executor:
        futures = []
        for v in supportList:
            sid = v.get('id') if isinstance(v, dict) else None
            if sid is not None:
                futures.append(executor.submit(processSupportId, sid))
        for v in charUrls:
            futures.append(executor.submit(processCharacterUrl, v))
        
        for future in futures:
            processTask(future)

    if bar:
        bar.close()

    finalOut = finalizeAverages(aggregated)
    forced_events = {
        "New Year's Shrine Visit": {
            "choices": {
                "1": "Choice 1",
                "2": "Choice 2",
                "3": "Choice 3"
            },
            "stats": {
                "1": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 30.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                },
                "2": {
                    "Friendship": 0.0,
                    "Guts": 5.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 5.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 5.0,
                    "Stamina": 5.0,
                    "Wisdom": 5.0
                },
                "3": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 35.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                }
            }
        },
         "Tutorial": {
            "choices": {
                "1": "Choice 1",
                "2": "Choice 2",
                "3": "Choice 3",
                "4": "Choice 4",
                "5": "Choice 5"
            },
            "stats": {
                "1": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                },
                "2": {
                    "Friendship": 100000.0,
                    "Guts":111110.0,
                    "HP": 111110.0,
                    "Max Energy": 111110.0,
                    "Mood": 1110.0,
                    "Power": 1110.0,
                    "Skill": 110.0,
                    "Skill Hint": 110.0,
                    "Skill Pts": 110.0,
                    "Speed": 110.0,
                    "Stamina": 110.0,
                    "Wisdom": 110.0
                },
                "3": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                },
                "4": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                },
                "5": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                }
            }
        },
        "New Year's Resolutions": {
        "choices": {
            "1": "Choice 1",
            "2": "Choice 2",
            "3": "Choice 3"
            },
            "stats": {
                "1": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 10.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                },
                "2": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 20.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                },
                "3": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 20.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                }
            }
        },
        "Extra Training": {
            "choices": {
                "1": "Choice 1",
                "2": "Choice 2"
            },
            "stats": {
                "1": {
                    "Friendship": 5.0,
                    "Guts": 0.0,
                    "HP": -5.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 5.0,
                    "Stamina": 0.0,
                    "Wisdom": 5.0
                },
                "2": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 5.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                }
            }
        },
        "Don't Overdo It!": {
            "choices": {
                "1": "Choice 1",
                "2": "Choice 2"
            },
            "stats": {
                "1": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                },
                "2": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                }
            }
        },
        "Get Well Soon!": {
            "choices": {
                "1": "Choice 1",
                "2": "Choice 2"
            },
            "stats": {
                "1": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                },
                "2": {
                    "Friendship": 0.0,
                    "Guts": 0.0,
                    "HP": 0.0,
                    "Max Energy": 0.0,
                    "Mood": 0.0,
                    "Power": 0.0,
                    "Skill": 0.0,
                    "Skill Hint": 0.0,
                    "Skill Pts": 0.0,
                    "Speed": 0.0,
                    "Stamina": 0.0,
                    "Wisdom": 0.0
                }
            }
        }
    }
    finalOut.update(forced_events)
    with open('event_data.json', 'w', encoding='utf-8') as f:
        json.dump(finalOut, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    runEventsEn()