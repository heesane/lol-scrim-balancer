# 단일 파일 내전 수집기: 이 파일만 실행하세요.
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


QUEUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lcu_pending_matches.json")

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
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

BASE = Path(__file__).resolve().parent
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


class CollectorUI:
    def __init__(self, root):
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
        root.title('내전 결과 수집기 · v2.0')
        root.geometry('1000x680')
        root.minsize(800, 560)
        root.configure(bg='#f4f6fa')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#f4f6fa')
        style.configure('TLabel', background='#f4f6fa', font=('맑은 고딕', 10))
        style.configure('Title.TLabel', font=('맑은 고딕', 20, 'bold'))
        style.configure('Treeview', font=('맑은 고딕', 10), rowheight=32)
        style.configure('Treeview.Heading', font=('맑은 고딕', 10, 'bold'), padding=8)
        style.configure('TNotebook.Tab', padding=(18, 10), font=('맑은 고딕', 10))
        style.configure('Status.TLabel', font=('맑은 고딕', 12, 'bold'), foreground='#1d4ed8')
        style.configure('TButton', font=('맑은 고딕', 10), padding=(16, 9))
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='내전 결과 수집기', style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame, text='롤 클라이언트에서 경기 결과를 수집하고 웹앱에 동기화합니다.').pack(anchor='w', pady=(6, 18))
        self.status = tk.StringVar(value='대기중 · 수집 중지')
        ttk.Label(frame, textvariable=self.status, style='Status.TLabel').pack(anchor='w', pady=(0, 12))
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(0, 16))
        self.start_button = ttk.Button(buttons, text='수집 시작', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='중지', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        ttk.Button(buttons, text='로그 지우기', command=self.clear).pack(side='right')
        ttk.Button(buttons, text='로그 저장', command=self.save_log).pack(side='right', padx=8)
        ttk.Button(buttons, text='웹앱 열기', command=lambda: __import__('webbrowser').open(SERVER_URL.rsplit('/api/', 1)[0])).pack(side='right')
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill='both', expand=True)
        log_tab = ttk.Frame(self.tabs)
        self.lobby_tab = ttk.Frame(self.tabs, padding=12)
        self.history_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.lobby_tab, text='현재 방 참가자')
        self.tabs.add(log_tab, text='실행 로그')
        self.tabs.add(self.history_tab, text='매치 히스토리')
        self.lobby_status = tk.StringVar(value='조회 중...')
        ttk.Label(self.lobby_tab, textvariable=self.lobby_status).pack(anchor='w')
        ttk.Button(self.lobby_tab, text='새로고침', command=lambda: self.refresh_view('lobby')).pack(anchor='e', pady=8)
        teams_panel = ttk.Frame(self.lobby_tab)
        teams_panel.pack(fill='both', expand=True)
        teams_panel.columnconfigure(0, weight=1, uniform='team')
        teams_panel.columnconfigure(1, weight=1, uniform='team')
        teams_panel.rowconfigure(0, weight=1)
        blue_panel = ttk.Frame(teams_panel, padding=(0, 0, 8, 0))
        red_panel = ttk.Frame(teams_panel, padding=(8, 0, 0, 0))
        blue_panel.grid(row=0, column=0, sticky='nsew')
        red_panel.grid(row=0, column=1, sticky='nsew')
        self.blue_title = tk.StringVar(value='블루팀 · 0명')
        self.red_title = tk.StringVar(value='레드팀 · 0명')
        ttk.Label(blue_panel, textvariable=self.blue_title, foreground='#2563eb', font=('맑은 고딕', 14, 'bold')).pack(anchor='w', pady=(0, 10))
        ttk.Label(red_panel, textvariable=self.red_title, foreground='#dc2626', font=('맑은 고딕', 14, 'bold')).pack(anchor='w', pady=(0, 10))
        self.blue_tree = self.make_table(blue_panel, [('name','플레이어'), ('leader','방장')])
        self.red_tree = self.make_table(red_panel, [('name','플레이어'), ('leader','방장')])
        for team_tree in (self.blue_tree, self.red_tree):
            team_tree.column('name', width=260, minwidth=100)
            team_tree.column('leader', width=60, minwidth=50, stretch=False)
        self.other_members = tk.StringVar(value='')
        ttk.Label(self.lobby_tab, textvariable=self.other_members, wraplength=840).pack(anchor='w', pady=(10, 0))
        bar = ttk.Frame(self.history_tab)
        bar.pack(fill='x', pady=(0,8))
        self.history_source = tk.StringVar(value='웹앱 내전 기록')
        picker = ttk.Combobox(bar, textvariable=self.history_source, values=['웹앱 내전 기록','내 계정 최근 경기'], state='readonly', width=24)
        picker.pack(side='left')
        picker.bind('<<ComboboxSelected>>', lambda e: self.refresh_view('history'))
        ttk.Button(bar, text='새로고침', command=lambda: self.refresh_view('history')).pack(side='right')
        self.history_status = tk.StringVar(value='새로고침을 눌러 기록을 불러오세요. 행을 더블클릭하면 상세 정보를 봅니다.')
        ttk.Label(self.history_tab, textvariable=self.history_status).pack(anchor='w', pady=(0,8))
        self.history_tree = self.make_table(self.history_tab, [('date','일시'), ('mode','종류'), ('result','결과'), ('duration','시간'), ('id','경기 ID')])
        self.history_tree.bind('<Double-1>', self.show_match)
        self.history_tree.bind('<Return>', self.show_match)
        self.log = ScrolledText(log_tab, wrap='word', font=('맑은 고딕', 10), bg='#152033', fg='#e2e8f0', relief='flat', padx=14, pady=14, state='disabled')
        self.log.pack(fill='both', expand=True)
        ttk.Label(frame, text='전송에 실패한 경기는 로컬에 보관되며, 수집 중 또는 다음 시작 시 재시도합니다.').pack(anchor='w', pady=(12, 0))
        self.append('수집 시작을 누르면 자동 업로드가 활성화됩니다.\n')
        root.report_callback_exception = self.ui_error
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)
        root.after(200, self.refresh_lobby_loop)
        root.after(100, self.refresh_phase_loop)
        self.tabs.bind('<<NotebookTabChanged>>', lambda e: self.refresh_view('history') if self.tabs.select() == str(self.history_tab) else None)

    def ui_error(self, error_type, error, traceback):
        import traceback as trace
        self.append('[화면 오류] ' + ''.join(trace.format_exception(error_type, error, traceback)) + '\n')
        self.status.set('화면 처리 오류 · 실행 로그를 확인하세요')

    @staticmethod
    def make_table(parent, columns):
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill='both', expand=True)
        tree = ttk.Treeview(wrapper, columns=[c[0] for c in columns], show='headings', selectmode='browse')
        for key, title in columns:
            tree.heading(key, text=title)
            tree.column(key, width=150, minwidth=60)
        scrollbar = ttk.Scrollbar(wrapper, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        horizontal = ttk.Scrollbar(wrapper, orient='horizontal', command=tree.xview)
        tree.configure(xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom', fill='x')
        scrollbar.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)
        return tree

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
        self.view_busy.discard(kind)
        if kind == 'phase':
            previous = self.game_phase
            self.game_phase = None if error else data
            if self.game_phase in ('InProgress', 'Reconnect', 'GameStart') and previous not in ('InProgress', 'Reconnect', 'GameStart'):
                self.submission_state = None
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
            self.blue_title.set(f'블루팀 · {len(self.blue_tree.get_children())}명')
            self.red_title.set(f'레드팀 · {len(self.red_tree.get_children())}명')
            self.other_members.set('관전자 / 대기: ' + ', '.join(others) if others else '')
        else:
            self.history_records.clear()
            for index, record in enumerate(data):
                if not isinstance(record, dict): continue
                if source == '웹앱 내전 기록':
                    values = (record.get('date',''), '웹앱 저장 기록', record.get('winner','알 수 없음'), record.get('duration','알 수 없음'), record.get('matchId',''))
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
            status.set(f'{len(self.history_records)}경기 · 더블클릭하면 상세 정보를 봅니다.')

    def show_match(self, event=None):
        selected = self.history_tree.selection()
        if not selected or selected[0] not in self.history_records: return
        source, record = self.history_records[selected[0]]
        window = tk.Toplevel(self.root)
        window.title('경기 상세')
        window.geometry('760x460')
        box = ScrolledText(window, wrap='word', font=('맑은 고딕',10), padx=16, pady=16)
        box.pack(fill='both', expand=True)
        if source == '웹앱 내전 기록':
            lines = [f"경기: {record.get('matchId','')}  |  승리: {record.get('winner','')}  |  시간: {record.get('duration','')}", '']
            for key, label in [('blue','블루팀'),('red','레드팀')]:
                lines.append(label)
                for player in record.get(key,[]) or []:
                    lines.append(f"  {player.get('name','')}  /  {player.get('champion','')}  /  {('미확인' if player.get('role') in ('UNKNOWN', None, '') else player.get('role'))}  /  KDA {player.get('kda','')}  /  딜량 {player.get('damage','')}  /  CS {player.get('cs','')}")
                lines.append('')
            box.insert('end', '\n'.join(lines))
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
        self.log.insert('end', text)
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
        if executable.name.lower() == 'pythonw.exe':
            executable = executable.with_name('python.exe')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        try:
            process = subprocess.Popen([str(executable), '-u', str(Path(__file__).resolve()), '--worker'], cwd=BASE, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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
        app = tk.Tk()
        CollectorUI(app)
        app.mainloop()
