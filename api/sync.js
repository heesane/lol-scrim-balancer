import { createClient } from '@supabase/supabase-js';
 
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);
 
// ─────────────────────────────────────────────────────────────
// 🗳️ 내전 일정(투표) 병합 로직
//
// 문제: 클라이언트는 '자기가 알고 있는 전체 상태'를 통째로 보내므로, 4초 안에 다른 사람이
//       한 투표를 아직 모르는 클라이언트가 저장하면 그 투표가 지워졌습니다.
// 해결: 서버가 기존 데이터와 들어온 데이터를 투표 단위로 합칩니다.
//   - 새로 들어온/바뀐 투표  → 반영 (서버가 votedAt 시각 도장을 찍음)
//   - 서버에만 있는 투표      → 유지 (클라이언트가 아직 모르는 새 투표)
//       단, 이번 저장에 '취소(CANCEL)' 로그가 새로 있으면 취소로 보고 제거
//   - 옛 사본(도장이 더 오래됨) → 서버의 최신 투표를 유지
//   - 이미 서버에서 사라진 투표의 옛 사본 → 부활시키지 않음
// ─────────────────────────────────────────────────────────────
const VOTE_FIELDS = ['id', 'name', 'status', 'availTime', 'reason'];
const MAX_VOTE_LOGS = 25;
 
const isObj = v => v && typeof v === 'object' && !Array.isArray(v);
const voteKey = p => (p && (p.id || p.name)) || null;
// Supabase(jsonb)는 키 순서를 바꿔 저장하므로 JSON 문자열 비교 대신 필드별로 비교
const sameVote = (a, b) => VOTE_FIELDS.every(k => (a?.[k] ?? '') === (b?.[k] ?? ''));
const logKey = l => [l?.timestamp, l?.name, l?.oldStatus, l?.newStatus, l?.availTime, l?.reason].join('|');
 
function mergeParticipants(existingList, incomingList, cancelledNames, stamp) {
  const exMap = new Map();
  (Array.isArray(existingList) ? existingList : []).forEach(p => {
    const k = voteKey(p);
    if (k && !exMap.has(k)) exMap.set(k, p);
  });
 
  const outMap = new Map();
  const incomingOrder = [];
 
  (Array.isArray(incomingList) ? incomingList : []).forEach(p => {
    const k = voteKey(p);
    if (!k || outMap.has(k) || !isObj(p)) return;
    const e = exMap.get(k);
 
    if (e) {
      if (p.votedAt && e.votedAt && p.votedAt < e.votedAt) {
        outMap.set(k, e);                          // 클라이언트 사본이 옛것 → 서버 최신 유지
      } else if (sameVote(p, e)) {
        outMap.set(k, e);                          // 변화 없음
      } else {
        outMap.set(k, { ...p, votedAt: stamp });   // 이번에 바꾼 투표
      }
    } else if (p.votedAt) {
      // 도장이 있는데 서버엔 없음 = 그 사이 누군가 취소한 투표의 옛 사본 → 되살리지 않음
    } else {
      outMap.set(k, { ...p, votedAt: stamp });     // 새 투표
    }
    if (outMap.has(k)) incomingOrder.push(k);
  });
 
  // 서버에만 있는 투표: 이번 저장에서 취소한 게 아니면 유지
  for (const [k, e] of exMap) {
    if (!outMap.has(k) && !cancelledNames.has(e.name)) outMap.set(k, e);
  }
 
  // 표시 순서 안정화: 기존 순서 먼저, 새 투표는 뒤에
  const result = [];
  for (const k of exMap.keys()) if (outMap.has(k)) result.push(outMap.get(k));
  for (const k of incomingOrder) if (!exMap.has(k)) result.push(outMap.get(k));
  return result;
}
 
function mergeSchedules(existingSched, incomingSched, stamp) {
  const ex = isObj(existingSched) ? existingSched : {};
  const inc = isObj(incomingSched) ? incomingSched : {};
  const result = {};
 
  for (const date of new Set([...Object.keys(ex), ...Object.keys(inc)])) {
    const e = isObj(ex[date]) ? ex[date] : null;
    const i = isObj(inc[date]) ? inc[date] : null;
 
    if (!i) { result[date] = e; continue; }     // 이 클라이언트가 모르는 날짜 → 서버 것 유지
 
    const exLogs = Array.isArray(e?.voteLogs) ? e.voteLogs : [];
    const incLogs = Array.isArray(i.voteLogs) ? i.voteLogs : [];
    const exLogKeys = new Set(exLogs.map(logKey));
    const newLogs = incLogs.filter(l => !exLogKeys.has(logKey(l)));   // 이번 저장에서 새로 생긴 로그
    const cancelledNames = new Set(newLogs.filter(l => l?.newStatus === 'CANCEL').map(l => l.name));
 
    result[date] = {
      ...(e || {}),
      ...i,
      time: i.time ?? e?.time,
      participants: mergeParticipants(e?.participants, i.participants, cancelledNames, stamp),
      voteLogs: [...newLogs, ...exLogs].slice(0, MAX_VOTE_LOGS)
    };
  }
  return result;
}
 
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader(
    'Access-Control-Allow-Headers',
    'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version'
  );
 
  if (req.method === 'OPTIONS') return res.status(200).end();
 
  const rowId = 'main_scrim_data_row';
 
  // 1. GET: Supabase DB의 최신 전체 원본 데이터 반환
  if (req.method === 'GET') {
    try {
      const { data, error } = await supabase
        .from('scrim_data')
        .select('payload, updated_at')
        .eq('id', rowId)
        .single();
 
      if (error || !data || !data.payload) {
        return res.status(200).json({
          summoners: [],
          matchHistory: [],
          replayArchives: [],
          scrimSchedules: {},
          communityPosts: [],
          selectedPlayerIds: [],
          currentMatch: null,
          updatedAt: 0
        });
      }
 
      return res.status(200).json({
        ...data.payload,
        updatedAt: data.updated_at || Date.now()
      });
    } catch (err) {
      console.error('Sync GET error:', err);
      return res.status(500).json({ error: err.message });
    }
  }
 
  // 2. POST: 클라이언트에서 수정된 전체 상태를 안전하게 Supabase에 저장
  if (req.method === 'POST') {
    try {
      const incoming = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
      const wallClock = Date.now();
 
      const { data: current } = await supabase
        .from('scrim_data')
        .select('payload, updated_at')
        .eq('id', rowId)
        .single();
 
      const existing = current?.payload || {};
 
      // 🌟 저장 시각: 항상 이전 저장보다 크고, 저장한 클라이언트의 시각보다도 크게 만든다.
      //    → 저장한 클라이언트가 다음 동기화(4초 주기)에서 '병합된 최신 데이터'를 반드시 받아 가도록 보장
      //    (클라이언트/서버 시계가 어긋나도 동작, 단 클라이언트 시각은 최대 +60초까지만 신뢰)
      const clientTs = Number(incoming.updatedAt) || 0;
      const now = Math.max(
        wallClock,
        (Number(current?.updated_at) || 0) + 1,
        Math.min(clientTs, wallClock + 60000) + 1
      );
 
      // 🌟 [핵심 DB 방어막]: 관리자 삭제가 아닌 한 빈 배열 덮어쓰기 영구 차단
      let resolvedHistory = existing.matchHistory || [];
      if (incoming.allowEmptyHistory === true) {
        resolvedHistory = [];
      } else if (Array.isArray(incoming.matchHistory) && incoming.matchHistory.length > 0) {
        resolvedHistory = incoming.matchHistory;
      }
 
      let resolvedPosts = existing.communityPosts || [];
      if (incoming.allowEmptyPosts === true) {
        resolvedPosts = [];
      } else if (Array.isArray(incoming.communityPosts) && incoming.communityPosts.length > 0) {
        resolvedPosts = incoming.communityPosts;
      }
 
      // 🌟 내전 일정(투표): 백업 불러오기(두 플래그가 모두 true)는 그대로 덮어쓰고, 그 외에는 병합
      let resolvedSchedules;
      if (!isObj(incoming.scrimSchedules)) {
        resolvedSchedules = existing.scrimSchedules || {};
      } else if (incoming.allowEmptyHistory === true && incoming.allowEmptyPosts === true) {
        resolvedSchedules = incoming.scrimSchedules;
      } else {
        resolvedSchedules = mergeSchedules(existing.scrimSchedules, incoming.scrimSchedules, now);
      }
 
      // 🌟 대진표가 있으면 선택 인원은 항상 대진표 기준으로 저장
      const nextMatch = incoming.currentMatch !== undefined ? incoming.currentMatch : existing.currentMatch;
      let nextSelected = Array.isArray(incoming.selectedPlayerIds)
        ? incoming.selectedPlayerIds
        : (existing.selectedPlayerIds || []);
 
      if (nextMatch) {
        nextSelected = [...(nextMatch.blue || []), ...(nextMatch.red || [])]
          .filter(Boolean)
          .map(p => p.id);
      }
 
      const payload = {
        summoners: (Array.isArray(incoming.summoners) && incoming.summoners.length > 0) ? incoming.summoners : (existing.summoners || []),
        matchHistory: resolvedHistory,
        replayArchives: Array.isArray(incoming.replayArchives) ? incoming.replayArchives : (existing.replayArchives || []),
        scrimSchedules: resolvedSchedules,
        communityPosts: resolvedPosts,
        selectedPlayerIds: nextSelected,
        currentMatch: nextMatch,
        updatedAt: now
      };
 
      const { error } = await supabase
        .from('scrim_data')
        .upsert({
          id: rowId,
          payload: payload,
          updated_at: now
        });
 
      if (error) throw error;
      return res.status(200).json({ success: true, timestamp: now, data: payload });
 
    } catch (err) {
      console.error('Sync POST error:', err);
      return res.status(500).json({ error: err.message });
    }
  }
 
  return res.status(405).json({ error: 'Method not allowed' });
}
