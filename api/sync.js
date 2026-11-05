import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

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
      const now = Date.now();

      const { data: current } = await supabase
        .from('scrim_data')
        .select('payload')
        .eq('id', rowId)
        .single();

      const existing = current?.payload || {};

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
        scrimSchedules: (incoming.scrimSchedules && typeof incoming.scrimSchedules === 'object') ? incoming.scrimSchedules : (existing.scrimSchedules || {}),
        communityPosts: resolvedPosts,
        selectedPlayerIds: nextSelected,   // ← 변경
        currentMatch: nextMatch,           // ← 변경
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
