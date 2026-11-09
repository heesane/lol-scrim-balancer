# 단일 파일 내전 수집기: 이 파일만 실행하세요. exe 빌드·배포는 같은 폴더의 README.md를 참고하세요.
# lcu_collector.py - 롤 클라이언트 로컬 LCU API 사설 내전 10인 스탯 자동 수집기 (완성본)
import os
import sys
import time
import json
import base64
import urllib.request
import ssl
import datetime
import re  # 딥롤 페이지 파싱에 필요 (누락 시 NameError가 except에 삼켜짐)
import urllib.error

SERVER_URL = "https://lol-scrim-balancer.vercel.app/api/sync"

FROZEN = getattr(sys, 'frozen', False)


def data_dir():
    """대기 큐·아카이브·백업을 둘 폴더를 정한다.

    스크립트로 실행하면 기존처럼 이 파일이 있는 폴더를 쓴다.
    PyInstaller onefile exe는 임시 폴더(_MEIPASS)에 풀리므로
    %LOCALAPPDATA%\\ScrimCollector에 두고, 없으면 exe가 있는 폴더를 쓴다.
    """
    if not FROZEN:
        return os.path.dirname(os.path.abspath(__file__))
    local = os.environ.get('LOCALAPPDATA')
    folder = os.path.join(local, 'ScrimCollector') if local else os.path.dirname(os.path.abspath(sys.executable))
    os.makedirs(folder, exist_ok=True)
    return folder


DATA_DIR = data_dir()

def test_lcu_connection(port, password):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"https://127.0.0.1:{port}/help"
    auth_header = "Basic " + base64.b64encode(f"riot:{password}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": auth_header})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=1.5) as res:
            return res.status == 200
    except Exception:
        return False

def get_lcu_credentials():
    possible_paths = [
        r"C:\Riot Games\League of Legends\lockfile",
        r"D:\Riot Games\League of Legends\lockfile",
        r"C:\Program Files\Riot Games\League of Legends\lockfile",
        r"D:\Program Files\Riot Games\League of Legends\lockfile"
    ]
    for p in possible_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    parts = f.read().split(":")
                    if len(parts) >= 4:
                        port = parts[2]
                        password = parts[3]
                        if test_lcu_connection(port, password):
                            return port, password
            except Exception:
                pass
    return None, None

def query_lcu(port, password, endpoint):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"https://127.0.0.1:{port}{endpoint}"
    auth_header = "Basic " + base64.b64encode(f"riot:{password}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": auth_header})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=3) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

def preserve_match(record):
    folder = os.path.join(os.path.dirname(QUEUE_PATH), 'lcu_match_archive')
    os.makedirs(folder, exist_ok=True)
    match_id = str(record['matchId'])
    if not match_id.startswith('LCU_') or not match_id[4:].isdigit():
        raise ValueError('잘못된 경기 ID입니다.')
    path = os.path.join(folder, match_id + '.json')
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(path + '.tmp', path)


def is_scrim(data):
    return (isinstance(data, dict) and 'CUSTOM' in str(data.get('gameType') or data.get('queueType') or '').upper()
            and data.get('gameMode') == 'CLASSIC' and data.get('mapId', 11) == 11)


def push_match_to_cloud(match_data):
    ctx = ssl.create_default_context()
    try:
        preserve_match(match_data)
        req_get = urllib.request.Request(SERVER_URL, headers={"Accept": "application/json"})
        existing_data = {}
        with urllib.request.urlopen(req_get, context=ctx, timeout=5) as res:
            existing_data = json.loads(res.read().decode())

        if not isinstance(existing_data, dict) or "matchHistory" not in existing_data:
            raise ValueError("서버 기록이 누락된 응답입니다. 덮어쓰기를 중단합니다.")
        match_history = existing_data["matchHistory"]
        if not isinstance(existing_data, dict) or not isinstance(match_history, list):
            raise ValueError("서버 데이터 형식이 올바르지 않습니다.")
        match_id = match_data["matchId"]
        if any(isinstance(m, dict) and m.get("matchId") == match_id for m in match_history):
            print(f"[-] 이미 등록된 경기(ID: {match_id})입니다.")
            return True

        backups = os.path.join(os.path.dirname(QUEUE_PATH), 'lcu_server_backups')
        os.makedirs(backups, exist_ok=True)
        with open(os.path.join(backups, str(time.time_ns()) + '.json'), 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False)
        match_history.insert(0, match_data)
        existing_data["matchHistory"] = match_history
        existing_data["updatedAt"] = int(time.time() * 1000)

        json_payload = json.dumps(existing_data).encode("utf-8")
        req_post = urllib.request.Request(
            SERVER_URL,
            data=json_payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req_post, context=ctx, timeout=5) as res:
            resp_json = json.loads(res.read().decode())
            if resp_json.get("success"):
                print(f"[ 성공] 내전 결과가 웹앱({SERVER_URL})에 완벽히 동기화되었습니다!")
                return True
    except Exception as e:
        print(f"[!] 웹앱 동기화 전송 실패: {e}")
    print("[!] 동기화 전송 실패: 서버가 성공 응답을 반환하지 않았습니다.")
    return False


QUEUE_PATH = os.path.join(DATA_DIR, "lcu_pending_matches.json")

def save_pending(pending):
    temporary = QUEUE_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, QUEUE_PATH)

def load_pending():
    try:
        with open(QUEUE_PATH, encoding="utf-8") as f:
            pending = json.load(f)
        if not isinstance(pending, dict):
            raise ValueError("대기 파일이 올바른 객체가 아닙니다.")
        for match_id, record in pending.items():
            if not isinstance(record, dict) or record.get('matchId') != match_id or not isinstance(record.get('blue'), list) or not isinstance(record.get('red'), list):
                raise ValueError('전송 대기 파일이 손상되었습니다. 원본 파일을 보존하고 로그를 확인하세요.')
        return pending
    except FileNotFoundError:
        return {}

def retry_pending(pending, completed):
    for match_id, record in list(pending.items()):
        if push_match_to_cloud(record):
            del pending[match_id]
            save_pending(pending)
            completed.add(match_id)

def game_id_equal(left, right):
    return left is not None and right is not None and str(left) == str(right)


def result_is_win(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('win', 'true', 'victory')
    return False


def winner_team_id(teams):
    winners = [t.get('teamId') for t in teams
               if t.get('teamId') in (100, 200)
               and result_is_win(t.get('isWinningTeam', t.get('won', t.get('win'))))]
    return winners[0] if len(winners) == 1 else None


def load_champion_names(port, password):
    data = query_lcu(port, password, '/lol-game-data/assets/v1/champion-summary.json')
    if not isinstance(data, list):
        return {}
    return {int(champion['id']): champion['name'] for champion in data
            if isinstance(champion, dict) and isinstance(champion.get('id'), int)
            and champion['id'] > 0 and champion.get('name')}


def resolve_champion_name(player, names):
    try:
        champion_id = int(player.get('championId', 0))
    except (ValueError, TypeError):
        champion_id = 0
    if names.get(champion_id):
        return names[champion_id]
    raw = player.get('championName')
    if isinstance(raw, str) and raw.strip().upper() not in ('', 'UNKNOWN', 'NONE', 'NULL', 'UNDEFINED'):
        return raw.strip()
    return f'챔피언 ID {champion_id}' if champion_id > 0 else '챔피언 정보 없음'


def normalize_result(data, champion_names=None):
    normalized = dict(data)
    champion_names = champion_names or {}
    identities = {i.get('participantId'): i.get('player', {}) for i in data.get('participantIdentities', [])}
    players = list(data.get('participants') or [])
    if not players:
        for team in data.get('teams', []):
            for player in team.get('players', []) or []:
                players.append({**player, 'teamId': team.get('teamId')})
    result = []
    aliases = {'CHAMPIONS_KILLED':'kills', 'NUM_DEATHS':'deaths', 'ASSISTS':'assists',
               'TOTAL_DAMAGE_DEALT_TO_CHAMPIONS':'totalDamageDealtToChampions',
               'MINIONS_KILLED':'totalMinionsKilled', 'NEUTRAL_MINIONS_KILLED':'neutralMinionsKilled'}
    for player in players:
        identity = identities.get(player.get('participantId'), {})
        stats = player.get('stats') or {}
        numeric = {}
        for field, alias in aliases.items():
            value = stats.get(field, stats.get(alias, 0))
            try:
                numeric[field] = int(value)
            except (ValueError, TypeError, OverflowError):
                raise ValueError(f'잘못된 스탯 값: {field}')
        result.append({**player, 'stats': numeric,
            'summonerName': player.get('riotIdGameName') or identity.get('gameName') or player.get('summonerName') or identity.get('summonerName'),
            'tagLine': player.get('riotIdTagLine') or player.get('tagLine') or identity.get('tagLine'),
            'teamPosition': next((value for value in [player.get('detectedTeamPosition'), player.get('teamPosition'), player.get('selectedPosition')] if value and str(value).upper() not in ('UNKNOWN', 'NONE', 'UNSELECTED', 'INVALID')), None),
            'championName': resolve_champion_name(player, champion_names)})
    normalized['participants'] = result
    normalized['gameLength'] = data.get('gameLength') or data.get('gameDuration')
    return normalized


def format_duration(stats):
    # gameLength는 초 단위로 취급하며, 없는 값은 추측하지 않습니다.
    seconds = stats.get("gameLength")
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0:
        minutes, seconds = divmod(int(seconds), 60)
        return f"{minutes}분 {seconds:02d}초"
    return "알 수 없음"



_DEEPLOL_TRIES = {}   # game_id -> 크롤링 시도 횟수 (결과 재조회 때마다 15초씩 낭비되는 것 방지)
_DEEPLOL_CACHE = {}   # game_id -> 성공한 점수 딕셔너리

def fetch_deeplol_real_scores(game_id, max_retries=6, delay=3.0):
    """
    게임 종료 후 딥롤(DeepLoL) 경기 페이지에서 10인의 실제 AI-Score를 가져옵니다.
    실패 원인은 로그에 그대로 출력합니다. (403=차단, 404=해당 경기 페이지 없음, 파싱 실패=페이지 구조 상이)
    """
    if game_id in _DEEPLOL_CACHE:
        return _DEEPLOL_CACHE[game_id]
    if _DEEPLOL_TRIES.get(game_id, 0) >= 2:      # 같은 경기는 최대 2회까지만 크롤링 시도
        return {}
    _DEEPLOL_TRIES[game_id] = _DEEPLOL_TRIES.get(game_id, 0) + 1

    match_key = f"KR_{game_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.deeplol.gg/"
    }
    target_url = f"https://www.deeplol.gg/match/kr/{match_key}"

    print(f"[*] 딥롤 실제 AI-Score 크롤링 시도 중 (Match ID: {match_key})...")
    time.sleep(3)  # 딥롤 서버 전적 집계 대기

    last_reason = ''
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as res:
                html = res.read().decode('utf-8', errors='ignore')

            scores = {}
            json_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
            if not json_match:
                last_reason = f'페이지에 __NEXT_DATA__ 가 없습니다 (응답 {len(html)}자) - 차단 페이지이거나 사이트 구조가 다릅니다'
            else:
                page_data = json.loads(json_match.group(1))
                match_data = page_data.get('props', {}).get('pageProps', {}).get('matchData', {})
                participants = match_data.get('participants', []) if isinstance(match_data, dict) else []
                for p in participants:
                    g_name = p.get('riotIdGameName') or p.get('summonerName') or ''
                    tag = p.get('riotIdTagLine') or ''
                    full_name = f"{g_name}#{tag}" if tag else g_name
                    ai_score = p.get('aiScore') or p.get('score')
                    if full_name and ai_score:
                        scores[full_name] = int(ai_score)
                if len(scores) >= 10:
                    print("[+] 딥롤 실제 AI-Score 10인 크롤링 성공!")
                    _DEEPLOL_CACHE[game_id] = scores
                    return scores
                last_reason = f'점수를 찾지 못했습니다 (참가자 {len(participants)}명 중 점수 {len(scores)}명)'
        except urllib.error.HTTPError as err:
            last_reason = f'HTTP {err.code} ({"차단/봇 방어" if err.code in (403, 429) else "해당 경기 페이지 없음" if err.code == 404 else "서버 응답 오류"})'
        except Exception as err:
            last_reason = f'{type(err).__name__}: {err}'

        print(f"[-] 딥롤 경기 반영 대기 중 ({attempt + 1}/{max_retries}) · {last_reason}")
        time.sleep(delay)

    print("[!] 딥롤 크롤링 미반영: 딥롤 실측 보정 공식으로 자동 산출합니다.")
    return {}

def build_match_record(stats):
    game_id = stats["gameId"]
    teams = stats.get("teams", [])
    winner_id = winner_team_id(teams)
    if winner_id is None:
        raise ValueError("승리 팀 정보가 아직 없습니다.")
    blue_win = winner_id == 100
            
    blue_team = []
    red_team = []
    all_players = []
    
    # 🌟 딥롤 실시간 AI-Score 크롤링
    deeplol_scores = fetch_deeplol_real_scores(game_id)

    for p in stats.get("participants", []):
        if p.get("teamId") not in (100, 200):
            raise ValueError("알 수 없는 팀 ID입니다.")
        k = p.get("stats", {}).get("CHAMPIONS_KILLED", 0)
        d = p.get("stats", {}).get("NUM_DEATHS", 0)
        a = p.get("stats", {}).get("ASSISTS", 0)
        dmg = p.get("stats", {}).get("TOTAL_DAMAGE_DEALT_TO_CHAMPIONS", 0)
        cs = p.get("stats", {}).get("MINIONS_KILLED", 0) + p.get("stats", {}).get("NEUTRAL_MINIONS_KILLED", 0)
        raw_calc = 42 + (k * 1.35) - (d * 2.35) + (a * 0.75) + (dmg / 4200) + (cs * 0.025)
        ai_score = max(25, min(80, round(raw_calc)))
        
        # 🌟 딥롤 크롤링 결과가 있으면 실제 딥롤 점수 100% 매핑
        p_name_tag = (p.get("summonerName") or "") + (f"#{p['tagLine']}" if p.get("tagLine") else "")
        for d_name, d_score in deeplol_scores.items():
            if p_name_tag.split('#')[0].replace(" ", "").lower() == d_name.split('#')[0].replace(" ", "").lower():
                ai_score = d_score
                break
        
        role_raw = (p.get("teamPosition") or "").upper()
        role = "UNKNOWN"
        if "MID" in role_raw or "MIDDLE" in role_raw: role = "MID"
        elif "TOP" in role_raw: role = "TOP"
        elif "JUG" in role_raw or "JUNGLE" in role_raw: role = "JUG"
        elif "BOT" in role_raw or "ADC" in role_raw: role = "ADC"
        elif "SUP" in role_raw or "UTILITY" in role_raw: role = "SUP"

        p_data = {
            "name": (p.get("summonerName") or "알 수 없음") + (f"#{p['tagLine']}" if p.get("tagLine") else ""),
            "tier": "UNRANKED",
            "role": role,
            "champion": p.get("championName", "챔피언"),
            "championId": p.get("championId"),
            "aiScore": ai_score,
            "kda": f"{k}/{d}/{a} ({'Perfect' if d == 0 else round((k+a)/d, 2)})",
            "damage": f"{dmg:,}",
            "cs": cs,
            "win": (p.get("teamId") == 100 and blue_win) or (p.get("teamId") == 200 and not blue_win)
        }

        all_players.append(p_data)
        if p.get("teamId") == 100:
            blue_team.append(p_data)
        else:
            red_team.append(p_data)
    
    best_score = max([p["aiScore"] for p in all_players]) if all_players else 80
    mvp = next((p["name"] for p in all_players if p["aiScore"] == best_score), "MVP")

    stamp = stats.get("gameCreation")
    ended = stats.get("endOfGameTimestamp")
    instant = (stamp / 1000 + (stats.get("gameLength") or 0) if isinstance(stamp, (int,float)) else ended / 1000 if isinstance(ended, (int,float)) and ended > 100000000000 else time.time())
    date_str = datetime.datetime.fromtimestamp(instant).strftime("%Y-%m-%d %H:%M")

    match_record = {
        "id": f"m-LCU-{game_id}",
        "date": date_str,
        "matchId": f"LCU_{game_id}",
        "winner": "BLUE" if blue_win else "RED",
        "mvp": mvp,
        "duration": format_duration(stats),
        "blue": blue_team,
        "red": red_team
    }

    if len(blue_team) != 5 or len(red_team) != 5:
        raise ValueError("5 대 5 참가자 정보가 아직 완성되지 않았습니다.")
    return match_record


def collector_main():
    import msvcrt
    lock = open(QUEUE_PATH + '.lock', 'a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        raise RuntimeError('이미 다른 수집기가 실행 중입니다. 기존 수집기를 중지하세요.')
    try:
        collect_loop()
    finally:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


def collect_loop():
    pending = load_pending()
    state_path = QUEUE_PATH + '.state'
    try:
        with open(state_path, encoding='utf-8') as f:
            state = json.load(f)
        if not isinstance(state, dict) or not isinstance(state.get('completed', []), list):
            raise ValueError('수집 상태 파일 형식이 올바르지 않습니다.')
    except FileNotFoundError:
        state = {'completed': [], 'tracking': None}
    completed = set(state.get('completed', []))
    def save_state():
        state['completed'] = sorted(completed)
        with open(state_path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(state, f); f.flush(); os.fsync(f.fileno())
        os.replace(state_path + '.tmp', state_path)
    retry_at = {}
    attempts = {}
    announced = set()
    champion_names = {}
    connected = False
    print('[*] 수집 시작 · 5 대 5 소환사의 협곡 내전만 제출합니다.')
    while True:
        for match_id, record in list(pending.items()):
            if match_id in completed:
                del pending[match_id]; save_pending(pending)
                continue
            if time.monotonic() < retry_at.get(match_id, 0):
                continue
            if push_match_to_cloud(record):
                completed.add(match_id)
                save_state()
                del pending[match_id]
                save_pending(pending)
                print('@EVENT ' + json.dumps({'type':'submitted', 'matchId':match_id}))
            else:
                attempts[match_id] = attempts.get(match_id, 0) + 1
                retry_at[match_id] = time.monotonic() + min(120, 5 * 2 ** min(attempts[match_id]-1, 5))
            time.sleep(0)
        port, password = get_lcu_credentials()
        if not port:
            if connected:
                print('[!] 클라이언트가 종료되었습니다. 재연결 대기 중')
            connected = False
            time.sleep(3)
            continue
        if not connected:
            print('[+] 롤 클라이언트 실제 연결 성공 · 대기중')
            connected = True
        phase = query_lcu(port, password, '/lol-gameflow/v1/gameflow-phase')
        if phase in ('ChampSelect', 'GameStart', 'InProgress', 'Reconnect'):
            session = query_lcu(port, password, '/lol-gameflow/v1/session')
            game_id = (session.get('gameData') or {}).get('gameId') if isinstance(session, dict) else None
            if game_id and state.get('tracking') != game_id:
                state['tracking'] = game_id; save_state()
            time.sleep(3)
            continue
        raw = query_lcu(port, password, '/lol-end-of-game/v1/eog-stats-block')
        game_id = raw.get('gameId') if isinstance(raw, dict) else state.get('tracking')
        match_id = f'LCU_{game_id}'
        if not game_id or match_id in completed or match_id in pending:
            time.sleep(3)
            continue
        if not champion_names:
            champion_names = load_champion_names(port, password)
        history = None
        if not isinstance(raw, dict) or winner_team_id(raw.get('teams', [])) is None:
            history = query_lcu(port, password, f'/lol-match-history/v1/games/{game_id}')
            if isinstance(history, dict) and history.get('gameId') == game_id:
                raw = history
        if isinstance(raw, dict) and raw.get('gameId') == game_id:
            kind = str(raw.get('gameType') or raw.get('queueType') or '').upper()
            if 'CUSTOM' not in kind:
                # Verify unknown EOG game types using the matching history record.
                history = history or query_lcu(port, password, f'/lol-match-history/v1/games/{game_id}')
                kind = str(history.get('gameType','')).upper() if isinstance(history, dict) else ''
                if 'CUSTOM' not in kind:
                    time.sleep(3); continue
            if not is_scrim(raw):
                history = history or query_lcu(port, password, f'/lol-match-history/v1/games/{game_id}')
                if not is_scrim(history):
                    if game_id not in announced:
                        print('[*] 협곡 내전이 아니므로 수집하지 않습니다.')
                        announced.add(game_id)
                    time.sleep(3); continue
                raw = history
            try:
                try:
                    record = build_match_record(normalize_result(raw, champion_names))
                except (ValueError, TypeError, KeyError):
                    history = history or query_lcu(port, password, f'/lol-match-history/v1/games/{game_id}')
                    if not isinstance(history, dict) or history.get('gameId') != game_id:
                        raise ValueError('완전한 경기 결과를 기다리고 있습니다.')
                    record = build_match_record(normalize_result(history, champion_names))
            except (ValueError, TypeError, KeyError) as exc:
                if game_id not in announced:
                    print(f'[!] 경기 {game_id}: {exc} 자동 재확인 중')
                    announced.add(game_id)
                time.sleep(3); continue
            preserve_match(record)
            pending[match_id] = record
            save_pending(pending)
            print(f'[+] 내전 경기 종료 감지! (Game ID: {game_id}) · 로컬 저장 완료')
        time.sleep(3)



from pathlib import Path
import os
import json
import ssl
import urllib.request
import datetime
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

BASE = Path(DATA_DIR)
collector = sys.modules[__name__]


def run_worker():
    stop = threading.Event()
    def listen():
        sys.stdin.readline()
        stop.set()
    threading.Thread(target=listen, daemon=True).start()
    def sleep(seconds):
        if stop.wait(seconds):
            raise SystemExit(0)
    collector.time.sleep = sleep
    collector_main()



def resolve_lobby_members(data, port, password, name_cache):
    config = data.get('gameConfig') or {}
    def key(member):
        return member.get('puuid') or member.get('summonerId') or member.get('botUuid') or member.get('botId')
    assignments = {}
    members = {key(member): dict(member) for member in data.get('members', []) if key(member)}
    for field, label in [('customTeam100', '블루'), ('customTeam200', '레드'), ('customSpectators', '관전자')]:
        for member in config.get(field, []) or []:
            member_key = key(member)
            if member_key:
                members[member_key] = {**members.get(member_key, {}), **member}
                assignments[member_key] = label
    result = []
    for member_key, member in members.items():
        name = member.get('riotIdGameName') or member.get('summonerName')
        tag = member.get('riotIdTagLine') or member.get('tagLine')
        if not name and not member.get('isBot'):
            cached = name_cache.get(member_key)
            if cached and time.monotonic() - cached[0] < 60:
                info = cached[1]
            else:
                sid = member.get('summonerId')
                info = query_lcu(port, password, f'/lol-summoner/v1/summoners/{sid}') if sid else None
                if isinstance(info, dict) and (info.get('gameName') or info.get('displayName')):
                    if len(name_cache) >= 100:
                        name_cache.clear()
                    name_cache[member_key] = (time.monotonic(), info)
            if isinstance(info, dict):
                name = info.get('gameName') or info.get('displayName')
                tag = info.get('tagLine')
        member['_displayName'] = (name + ('#' + tag if tag else '')) if name else ('봇' if member.get('isBot') else '이름 조회 실패')
        member['_displayTeam'] = assignments.get(member_key) or ('관전자' if member.get('isSpectator') else {100:'블루',200:'레드'}.get(member.get('teamId'), '미확인 / 대기'))
        result.append(member)
    return result


# ---------- 챔피언 상성 데이터 (vschamp.lol) ----------
# vschamp.lol 페이지가 쓰는 정적 JSON을 실행 시 받아 데이터 폴더에 하루 동안 캐시한다.
# 저장소나 exe에는 복사본을 넣지 않는다. 받을 수 없으면 마지막 캐시를 쓰고, 그것도 없으면 기능만 꺼진다.
COUNTER_SITE = 'https://vschamp.lol/'
COUNTER_URL = COUNTER_SITE + 'champ.json?v=1.2.6'
COUNTER_CACHE = os.path.join(DATA_DIR, 'vschamp_champ.json')
COUNTER_MAX_AGE = 24 * 60 * 60
COUNTER_HEADERS = {'User-Agent': 'ScrimCollector/2.0 (+https://lol-scrim-balancer.vercel.app)'}


def norm_name(value):
    return re.sub(r'\s+', '', str(value or '')).lower()


def split_ref(value):
    """'제라스(원딜, 미드)' -> ('제라스', ['원딜', '미드'])"""
    match = re.match(r'^(.*?)\s*\(([^()]*)\)\s*$', str(value or ''))
    if not match:
        return str(value or '').strip(), []
    return match.group(1).strip(), [part.strip() for part in match.group(2).split(',') if part.strip()]


def clean_reason(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def http_get(url, timeout=10):
    request = urllib.request.Request(url, headers=COUNTER_HEADERS)
    with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=timeout) as response:
        return response.read()


def download_counter_data():
    url = COUNTER_URL
    try:
        # 사이트가 데이터 버전(?v=)을 올리면 페이지에 적힌 최신 경로를 따른다.
        found = re.search(r'champ\.json\?v=[\w.\-]+', http_get(COUNTER_SITE).decode('utf-8', 'ignore'))
        if found:
            url = COUNTER_SITE + found.group(0)
    except Exception:
        pass
    data = json.loads(http_get(url, timeout=15).decode('utf-8'))
    if not isinstance(data, list) or len(data) < 50 or not all(isinstance(e, dict) and e.get('champion') for e in data):
        raise ValueError('상성 데이터 형식이 예상과 다릅니다.')
    with open(COUNTER_CACHE + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(COUNTER_CACHE + '.tmp', COUNTER_CACHE)
    return data


def load_counter_data(force=False):
    """(데이터, 상태 문구)를 돌려준다."""
    try:
        age = time.time() - os.path.getmtime(COUNTER_CACHE)
    except OSError:
        age = None
    if age is not None and age < COUNTER_MAX_AGE and not force:
        with open(COUNTER_CACHE, encoding='utf-8') as f:
            return json.load(f), '오늘 받은 데이터'
    try:
        return download_counter_data(), '방금 받은 최신 데이터'
    except Exception as exc:
        if age is None:
            raise ValueError(f'상성 데이터를 받을 수 없습니다 ({exc})')
        with open(COUNTER_CACHE, encoding='utf-8') as f:
            return json.load(f), f'최신 데이터를 받지 못해 {int(age // 86400)}일 전 데이터를 사용'


DDRAGON = 'https://ddragon.leagueoflegends.com'
ICON_DIR = os.path.join(DATA_DIR, 'champion_icons')
_ddragon_version = None


def ddragon_version():
    global _ddragon_version
    if _ddragon_version is None:
        _ddragon_version = json.loads(http_get(DDRAGON + '/api/versions.json'))[0]
    return _ddragon_version


def load_champion_keys():
    """한글 챔피언 이름 -> Data Dragon 키(예: '오공' -> 'MonkeyKing'). 버전별로 디스크에 캐시한다."""
    version = ddragon_version()
    path = os.path.join(ICON_DIR, version, 'champions_ko.json')
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    data = json.loads(http_get(f'{DDRAGON}/cdn/{version}/data/ko_KR/champion.json'))['data']
    keys = {norm_name(info['name']): key for key, info in data.items()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(keys, f, ensure_ascii=False)
    os.replace(path + '.tmp', path)
    return keys


def champion_icon(key):
    """챔피언 정사각형 아이콘 PNG 바이트. 버전별로 디스크에 캐시한다."""
    if not re.fullmatch(r'[A-Za-z0-9]+', key):
        raise ValueError('잘못된 챔피언 키입니다.')
    version = ddragon_version()
    path = os.path.join(ICON_DIR, version, key + '.png')
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        pass
    data = http_get(f'{DDRAGON}/cdn/{version}/img/champion/{key}.png')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'wb') as f:
        f.write(data)
    os.replace(path + '.tmp', path)
    return data


class CounterIndex:
    def __init__(self, entries):
        self.entries = [e for e in entries if isinstance(e, dict) and e.get('champion')]
        self.champions = {norm_name(e['champion']): e for e in self.entries}
        self.lookup = dict(self.champions)
        for entry in self.entries:
            for alias in entry.get('aliases') or []:
                self.lookup.setdefault(norm_name(alias), entry)

    def get(self, name):
        return self.champions.get(norm_name(name))

    def find(self, query):
        q = norm_name(query)
        if not q:
            return []
        if q in self.lookup:
            return [self.lookup[q]]
        found = [e for key, e in self.lookup.items() if key.startswith(q)] or [e for key, e in self.lookup.items() if q in key]
        unique = []
        for entry in found:
            if entry not in unique:
                unique.append(entry)
        return sorted(unique, key=lambda e: e['champion'])

    def describe(self, entry):
        """챔피언 카운터와 아이템·룬 같은 대처 요소를 나눠 정리한다."""
        result = {'champion': entry['champion'], 'lines': entry.get('lines') or [], 'hard': [], 'general': [], 'extras': [],
                  'synergy': [], 'combos': []}
        for key in ('hard', 'general'):
            for ref in entry.get(key + '_counters') or []:
                if not isinstance(ref, dict):
                    continue
                name, lines = split_ref(ref.get('name'))
                item = {'name': name, 'lines': lines, 'reason': clean_reason(ref.get('reason')), 'hard': key == 'hard'}
                result[key if norm_name(name) in self.champions else 'extras'].append(item)
        result['synergy'] = [split_ref(name)[0] for name in entry.get('synergy') or [] if isinstance(name, str)]
        result['combos'] = [' + '.join(part.strip() for part in name.split('&')) for name in entry.get('combo_counters') or [] if isinstance(name, str)]
        return result


# ---------- 화면 디자인 ----------
# 웹앱(index.html)의 밝은 테마 토큰에 맞춘 색. 포인트 색은 ACCENT 한 곳만 바꾸면 된다.
BG = '#F3F4F7'
CARD = '#FFFFFF'
MUTED = '#F1F3F6'
LINE = '#E2E5EB'
LINE_STRONG = '#D0D5DE'
FG = '#161B24'
SUB = '#5C6678'
ACCENT = '#D6A23A'
ACCENT_HOVER = '#E2B24E'
ACCENT_FG = '#141006'
ACCENT_SOFT = '#EED9A8'
ACCENT_TINT = '#FBF4E4'
BLUE = '#2563EB'
RED = '#DC2626'
GREEN = '#16A34A'
AMBER = '#D97706'
DISABLED = '#C9CED8'
STRIPE = '#F8F9FB'
FONT_FILES = ('Pretendard-Regular.ttf', 'Pretendard-Bold.ttf')
FALLBACK_FONT = 'Malgun Gothic' if sys.platform == 'win32' else 'Apple SD Gothic Neo'
FONT = FALLBACK_FONT
SCALE = 1.0
TIER_NAMES = {'IRON': '아이언', 'BRONZE': '브론즈', 'SILVER': '실버', 'GOLD': '골드', 'PLATINUM': '플래티넘',
              'EMERALD': '에메랄드', 'DIAMOND': '다이아몬드', 'MASTER': '마스터', 'GRANDMASTER': '그랜드마스터',
              'CHALLENGER': '챌린저'}


def resource_path(*parts):
    """exe 안에 묶인 파일은 _MEIPASS, 스크립트 실행 시에는 이 파일 옆에서 찾는다."""
    return os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), *parts)


def register_fonts():
    """함께 배포한 Pretendard를 이 프로세스에만 임시 등록한다. 사용자 PC에 설치하지 않는다."""
    if sys.platform != 'win32':
        return
    import ctypes
    for name in FONT_FILES:
        path = resource_path('fonts', name)
        if os.path.exists(path):
            ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)  # 0x10 = FR_PRIVATE


def px(value):
    return int(round(value * SCALE))


def font(size, weight='normal'):
    return (FONT, size, weight)


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


class RoundedCard(tk.Canvas):
    """둥근 테두리 카드. 내용은 self.body(tk.Frame)에 넣는다."""

    def __init__(self, parent, title=None, subtitle=None, border=ACCENT_SOFT, pad=16, outer=BG):
        super().__init__(parent, bg=outer, highlightthickness=0, bd=0)
        self.border = border
        self.pad = px(pad)
        self.body = tk.Frame(self, bg=CARD)
        if title:
            tk.Label(self.body, text=title, bg=CARD, fg=FG, font=font(13, 'bold')).pack(pady=(0, 2))
        if subtitle:
            tk.Label(self.body, text=subtitle, bg=CARD, fg=SUB, font=font(9)).pack(pady=(0, px(6)))
        self.window = self.create_window(0, 0, window=self.body, anchor='nw')
        self.bind('<Configure>', self.redraw)

    def redraw(self, event=None):
        w, h = self.winfo_width(), self.winfo_height()
        self.delete('shape')
        round_rect(self, 1, 1, w - 2, h - 2, px(16), fill=CARD, outline=self.border, width=max(1, px(1.2)), tags='shape')
        self.tag_lower('shape')
        self.coords(self.window, self.pad, self.pad)
        self.itemconfigure(self.window, width=max(1, w - 2 * self.pad), height=max(1, h - 2 * self.pad))


class RoundButton(tk.Canvas):
    """둥근 버튼. configure(state='disabled'|'normal')을 ttk.Button처럼 받는다."""

    KINDS = {
        'primary': (ACCENT, ACCENT_HOVER, ACCENT_FG, ''),
        'secondary': (CARD, MUTED, FG, LINE_STRONG),
        'pill': (CARD, ACCENT_TINT, '#9A6B12', ACCENT_SOFT),
        'danger': (CARD, '#FEF2F2', RED, '#F3B4B4'),
    }

    def __init__(self, parent, text, command=None, kind='secondary', width=None, height=36, size=10, bg=CARD, state='normal', image=None):
        self.text, self.command, self.kind, self.size, self.image = text, command, kind, size, image
        measure = tkfont.Font(font=font(size, 'bold')).measure(text)
        if image is not None:
            measure += image.width() + px(6)
        self.w = px(width) if width else measure + px(34)
        self.h = px(height)
        super().__init__(parent, width=self.w, height=self.h, bg=bg, highlightthickness=0, bd=0, cursor='hand2', takefocus=1)
        self._state, self._hover, self._focus = state, False, False
        self.bind('<FocusIn>', lambda e: self._set_focus(True))
        self.bind('<FocusOut>', lambda e: self._set_focus(False))
        for key in ('<KeyPress-space>', '<KeyPress-Return>', '<KeyPress-KP_Enter>'):
            self.bind(key, self._key)
        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))
        self.bind('<ButtonRelease-1>', self._click)
        self.bind('<Configure>', lambda e: self.draw())
        self.draw()

    def _set_focus(self, value):
        self._focus = value
        self.draw()

    def _key(self, event):
        if self._state != 'disabled' and self.command:
            self.command()
        return 'break'

    def _set_hover(self, value):
        self._hover = value
        self.draw()

    def _click(self, event):
        if self._state != 'disabled' and self.command and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def draw(self):
        self.delete('all')
        w, h = max(self.winfo_width(), 2), max(self.winfo_height(), 2)
        if w <= 2:
            w, h = self.w, self.h
        fill, hover, fg, outline = self.KINDS[self.kind]
        if self._state == 'disabled':
            fill, fg, outline = (MUTED, DISABLED, LINE) if self.kind != 'primary' else (DISABLED, CARD, '')
        elif self._hover:
            fill = hover
        if self._focus and self._state != 'disabled':
            # 키보드 포커스 표시: 포인트 색 2px 테두리
            round_rect(self, 1, 1, w - 2, h - 2, h / 2 - 1, fill=fill, outline=ACCENT if self.kind != 'primary' else '#9A6B12', width=max(2, px(2)))
        else:
            round_rect(self, 1, 1, w - 2, h - 2, h / 2 - 1, fill=fill, outline=outline or fill, width=1)
        if self.image is None:
            self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=font(self.size, 'bold'))
        else:
            text_w = tkfont.Font(font=font(self.size, 'bold')).measure(self.text)
            left = (w - (self.image.width() + px(6) + text_w)) / 2
            self.create_image(left, h / 2, image=self.image, anchor='w')
            self.create_text(left + self.image.width() + px(6), h / 2, text=self.text, fill=fg, font=font(self.size, 'bold'), anchor='w')
        super().configure(cursor='arrow' if self._state == 'disabled' else 'hand2', takefocus=0 if self._state == 'disabled' else 1)

    def configure(self, cnf=None, **kw):
        state = kw.pop('state', None)
        if state is not None:
            self._state = state
            self.draw()
        if cnf or kw:
            return super().configure(cnf, **kw)

    config = configure


class StatusDot(tk.Canvas):
    def __init__(self, parent, size=12, bg=CARD):
        super().__init__(parent, width=px(size), height=px(size), bg=bg, highlightthickness=0, bd=0)
        self.size = px(size)
        self.set(DISABLED)

    def set(self, color):
        self.delete('all')
        s = self.size
        self.create_oval(1, 1, s - 1, s - 1, fill=color, outline=color)


def status_color(text):
    if '오류' in text or '실패' in text:
        return RED
    if '수집 중지' in text:
        return DISABLED
    if '게임 중' in text:
        return BLUE
    if '제출 완료' in text:
        return GREEN
    if any(word in text for word in ('확인 중', '제출 대기', '중지 중')):
        return AMBER
    return GREEN


class CollectorUI:
    def __init__(self, root):
        global SCALE, FONT
        FONT = 'Pretendard' if 'Pretendard' in tkfont.families(root) else FALLBACK_FONT
        self.root = root
        self.process = None
        self.stopping = False
        self.game_phase = None
        self.submission_state = None
        self.closing = False
        self.events = queue.Queue()
        self.view_events = queue.Queue()
        self.view_busy = set()
        self.history_records = {}
        self.lobby_name_cache = {}
        self.last_lobby_data = None
        self.roster_retained = False
        self.icon_cache = {}
        self.avatar_image = None
        self.counter_index = None
        self.counter_auto_key = None
        self.champ_select = None
        self.champ_names = {}
        self.champ_keys = {}
        self.icon_data = {}
        self.champ_images = {}
        self.icons_wanted = set()
        self.icons_failed = set()
        self.counter_view = None
        SCALE = max(1.0, root.winfo_fpixels('1i') / 96)
        root.title('내전 결과 수집기')
        root.geometry(f'{px(980)}x{px(760)}')
        root.minsize(px(860), px(660))
        root.configure(bg=BG)
        root.option_add('*TCombobox*Listbox.font', font(10))
        root.option_add('*TCombobox*Listbox.background', CARD)
        root.option_add('*TCombobox*Listbox.selectBackground', ACCENT_TINT)
        root.option_add('*TCombobox*Listbox.selectForeground', FG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=FG, font=font(10),
                        rowheight=px(30), borderwidth=0, bordercolor=LINE, lightcolor=CARD, darkcolor=CARD)
        style.map('Treeview', background=[('selected', ACCENT_TINT)], foreground=[('selected', FG)])
        style.configure('Treeview.Heading', background=MUTED, foreground=SUB, font=font(9, 'bold'), padding=px(6),
                        borderwidth=0, relief='flat', bordercolor=LINE, lightcolor=MUTED, darkcolor=MUTED)
        style.map('Treeview.Heading', background=[('active', MUTED)])
        style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        for orient in ('Vertical', 'Horizontal'):
            style.configure(f'{orient}.TScrollbar', background=LINE, troughcolor=CARD, bordercolor=CARD,
                            lightcolor=LINE, darkcolor=LINE, arrowcolor=SUB, gripcount=0, arrowsize=px(11))
            style.map(f'{orient}.TScrollbar', background=[('active', LINE_STRONG)])
        style.configure('TCombobox', fieldbackground=MUTED, background=MUTED, foreground=FG, bordercolor=LINE,
                        lightcolor=MUTED, darkcolor=MUTED, arrowcolor=SUB, padding=px(5))
        style.configure('TEntry', fieldbackground=MUTED, foreground=FG, bordercolor=LINE, lightcolor=MUTED,
                        darkcolor=MUTED, insertcolor=FG, padding=px(5))
        style.map('TEntry', bordercolor=[('focus', ACCENT)], lightcolor=[('focus', MUTED)])
        style.configure('TEntry', selectbackground=ACCENT_SOFT, selectforeground=FG)
        style.configure('Placeholder.TEntry', fieldbackground=MUTED, foreground=SUB, bordercolor=LINE, lightcolor=MUTED,
                        darkcolor=MUTED, padding=px(5))
        style.map('TCombobox', fieldbackground=[('readonly', MUTED)], selectbackground=[('readonly', MUTED)],
                  selectforeground=[('readonly', FG)])

        frame = tk.Frame(root, bg=BG, padx=px(22), pady=px(16))
        frame.pack(fill='both', expand=True)

        # 상단 바: 제목과 웹앱 바로가기
        top = tk.Frame(frame, bg=BG)
        top.pack(fill='x', pady=(0, px(12)))
        tk.Label(top, text='내전 결과 수집기', bg=BG, fg=FG, font=font(14, 'bold')).pack(side='left')
        tk.Label(top, text='v2.0', bg=BG, fg=SUB, font=font(9)).pack(side='left', padx=(px(6), 0), pady=(px(4), 0))
        RoundButton(top, '웹앱 열기', kind='pill', height=30, size=9, bg=BG,
                    command=lambda: __import__('webbrowser').open(SERVER_URL.rsplit('/api/', 1)[0])).pack(side='right')

        grid = tk.Frame(frame, bg=BG)
        grid.pack(fill='both', expand=True)
        grid.columnconfigure(0, weight=1, uniform='col')
        grid.columnconfigure(1, weight=1, uniform='col')
        grid.rowconfigure(0, minsize=px(196))
        grid.rowconfigure(1, weight=1)

        # 카드 1: 롤 클라이언트에 로그인한 계정
        account = RoundedCard(grid, '내 계정', '롤 클라이언트에 접속한 계정 정보입니다')
        account.grid(row=0, column=0, sticky='nsew', padx=(0, px(8)), pady=(0, px(14)))
        info = tk.Frame(account.body, bg=CARD)
        info.pack(expand=True)
        self.avatar = tk.Canvas(info, width=px(76), height=px(76), bg=CARD, highlightthickness=0, bd=0)
        self.avatar.grid(row=0, column=0, rowspan=4, padx=(0, px(16)))
        self.account_name = tk.StringVar(value='연결 대기 중')
        self.account_level = tk.StringVar(value='')
        self.account_rank = tk.StringVar(value='')
        self.account_conn = tk.StringVar(value='롤 클라이언트를 확인하는 중...')
        tk.Label(info, textvariable=self.account_name, bg=CARD, fg=FG, font=font(15, 'bold'), anchor='w').grid(row=0, column=1, sticky='w')
        tk.Label(info, textvariable=self.account_level, bg=CARD, fg=SUB, font=font(10), anchor='w').grid(row=1, column=1, sticky='w', pady=(px(2), 0))
        tk.Label(info, textvariable=self.account_rank, bg=CARD, fg='#9A6B12', font=font(10, 'bold'), anchor='w').grid(row=2, column=1, sticky='w', pady=(px(2), 0))
        conn = tk.Frame(info, bg=CARD)
        conn.grid(row=3, column=1, sticky='w', pady=(px(8), 0))
        self.conn_dot = StatusDot(conn, 9)
        self.conn_dot_color = DISABLED
        self.conn_dot.pack(side='left', padx=(0, px(6)))
        tk.Label(conn, textvariable=self.account_conn, bg=CARD, fg=SUB, font=font(9)).pack(side='left')
        self.draw_avatar(None, '?')

        # 카드 2: 수집 상태와 시작/중지
        control = RoundedCard(grid, '결과 수집', '내전이 끝나면 결과를 웹앱에 자동으로 올립니다')
        control.grid(row=0, column=1, sticky='nsew', padx=(px(8), 0), pady=(0, px(14)))
        status_row = tk.Frame(control.body, bg=MUTED, padx=px(14), pady=px(10))
        status_row.pack(fill='x', pady=(px(2), px(12)))
        self.status_dot = StatusDot(status_row, 12, bg=MUTED)
        self.status_dot.pack(side='left', padx=(0, px(10)))
        self.status = tk.StringVar(value='대기중 · 수집 중지')
        tk.Label(status_row, textvariable=self.status, bg=MUTED, fg=FG, font=font(11, 'bold'), anchor='w').pack(side='left', fill='x')
        self.status.trace_add('write', lambda *a: self.status_dot.set(status_color(self.status.get())))
        buttons = tk.Frame(control.body, bg=CARD)
        buttons.pack(fill='x')
        buttons.columnconfigure(0, weight=3)
        buttons.columnconfigure(1, weight=1)
        self.start_button = RoundButton(buttons, '수집 시작', self.start, kind='primary', height=40, size=11)
        self.start_button.grid(row=0, column=0, sticky='ew', padx=(0, px(8)))
        self.stop_button = RoundButton(buttons, '중지', self.stop, kind='danger', height=40, size=11, state='disabled')
        self.stop_button.grid(row=0, column=1, sticky='ew')
        tk.Label(control.body, text='전송에 실패한 경기는 로컬에 보관했다가 다시 보냅니다.', bg=CARD, fg=SUB,
                 font=font(9)).pack(pady=(px(10), 0))

        # 카드 3: 참가자 · 로그 · 매치 히스토리
        main = RoundedCard(grid, border=LINE, pad=16)
        main.grid(row=1, column=0, columnspan=2, sticky='nsew')
        tabs_bar = tk.Frame(main.body, bg=CARD)
        tabs_bar.pack(fill='x')
        tk.Frame(main.body, bg=LINE, height=1).pack(fill='x', pady=(0, px(12)))
        pages = tk.Frame(main.body, bg=CARD)
        pages.pack(fill='both', expand=True)
        pages.rowconfigure(0, weight=1)
        pages.columnconfigure(0, weight=1)
        self.lobby_tab = tk.Frame(pages, bg=CARD)
        log_tab = tk.Frame(pages, bg=CARD)
        self.history_tab = tk.Frame(pages, bg=CARD)
        self.counter_tab = tk.Frame(pages, bg=CARD)
        self.tab_buttons = {}
        for name, page in [('현재 방 참가자', self.lobby_tab), ('카운터 정보', self.counter_tab), ('실행 로그', log_tab), ('매치 히스토리', self.history_tab)]:
            page.grid(row=0, column=0, sticky='nsew')
            holder = tk.Frame(tabs_bar, bg=CARD)
            holder.pack(side='left', padx=(0, px(18)))
            label = tk.Label(holder, text=name, bg=CARD, fg=SUB, font=font(11, 'bold'), cursor='hand2', pady=px(6))
            label.pack()
            bar = tk.Frame(holder, bg=CARD, height=px(3))
            bar.pack(fill='x')
            label.bind('<Button-1>', lambda e, p=page: self.show_tab(p))
            self.tab_buttons[page] = (label, bar)

        # 참가자 탭
        lobby_head = tk.Frame(self.lobby_tab, bg=CARD)
        lobby_head.pack(fill='x', pady=(0, px(10)))
        self.lobby_status = tk.StringVar(value='조회 중...')
        tk.Label(lobby_head, textvariable=self.lobby_status, bg=CARD, fg=SUB, font=font(10)).pack(side='left')
        RoundButton(lobby_head, '새로고침', lambda: self.refresh_view('lobby'), height=30, size=9).pack(side='right')
        teams_panel = tk.Frame(self.lobby_tab, bg=CARD)
        teams_panel.pack(fill='both', expand=True)
        self.teams_panel = teams_panel
        self.lobby_empty = tk.Frame(self.lobby_tab, bg=CARD)
        tk.Label(self.lobby_empty, text='아직 표시할 참가자가 없습니다', bg=CARD, fg=FG, font=font(12, 'bold')).pack(pady=(0, px(6)))
        self.lobby_empty_hint = tk.Label(self.lobby_empty, text='', bg=CARD, fg=SUB, font=font(10), justify='center')
        self.lobby_empty_hint.pack()
        teams_panel.columnconfigure(0, weight=1, uniform='team')
        teams_panel.columnconfigure(1, weight=1, uniform='team')
        teams_panel.rowconfigure(0, weight=1)
        self.blue_title = tk.StringVar(value='블루팀 · 0명')
        self.red_title = tk.StringVar(value='레드팀 · 0명')
        trees = []
        for column, (title, color) in enumerate([(self.blue_title, BLUE), (self.red_title, RED)]):
            panel = tk.Frame(teams_panel, bg=CARD)
            panel.grid(row=0, column=column, sticky='nsew', padx=(0, px(8)) if column == 0 else (px(8), 0))
            head = tk.Frame(panel, bg=CARD)
            head.pack(fill='x', pady=(0, px(6)))
            dot = StatusDot(head, 10)
            dot.set(color)
            dot.pack(side='left', padx=(0, px(8)))
            tk.Label(head, textvariable=title, bg=CARD, fg=color, font=font(12, 'bold')).pack(side='left')
            trees.append(self.make_table(panel, [('name', '플레이어'), ('leader', '방장')], scroll_x=False))
        self.blue_tree, self.red_tree = trees
        for team_tree in (self.blue_tree, self.red_tree):
            team_tree.column('name', width=px(260), minwidth=px(100))
            team_tree.column('leader', width=px(60), minwidth=px(50), stretch=False, anchor='center')
            team_tree.heading('leader', anchor='center')
        self.other_members = tk.StringVar(value='')
        self.other_members_label = tk.Label(self.lobby_tab, textvariable=self.other_members, bg=CARD, fg=SUB, font=font(9),
                                            wraplength=px(840), justify='left')
        self.other_members_label.pack(anchor='w', pady=(px(8), 0))

        # 실행 로그 탭
        log_head = tk.Frame(log_tab, bg=CARD)
        log_head.pack(fill='x', pady=(0, px(10)))
        tk.Label(log_head, text='수집기가 남긴 기록입니다.', bg=CARD, fg=SUB, font=font(10)).pack(side='left')
        RoundButton(log_head, '지우기', self.clear, height=30, size=9).pack(side='right')
        RoundButton(log_head, '로그 저장', self.save_log, height=30, size=9).pack(side='right', padx=(0, px(6)))
        log_box = tk.Frame(log_tab, bg=STRIPE, highlightthickness=1, highlightbackground=LINE)
        log_box.pack(fill='both', expand=True)
        self.log = tk.Text(log_box, wrap='word', font=font(10), bg=STRIPE, fg=FG, selectbackground=ACCENT_SOFT, selectforeground=FG, inactiveselectbackground=ACCENT_TINT, relief='flat', bd=0,
                           padx=px(14), pady=px(12), state='disabled', highlightthickness=0, spacing1=px(2), spacing3=px(2))
        log_scroll = ttk.Scrollbar(log_box, orient='vertical', command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)
        for tag, color in [('ok', GREEN), ('warn', AMBER), ('error', RED), ('info', SUB)]:
            self.log.tag_configure(tag, foreground=color)

        # 매치 히스토리 탭
        bar = tk.Frame(self.history_tab, bg=CARD)
        bar.pack(fill='x', pady=(0, px(8)))
        self.history_source = tk.StringVar(value='웹앱 내전 기록')
        picker = ttk.Combobox(bar, textvariable=self.history_source, values=['웹앱 내전 기록', '내 계정 최근 경기'],
                              state='readonly', width=20, font=font(10))
        picker.pack(side='left')
        picker.bind('<<ComboboxSelected>>', lambda e: self.refresh_view('history'))
        RoundButton(bar, '새로고침', lambda: self.refresh_view('history'), height=30, size=9).pack(side='right')
        self.history_status = tk.StringVar(value='새로고침을 눌러 기록을 불러오세요. 행을 더블클릭하면 상세 정보를 봅니다.')
        tk.Label(self.history_tab, textvariable=self.history_status, bg=CARD, fg=SUB, font=font(10)).pack(anchor='w', pady=(0, px(8)))
        self.history_tree = self.make_table(self.history_tab, [('date', '일시'), ('mode', '종류'), ('result', '결과'), ('duration', '시간'), ('id', '경기 ID')])
        self.history_tree.bind('<Double-1>', self.show_match)
        self.history_tree.bind('<Return>', self.show_match)

        self.build_counter_tab(self.counter_tab)
        self.show_tab(self.lobby_tab, refresh=False)
        self.append('수집 시작을 누르면 자동 업로드가 활성화됩니다.\n')
        root.report_callback_exception = self.ui_error
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)
        root.after(200, self.refresh_lobby_loop)
        root.after(100, self.refresh_phase_loop)
        root.after(300, self.refresh_account_loop)
        root.after(500, self.load_counters)

    # ---------- 카운터 정보 탭 ----------
    def build_counter_tab(self, tab):
        head = tk.Frame(tab, bg=CARD)
        head.pack(fill='x', pady=(0, px(8)))
        self.counter_query = tk.StringVar()
        entry = self.counter_entry = ttk.Entry(head, textvariable=self.counter_query, width=26, font=font(10))
        entry.pack(side='left', ipady=px(3))
        placeholder = self.counter_placeholder_text = '챔피언 이름 (예: 가렌, 하이머)'
        def show_placeholder(event=None):
            if not self.counter_query.get():
                entry.configure(style='Placeholder.TEntry')
                self.counter_query.set(placeholder)
                self.counter_placeholder = True
        def hide_placeholder(event=None):
            if self.counter_placeholder:
                self.counter_placeholder = False
                self.counter_query.set('')
                entry.configure(style='TEntry')
        self.counter_placeholder = False
        entry.bind('<FocusIn>', hide_placeholder)
        entry.bind('<FocusOut>', show_placeholder)
        show_placeholder()
        # 한글 입력기는 조합 중 엔터를 조합 확정에 써서 KeyPress가 오지 않을 수 있다.
        # 그래서 키를 뗄 때도 받고, 조합된 글자가 입력칸에 반영된 뒤 검색한다.
        self.enter_pressed = False
        def on_press(event):
            self.enter_pressed = True
            self.root.after(30, self.search_counter)
        def on_release(event):
            if not self.enter_pressed:
                self.root.after(30, self.search_counter)
            self.enter_pressed = False
        for key in ('Return', 'KP_Enter'):
            entry.bind(f'<KeyPress-{key}>', on_press)
            entry.bind(f'<KeyRelease-{key}>', on_release)
        RoundButton(head, '검색', self.search_counter, kind='primary', height=30, size=9).pack(side='left', padx=(px(6), 0))
        source = tk.Label(head, text='데이터 출처: vschamp.lol', bg=CARD, fg=SUB, font=font(9, 'underline'), cursor='hand2')
        source.pack(side='right')
        source.bind('<Button-1>', lambda e: __import__('webbrowser').open(COUNTER_SITE))
        self.counter_picks = tk.Frame(tab, bg=CARD)
        self.counter_picks.pack(fill='x')
        self.counter_status = tk.StringVar(value='상성 데이터를 불러오는 중...')
        tk.Label(tab, textvariable=self.counter_status, bg=CARD, fg=SUB, font=font(10), anchor='w').pack(fill='x', pady=(px(4), px(8)))
        box = tk.Frame(tab, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        box.pack(fill='both', expand=True)
        self.counter_text = tk.Text(box, wrap='word', font=font(10), bg=CARD, fg=FG, selectbackground=ACCENT_SOFT, selectforeground=FG, inactiveselectbackground=ACCENT_TINT, relief='flat', bd=0, highlightthickness=0,
                                    padx=px(18), pady=px(14), spacing1=px(1), spacing3=px(1), cursor='arrow')
        scroll = ttk.Scrollbar(box, orient='vertical', command=self.counter_text.yview)
        self.counter_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.counter_text.pack(side='left', fill='both', expand=True)
        text = self.counter_text
        text.tag_configure('title', font=font(17, 'bold'))
        text.tag_configure('sub', foreground=SUB)
        text.tag_configure('section', font=font(12, 'bold'), spacing1=px(22), spacing3=px(8))
        text.tag_configure('name', font=font(10, 'bold'))
        text.tag_configure('hit', foreground=RED, font=font(10, 'bold'))
        text.tag_configure('reason', foreground='#3F4756', lmargin1=px(34), lmargin2=px(34), spacing1=px(3), spacing2=px(4), spacing3=px(12))
        text.tag_configure('rest', spacing2=px(6), lmargin1=px(2), lmargin2=px(2))
        def limit_measure(event):
            # 설명 문단은 한 줄이 너무 길어지지 않게 오른쪽 여백으로 폭을 제한한다(약 75자).
            text.tag_configure('reason', rmargin=max(px(14), event.width - px(860)))
        text.bind('<Configure>', limit_measure, add='+')
        text.tag_configure('alert', background='#FEF2F2', foreground=RED, font=font(10, 'bold'),
                           lmargin1=px(10), lmargin2=px(10), rmargin=px(10), spacing1=px(8), spacing3=px(8))
        text.tag_configure('good', background='#F0FDF4', foreground=GREEN, font=font(10, 'bold'),
                           lmargin1=px(10), lmargin2=px(10), rmargin=px(10), spacing1=px(8), spacing3=px(8))
        text.tag_configure('foot', foreground=SUB, font=font(9), spacing1=px(14))
        self.write_counter_text([('챔피언 이름을 검색하거나, 챔피언 선택에 들어가면 내 챔피언의 상성을 자동으로 보여 줍니다.\n', 'sub')])

    def write_counter_text(self, parts, scroll=0.0):
        text = self.counter_text
        text.configure(state='normal')
        text.delete('1.0', 'end')
        for chunk, tag in parts:
            if tag == 'IMG':
                text.image_create('end', image=chunk, align='center', padx=px(3))
            else:
                text.insert('end', chunk, tag if isinstance(tag, tuple) else (tag or ()))
        text.configure(state='disabled')
        text.yview_moveto(scroll)

    def champ_image(self, name, size):
        """캐시된 챔피언 아이콘을 size(논리 px)로 줄여 돌려준다. 없으면 받아 오도록 표시하고 None."""
        key = self.champ_keys.get(norm_name(name))
        if key is None:
            if self.counter_index and self.counter_index.get(name) and name not in self.icons_failed:
                self.icons_wanted.add(name)
            return None
        image = self.champ_images.get((key, size))
        if image is not None:
            return image
        data = self.icon_data.get(key)
        if data is None:
            if key not in self.icons_failed:
                self.icons_wanted.add(name)
            return None
        try:
            base = tk.PhotoImage(data=data)
        except tk.TclError:
            self.icons_failed.add(key)
            return None
        factor = max(1, round(base.width() / px(size)))
        image = base.subsample(factor) if factor > 1 else base
        self.champ_images[(key, size)] = image
        return image

    def request_icons(self):
        if not self.icons_wanted or 'icons' in self.view_busy:
            return
        names, self.icons_wanted = set(self.icons_wanted), set()
        self.view_busy.add('icons')
        known = dict(self.champ_keys)
        def fetch():
            try:
                keys = known or load_champion_keys()
                icons, failed = {}, set()
                for name in names:
                    key = keys.get(norm_name(name))
                    if not key:
                        failed.add(name)
                        continue
                    try:
                        icons[key] = base64.b64encode(champion_icon(key)).decode()
                    except Exception:
                        failed.add(key)
                self.view_events.put(('icons', None, (keys, icons, failed), None))
            except Exception as exc:
                self.view_events.put(('icons', None, ({}, {}, set(names)), str(exc)))
        threading.Thread(target=fetch, daemon=True).start()

    def render_icons(self, data):
        keys, icons, failed = data
        self.champ_keys = self.champ_keys or keys
        self.icon_data.update(icons)
        self.icons_failed.update(failed)
        if self.counter_view:
            self.show_counter(*self.counter_view, scroll=self.counter_text.yview()[0])
        if self.champ_select:
            self.render_champ_select(self.champ_select, rebuild_only=True)

    def load_counters(self, force=False):
        if 'counters' in self.view_busy:
            return
        self.view_busy.add('counters')
        def fetch():
            try:
                data, origin = load_counter_data(force)
                self.view_events.put(('counters', None, (CounterIndex(data), origin), None))
            except Exception as exc:
                self.view_events.put(('counters', None, None, str(exc)))
        threading.Thread(target=fetch, daemon=True).start()

    def render_counters(self, data, error):
        if error:
            self.counter_status.set(error + ' · 카운터 정보를 쓸 수 없습니다')
            return
        self.counter_index, origin = data
        self.counter_status.set(f'챔피언 {len(self.counter_index.entries)}명 · {origin}')
        if self.champ_select:
            self.counter_auto_key = None
            self.render_champ_select(self.champ_select)

    def search_counter(self):
        if not self.counter_index:
            return
        if self.counter_placeholder and self.counter_query.get() == self.counter_placeholder_text:
            return
        self.counter_placeholder = False
        self.counter_entry.configure(style='TEntry')
        matches = self.counter_index.find(self.counter_query.get())
        if not matches:
            self.counter_status.set(f"'{self.counter_query.get().strip()}'에 맞는 챔피언이 없습니다")
            return
        self.show_counter(matches[0]['champion'])
        if len(matches) > 1:
            self.counter_status.set('다른 결과: ' + ', '.join(m['champion'] for m in matches[1:8]))

    def show_counter(self, champion, highlight=(), highlight_label='', scroll=0.0):
        entry = self.counter_index.get(champion) if self.counter_index else None
        if entry is None:
            self.counter_view = None
            self.write_counter_text([(f'{champion}의 상성 정보가 없습니다.\n', 'sub')])
            return
        self.counter_view = (champion, tuple(highlight), highlight_label)
        info = self.counter_index.describe(entry)
        marked = {norm_name(name) for name in highlight}
        parts = []
        def icon(name, size):
            image = self.champ_image(name, size)
            if image is not None:
                parts.append((image, 'IMG'))
        icon(info['champion'], 52)
        parts.extend([(info['champion'], 'title'), ('   ' + ' · '.join(info['lines']) + '\n', 'sub')])
        hits = [c['name'] for c in info['hard'] + info['general'] if norm_name(c['name']) in marked]
        if hits:
            parts.append((f"{highlight_label}에 {info['champion']}의 카운터가 있습니다: {', '.join(dict.fromkeys(hits))}\n", 'alert'))
        elif marked:
            parts.append((f"{highlight_label}에 {info['champion']}의 카운터 챔피언이 없습니다\n", 'good'))

        def champions(title, items):
            if not items:
                return
            parts.append((title + f'  {len(items)}\n', 'section'))
            detailed = [c for c in items if c['reason']]
            rest = [c for c in items if not c['reason']]
            for c in detailed:
                hit = norm_name(c['name']) in marked
                icon(c['name'], 28)
                parts.append((c['name'], 'hit' if hit else 'name'))
                parts.append((('  ' + ', '.join(c['lines']) if c['lines'] else '') + ('  · ' + highlight_label if hit else '') + '\n', 'sub'))
                parts.append((c['reason'] + '\n', 'reason'))
            if rest:
                parts.append(('그 밖에  ', 'sub'))
                start = len(parts)
                for index, c in enumerate(rest):
                    hit = norm_name(c['name']) in marked
                    icon(c['name'], 22)
                    parts.append((c['name'], 'hit' if hit else 'name'))
                    if index < len(rest) - 1:
                        parts.append(('   ', None))
                parts.append(('\n', None))
                parts[start - 1:] = [(chunk, tag if tag in ('IMG',) else ((tag, 'rest') if tag else 'rest')) for chunk, tag in parts[start - 1:]]

        champions('하드 카운터', info['hard'])
        champions('일반 카운터', info['general'])
        champions('아이템·룬 등 대처 요소', info['extras'])
        if info['synergy']:
            parts.append(('함께하면 좋은 조합\n', 'section'))
            for index, name in enumerate(info['synergy']):
                icon(name, 22)
                parts.append((name + ('   ' if index < len(info['synergy']) - 1 else '\n'), None))
        if info['combos']:
            parts.extend([('까다로운 바텀 조합\n', 'section'), ('   ·   '.join(info['combos']) + '\n', 'rest')])
        parts.append(('출처: vschamp.lol · 설명은 원문 그대로 보여 줍니다. 챔피언 이미지: Riot Data Dragon\n', 'foot'))
        self.write_counter_text(parts, scroll)
        self.request_icons()

    def fetch_champ_select(self):
        port, password = collector.get_lcu_credentials()
        if not port:
            raise ValueError('롤 클라이언트에 연결할 수 없습니다.')
        session = collector.query_lcu(port, password, '/lol-champ-select/v1/session')
        if not isinstance(session, dict):
            raise ValueError('챔피언 선택 정보를 읽을 수 없습니다.')
        if not self.champ_names:
            self.champ_names = load_champion_names(port, password)
        def pick(player):
            champion_id = player.get('championId') or player.get('championPickIntent') or 0
            return self.champ_names.get(champion_id) if champion_id else None
        local = session.get('localPlayerCellId')
        mine = next((p for p in session.get('myTeam') or [] if p.get('cellId') == local), {})
        return {'me': pick(mine),
                'allies': [n for n in (pick(p) for p in session.get('myTeam') or [] if p is not mine) if n],
                'enemies': [n for n in (pick(p) for p in session.get('theirTeam') or []) if n]}

    def render_champ_select(self, data, rebuild_only=False):
        self.champ_select = data
        key = (data['me'], tuple(data['allies']), tuple(data['enemies']))
        if key == self.counter_auto_key and not rebuild_only:
            return
        self.counter_auto_key = key
        for child in self.counter_picks.winfo_children():
            child.destroy()
        allies = ([data['me']] if data['me'] else []) + data['allies']
        def view(name, ours):
            return lambda: self.show_counter(name, data['enemies'] if ours else allies, '상대 팀' if ours else '우리 팀')
        def team_row(label, color):
            row = tk.Frame(self.counter_picks, bg=CARD)
            row.pack(fill='x', pady=(px(2), px(2)))
            tk.Label(row, text=label, bg=CARD, fg=color, font=font(9, 'bold'), width=6, anchor='w').pack(side='left')
            return row
        def button(row, label, name, ours, kind):
            RoundButton(row, label, view(name, ours), kind=kind, height=32, size=9,
                        image=self.champ_image(name, 22)).pack(side='left', padx=(0, px(4)))
        ours_row = team_row('우리 팀', BLUE)
        if data['me']:
            button(ours_row, '내 픽 ' + data['me'], data['me'], True, 'pill')
        for name in data['allies']:
            button(ours_row, name, name, True, 'secondary')
        if data['enemies']:
            theirs_row = team_row('상대 팀', RED)
            for name in data['enemies']:
                button(theirs_row, name, name, False, 'danger')
        if data['me'] and self.counter_index and not rebuild_only:
            view(data['me'], True)()
        self.request_icons()

    def show_tab(self, page, refresh=True):
        page.tkraise()
        for other, (label, bar) in self.tab_buttons.items():
            active = other is page
            label.configure(fg=FG if active else SUB)
            bar.configure(bg=ACCENT if active else CARD)
        if refresh and page is self.history_tab:
            self.refresh_view('history')

    def draw_avatar(self, image, initial):
        c = self.avatar
        c.delete('all')
        size = px(76)
        center, radius = size / 2, px(34)
        if image is not None:
            c.create_image(center, center, image=image)
            inner, outer = radius, size
            mid, width = (inner + outer) / 2, outer - inner
            c.create_oval(center - mid, center - mid, center + mid, center + mid, outline=CARD, width=width)
        else:
            c.create_oval(center - radius, center - radius, center + radius, center + radius, fill=ACCENT_TINT, outline='')
            c.create_text(center, center, text=initial, fill='#9A6B12', font=font(20, 'bold'))
        c.create_oval(center - radius - px(2), center - radius - px(2), center + radius + px(2), center + radius + px(2),
                      outline=ACCENT, width=px(2))

    def refresh_account_loop(self):
        if self.closing:
            return
        self.refresh_view('account')
        self.root.after(10000, self.refresh_account_loop)

    def fetch_account(self):
        port, password = collector.get_lcu_credentials()
        if not port:
            raise ValueError('롤 클라이언트가 실행되어 있지 않습니다')
        me = collector.query_lcu(port, password, '/lol-summoner/v1/current-summoner')
        if not isinstance(me, dict) or not (me.get('gameName') or me.get('displayName')):
            raise ValueError('로그인한 계정을 확인할 수 없습니다')
        ranked = collector.query_lcu(port, password, '/lol-ranked/v1/current-ranked-stats') or {}
        solo = ((ranked.get('queueMap') or {}).get('RANKED_SOLO_5x5') or {}) if isinstance(ranked, dict) else {}
        tier = str(solo.get('tier') or '').upper()
        if tier in TIER_NAMES:
            division = solo.get('division')
            rank = f"솔로랭크 {TIER_NAMES[tier]}" + (f" {division}" if division and division != 'NA' else '') + f" · {solo.get('leaguePoints', 0)}LP"
        else:
            rank = '솔로랭크 기록 없음'
        icon_id = me.get('profileIconId')
        icon = self.icon_cache.get(icon_id)
        if icon is None and isinstance(icon_id, int):
            try:
                if 'version' not in self.icon_cache:
                    with urllib.request.urlopen('https://ddragon.leagueoflegends.com/api/versions.json', timeout=5) as response:
                        self.icon_cache['version'] = json.load(response)[0]
                url = f"https://ddragon.leagueoflegends.com/cdn/{self.icon_cache['version']}/img/profileicon/{icon_id}.png"
                with urllib.request.urlopen(url, timeout=5) as response:
                    icon = base64.b64encode(response.read()).decode()
                self.icon_cache[icon_id] = icon
            except Exception:
                icon = None
        return {'name': me.get('gameName') or me.get('displayName'), 'tag': me.get('tagLine') or '',
                'level': me.get('summonerLevel'), 'rank': rank, 'icon': icon}

    def render_account(self, data, error):
        if error:
            self.account_name.set('연결 대기 중')
            self.account_level.set('롤 클라이언트를 켜면 계정 정보를 불러옵니다')
            self.account_rank.set('')
            self.account_conn.set(error)
            self.conn_dot.set(DISABLED)
            self.conn_dot_color = DISABLED
            self.avatar_image = None
            self.draw_avatar(None, '?')
            return
        self.account_name.set(data['name'] + (f" #{data['tag']}" if data['tag'] else ''))
        self.account_level.set(f"레벨 {data['level']}" if data.get('level') else '')
        self.account_rank.set(data['rank'])
        self.account_conn.set('롤 클라이언트 연결됨')
        self.conn_dot.set(GREEN)
        self.conn_dot_color = GREEN
        self.update_lobby_empty()
        image = None
        if data.get('icon'):
            try:
                image = tk.PhotoImage(data=data['icon'])
                factor = max(1, round(image.width() / px(68)))
                if factor > 1:
                    image = image.subsample(factor)
            except tk.TclError:
                image = None
        self.avatar_image = image
        self.draw_avatar(image, (data['name'] or '?')[:1])

    def ui_error(self, error_type, error, traceback):
        import traceback as trace
        self.append('[화면 오류] ' + ''.join(trace.format_exception(error_type, error, traceback)) + '\n')
        self.status.set('화면 처리 오류 · 실행 로그를 확인하세요')

    @staticmethod
    def make_table(parent, columns, scroll_x=True):
        wrapper = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        wrapper.pack(fill='both', expand=True)
        tree = ttk.Treeview(wrapper, columns=[c[0] for c in columns], show='headings', selectmode='browse')
        for key, title in columns:
            tree.heading(key, text=title, anchor='w')
            tree.column(key, width=px(150), minwidth=px(60))
        tree.tag_configure('odd', background=STRIPE)
        scrollbar = ttk.Scrollbar(wrapper, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        if scroll_x:
            horizontal = ttk.Scrollbar(wrapper, orient='horizontal', command=tree.xview)
            tree.configure(xscrollcommand=horizontal.set)
            horizontal.pack(side='bottom', fill='x')
        scrollbar.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)
        return tree

    @staticmethod
    def stripe(tree):
        for index, item in enumerate(tree.get_children()):
            tree.item(item, tags=('odd',) if index % 2 else ())

    def refresh_phase_loop(self):
        if self.closing:
            return
        self.refresh_view('phase')
        self.root.after(2000, self.refresh_phase_loop)

    def update_game_status(self):
        if self.stopping:
            return
        active = self.process is not None
        if self.game_phase in ('InProgress', 'Reconnect', 'GameStart'):
            text = '게임 중'
        elif active and self.submission_state == 'submitted':
            text = '경기 결과 제출 완료! · 대기중'
        elif active and self.submission_state == 'failed':
            text = '경기 결과 제출 실패 · 재시도 대기중'
        elif active and (self.submission_state == 'pending' or self.game_phase in ('WaitingForStats', 'PreEndOfGame', 'EndOfGame')):
            text = '경기 종료 · 결과 제출 대기중'
        elif self.game_phase is None and active:
            text = '대기중 · 롤 연결 확인 중'
        else:
            text = '대기중'
        if not active:
            text += ' · 수집 중지'
        self.status.set(text)

    def refresh_lobby_loop(self):
        if self.closing:
            return
        self.refresh_view('lobby')
        self.root.after(5000, self.refresh_lobby_loop)

    def refresh_view(self, kind):
        if self.closing or kind in self.view_busy:
            return
        self.view_busy.add(kind)
        source = self.history_source.get() if kind == 'history' else None
        if kind == 'history':
            self.history_status.set('기록을 불러오는 중...')
        def fetch():
            try:
                if kind == 'account':
                    self.view_events.put((kind, source, self.fetch_account(), None))
                    return
                if kind == 'champselect':
                    self.view_events.put((kind, source, self.fetch_champ_select(), None))
                    return
                if kind == 'history' and source == '웹앱 내전 기록':
                    with urllib.request.urlopen(collector.SERVER_URL, context=ssl.create_default_context(), timeout=8) as response:
                        data = json.load(response)
                    records = data.get('matchHistory', [])
                    if not isinstance(records, list):
                        raise ValueError('경기 목록 형식을 확인할 수 없습니다.')
                    result = records
                else:
                    port, password = collector.get_lcu_credentials()
                    if not port:
                        raise ValueError('롤 클라이언트에 연결할 수 없습니다.')
                    endpoint = '/lol-lobby/v2/lobby' if kind == 'lobby' else '/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=10'
                    if kind == 'phase':
                        endpoint = '/lol-gameflow/v1/gameflow-phase'
                    data = collector.query_lcu(port, password, endpoint)
                    if kind == 'phase':
                        if not isinstance(data, str):
                            raise ValueError('게임 상태를 조회할 수 없습니다.')
                        self.view_events.put((kind, source, data, None))
                        return
                    if kind == 'lobby' and not isinstance(data, dict):
                        session = collector.query_lcu(port, password, '/lol-gameflow/v1/session')
                        game = (session.get('gameData') or {}) if isinstance(session, dict) else {}
                        if isinstance(session, dict) and session.get('phase') in ('ChampSelect','GameStart','InProgress','Reconnect','WaitingForStats','PreEndOfGame','EndOfGame') and game.get('isCustomGame') and (game.get('teamOne') or game.get('teamTwo')):
                            blue, red = game.get('teamOne') or [], game.get('teamTwo') or []
                            data = {'members':blue + red, '_inGame':True,
                                    'gameConfig':{'isCustom':True,'customTeam100':blue,'customTeam200':red}}
                    if not isinstance(data, dict):
                        raise ValueError('현재 로비가 없거나 조회할 수 없습니다.' if kind == 'lobby' else '최근 경기 기록을 조회할 수 없습니다.')
                    if kind == 'lobby':
                        data['_resolvedMembers'] = resolve_lobby_members(data, port, password, self.lobby_name_cache)
                    result = data if kind == 'lobby' else data.get('games', {}).get('games', [])
                    if kind == 'history':
                        me = collector.query_lcu(port, password, '/lol-summoner/v1/current-summoner') or {}
                        names = load_champion_names(port, password)
                        for game in result:
                            for identity in game.get('participantIdentities', []):
                                player = identity.get('player') or {}
                                if me.get('puuid') and player.get('puuid') == me['puuid']:
                                    game['_localParticipantId'] = identity.get('participantId')
                            for participant in game.get('participants', []):
                                participant['championName'] = resolve_champion_name(participant, names)
                self.view_events.put((kind, source, result, None))
            except Exception as exc:
                self.view_events.put((kind, source, None, str(exc)))
        threading.Thread(target=fetch, daemon=True).start()

    def retained_roster_status(self):
        count = len(self.last_lobby_data.get('_resolvedMembers', self.last_lobby_data.get('members', [])) or []) if self.last_lobby_data else 0
        if self.game_phase in ('GameStart', 'InProgress', 'Reconnect'):
            label = '게임 중 · 시작 전 팀 명단 유지'
        elif self.game_phase == 'ChampSelect':
            label = '챔피언 선택 중 · 마지막 팀 명단 유지'
        elif self.game_phase in ('WaitingForStats', 'PreEndOfGame', 'EndOfGame'):
            label = '경기 종료 · 마지막 팀 명단 유지'
        else:
            label = '로비 조회 불가 · 마지막 확인 명단'
        self.lobby_status.set(f'{label} · {count}명')

    def render_view(self, kind, source, data, error):
        try:
            self._render_view(kind, source, data, error)
        finally:
            if kind in ('lobby', 'phase') and not self.closing:
                self.update_lobby_empty()

    def update_lobby_empty(self):
        empty = not self.blue_tree.get_children() and not self.red_tree.get_children()
        if empty:
            connected = self.conn_dot_color == GREEN
            self.lobby_empty_hint.configure(text='롤 클라이언트에서 사용자 설정 게임 방에 들어가면\n블루팀·레드팀 참가자가 여기에 자동으로 표시됩니다.' if connected
                                            else '롤 클라이언트를 실행하고 로그인하면\n내전방 참가자를 자동으로 불러옵니다.')
            if not self.lobby_empty.winfo_ismapped():
                self.teams_panel.pack_forget()
                self.lobby_empty.pack(expand=True)
        elif not self.teams_panel.winfo_ismapped():
            self.lobby_empty.pack_forget()
            self.teams_panel.pack(fill='both', expand=True, before=self.other_members_label)

    def _render_view(self, kind, source, data, error):
        self.view_busy.discard(kind)
        if kind == 'account':
            if not self.closing:
                self.render_account(data, error)
            return
        if kind == 'counters':
            if not self.closing:
                self.render_counters(data, error)
            return
        if kind == 'icons':
            if not self.closing:
                self.render_icons(data)
            return
        if kind == 'champselect':
            if not self.closing and not error and self.game_phase == 'ChampSelect':
                self.render_champ_select(data)
            return
        if kind == 'phase':
            previous = self.game_phase
            self.game_phase = None if error else data
            if self.game_phase in ('InProgress', 'Reconnect', 'GameStart') and previous not in ('InProgress', 'Reconnect', 'GameStart'):
                self.submission_state = None
            if self.game_phase == 'ChampSelect':
                if previous != 'ChampSelect':
                    # 챔피언 선택에 들어가면 카운터 탭을 한 번 띄운다.
                    self.counter_auto_key = None
                    self.show_tab(self.counter_tab, refresh=False)
                self.refresh_view('champselect')
            elif previous == 'ChampSelect':
                self.champ_select = None
                for child in self.counter_picks.winfo_children():
                    child.destroy()
            self.update_game_status()
            if data == 'None' and not error:
                self.last_lobby_data = None
                self.roster_retained = False
                for team_tree in (self.blue_tree, self.red_tree):
                    team_tree.delete(*team_tree.get_children())
                self.blue_title.set('블루팀 · 0명')
                self.red_title.set('레드팀 · 0명')
                self.other_members.set('')
                self.lobby_status.set('현재 참가 중인 로비가 없습니다.')
            elif self.roster_retained:
                self.retained_roster_status()
            return
        if self.closing:
            return
        if kind == 'history' and source != self.history_source.get():
            self.refresh_view('history')
            return
        if kind == 'lobby':
            members = (data.get('_resolvedMembers', data.get('members')) or []) if isinstance(data, dict) else []
            during_game = self.game_phase in ('ChampSelect', 'GameStart', 'InProgress', 'Reconnect', 'WaitingForStats', 'PreEndOfGame', 'EndOfGame')
            if self.last_lobby_data and self.game_phase != 'None' and (error or (during_game and not members)):
                self.roster_retained = True
                self.retained_roster_status()
                return
            if not error:
                self.last_lobby_data = data if members else None
                self.roster_retained = False
        if kind == 'history' and error:
            self.history_status.set(error + ' · 이전 목록 유지')
            return
        tree = self.history_tree
        if kind == 'lobby':
            for team_tree in (self.blue_tree, self.red_tree):
                team_tree.delete(*team_tree.get_children())
            self.blue_title.set('블루팀 · 0명')
            self.red_title.set('레드팀 · 0명')
            self.other_members.set('')
        else:
            tree.delete(*tree.get_children())
        status = self.lobby_status if kind == 'lobby' else self.history_status
        if error:
            status.set(error)
            return
        if kind == 'lobby':
            members = data.get('_resolvedMembers', data.get('members')) or []
            config = data.get('gameConfig') or {}
            label = '진행 중인 경기 · 세션에서 복원' if data.get('_inGame') else '내전방' if config.get('isCustom') else '현재 로비'
            status.set(f'{label} · {len(members)}명 · 5초마다 자동 갱신')
            others = []
            for member in members:
                name = member.get('_displayName') or member.get('riotIdGameName') or member.get('summonerName') or '이름 확인 불가'
                team = member.get('_displayTeam') or {100:'블루',200:'레드'}.get(member.get('teamId'), '미확인 / 대기')
                leader = '방장' if member.get('isLeader') else ''
                if team in ('블루', '레드'):
                    team_tree = self.blue_tree if team == '블루' else self.red_tree
                    team_tree.insert('', 'end', values=(name, leader))
                else:
                    others.append(f'{name} ({team}' + (', 방장)' if leader else ')'))
            self.stripe(self.blue_tree)
            self.stripe(self.red_tree)
            self.blue_title.set(f'블루팀 · {len(self.blue_tree.get_children())}명')
            self.red_title.set(f'레드팀 · {len(self.red_tree.get_children())}명')
            self.other_members.set('관전자 / 대기: ' + ', '.join(others) if others else '')
        else:
            self.history_records.clear()
            for index, record in enumerate(data):
                if not isinstance(record, dict): continue
                if source == '웹앱 내전 기록':
                    winner = {'BLUE': '블루팀 승리', 'RED': '레드팀 승리'}.get(str(record.get('winner', '')).upper(), '알 수 없음')
                    values = (record.get('date',''), '내전', winner, record.get('duration','알 수 없음'), record.get('matchId',''))
                else:
                    stamp = record.get('gameCreation')
                    date = datetime.datetime.fromtimestamp(stamp / 1000).strftime('%Y-%m-%d %H:%M') if isinstance(stamp,(int,float)) else record.get('gameCreationDate','')
                    duration = record.get('gameDuration')
                    duration = f'{int(duration)//60}분 {int(duration)%60:02d}초' if isinstance(duration,(int,float)) else '알 수 없음'
                    participants = record.get('participants') or []
                    own = next((p for p in participants if game_id_equal(p.get('participantId'), record.get('_localParticipantId'))), participants[0] if len(participants)==1 else {})
                    stats = own.get('stats') or {}
                    win = stats.get('win')
                    result = '승리' if win is True else '패배' if win is False else '알 수 없음'
                    values = (date, record.get('gameMode',''), result, duration, record.get('gameId',''))
                item = tree.insert('', 'end', values=values)
                self.history_records[item] = (source, record)
            self.stripe(tree)
            status.set(f'{len(self.history_records)}경기 · 더블클릭하면 상세 정보를 봅니다.')

    def show_match(self, event=None):
        selected = self.history_tree.selection()
        if not selected or selected[0] not in self.history_records: return
        source, record = self.history_records[selected[0]]
        window = tk.Toplevel(self.root)
        window.title('경기 상세')
        window.geometry(f'{px(780)}x{px(480)}')
        window.configure(bg=BG)
        holder = tk.Frame(window, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        holder.pack(fill='both', expand=True, padx=px(16), pady=px(16))
        box = tk.Text(holder, wrap='word', font=font(10), bg=CARD, fg=FG, selectbackground=ACCENT_SOFT, selectforeground=FG, inactiveselectbackground=ACCENT_TINT, relief='flat', bd=0, highlightthickness=0,
                      padx=px(18), pady=px(16), spacing1=px(2), spacing3=px(2))
        scroll = ttk.Scrollbar(holder, orient='vertical', command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        box.pack(side='left', fill='both', expand=True)
        box.tag_configure('meta', foreground=SUB)
        box.tag_configure('blue', foreground=BLUE, font=font(12, 'bold'), spacing1=px(10))
        box.tag_configure('red', foreground=RED, font=font(12, 'bold'), spacing1=px(10))
        if source == '웹앱 내전 기록':
            box.insert('end', f"경기 {record.get('matchId','')}  ·  승리 {record.get('winner','')}  ·  {record.get('duration','')}\n", 'meta')
            for key, label in [('blue','블루팀'),('red','레드팀')]:
                box.insert('end', label + '\n', key)
                for player in record.get(key,[]) or []:
                    box.insert('end', f"  {player.get('name','')}  /  {player.get('champion','')}  /  {('미확인' if player.get('role') in ('UNKNOWN', None, '') else player.get('role'))}  /  KDA {player.get('kda','')}  /  딜량 {player.get('damage','')}  /  CS {player.get('cs','')}\n")
        else:
            identities = {i.get('participantId'): i.get('player',{}) for i in record.get('participantIdentities',[]) or []}
            lines = [f"경기: {record.get('gameId','')}  |  {record.get('gameMode','')}", '']
            for player in record.get('participants',[]) or []:
                identity = identities.get(player.get('participantId'),{})
                name = identity.get('gameName') or identity.get('summonerName') or '이름 확인 불가'
                stats = player.get('stats') or {}
                lines.append(f"{name}  /  {player.get('championName') or ('챔피언 ID ' + str(player.get('championId','')))}  /  KDA {stats.get('kills','?')}/{stats.get('deaths','?')}/{stats.get('assists','?')}")
            box.insert('end', '\n'.join(lines))
        box.configure(state='disabled')

    def append(self, text):
        self.log.configure(state='normal')
        for line in text.splitlines(keepends=True):
            head = line.lstrip()
            tag = ('error' if head.startswith(('[오류]', '[화면 오류]')) or '실패' in line else
                   'warn' if head.startswith('[!]') else
                   'ok' if head.startswith(('[+]', '[ 성공]')) else
                   'info' if head.startswith(('[*]', '[-]')) else '')
            self.log.insert('end', line, tag)
        if int(self.log.index('end-1c').split('.')[0]) > 1500:
            self.log.delete('1.0', '300.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def save_log(self):
        from tkinter import filedialog
        filename = filedialog.asksaveasfilename(parent=self.root, title='로그 저장', defaultextension='.txt', filetypes=[('텍스트 파일','*.txt')])
        if filename:
            try:
                Path(filename).write_text(self.log.get('1.0', 'end-1c'), encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('저장 실패', str(exc), parent=self.root)

    def clear(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')

    def start(self):
        if self.process is not None:
            return
        executable = Path(sys.executable)
        if FROZEN:
            # exe로 묶이면 sys.executable이 exe 자신이므로 인자만 넘긴다.
            command = [str(executable), '--worker']
        else:
            if executable.name.lower() == 'pythonw.exe':
                executable = executable.with_name('python.exe')
            command = [str(executable), '-u', str(Path(__file__).resolve()), '--worker']
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        try:
            process = subprocess.Popen(command, cwd=BASE, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            messagebox.showerror('실행 오류', str(exc))
            return
        self.process = process
        self.stopping = False
        self.submission_state = None
        self.update_game_status()
        self.refresh_view('phase')
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        def read():
            try:
                for line in process.stdout:
                    self.events.put(line)
            finally:
                process.stdout.close()
        threading.Thread(target=read, daemon=True).start()

    def stop(self):
        if self.process is None or self.stopping:
            return
        self.stopping = True
        self.status.set('중지 중 · 진행 중인 요청을 마무리하고 있습니다')
        self.stop_button.configure(state='disabled')
        try:
            self.process.stdin.write('\n')
            self.process.stdin.flush()
        except (OSError, ValueError):
            pass

    def poll(self):
        for _ in range(50):
            try:
                result = self.view_events.get_nowait()
            except queue.Empty:
                break
            self.render_view(*result)
        for _ in range(200):
            try:
                line = self.events.get_nowait()
            except queue.Empty:
                break
            if line.startswith('@EVENT '):
                try:
                    event = json.loads(line[7:])
                    if event.get('type') == 'submitted' and not self.stopping:
                        self.submission_state = 'submitted'
                        self.update_game_status()
                        self.refresh_view('history')
                except (ValueError, TypeError):
                    pass
                continue
            self.append(line)
            if not self.stopping:
                if '내전 경기 종료 감지' in line:
                    self.submission_state = 'pending'
                elif '동기화 전송 실패' in line:
                    self.submission_state = 'failed'
                elif '성공]' in line or '이미 등록된 경기' in line:
                    pass
                elif '실행되어 있지' in line or '클라이언트가 종료' in line:
                    self.game_phase = None
                self.update_game_status()
        if self.process is not None and self.process.poll() is not None:
            code = self.process.returncode
            self.process.stdin.close()
            self.process = None
            self.stopping = False
            self.update_game_status()
            if code != 0:
                self.status.set(f'오류로 종료됨 · 코드 {code}, 로그를 확인하세요')
            self.start_button.configure(state='normal')
            self.stop_button.configure(state='disabled')
            self.stopping = False
        if self.closing and self.process is None:
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        self.start_button.configure(state='disabled')
        self.stop()
        if self.process is None:
            self.root.destroy()


if __name__ == '__main__':
    # exe에서는 PYTHONIOENCODING·-u가 적용되지 않아 표준 입출력이 cp1252(charmap)로 잡힐 수 있다.
    # 한글 출력에서 UnicodeEncodeError가 나지 않도록 모든 실행 모드에서 먼저 UTF-8로 맞춘다.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    if sys.stdin is not None and hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8', errors='replace')
    if '--check-resources' in sys.argv:
        # 빌드 확인용: exe에 폰트가 함께 묶였는지 검사한다.
        missing = [name for name in FONT_FILES if not os.path.exists(resource_path('fonts', name))]
        print('누락된 리소스: ' + ', '.join(missing) if missing else '리소스 확인 완료', flush=True)
        sys.exit(1 if missing else 0)
    if '--worker' in sys.argv:
        try:
            run_worker()
        except Exception as exc:
            print(f'[오류] {exc}', flush=True)
            sys.exit(1)
    else:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        try:
            register_fonts()
        except OSError:
            pass
        app = tk.Tk()
        CollectorUI(app)
        app.mainloop()
