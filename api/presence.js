import { createClient } from '@supabase/supabase-js';
 
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);
 
// 접속자 1명 = scrim_data 테이블의 1개 행 (id: "presence:<clientId>")
//  - 메인 데이터 행('main_scrim_data_row')과 완전히 분리되어 /api/sync 동작에 영향을 주지 않습니다.
//  - 클라이언트마다 자기 행만 갱신하므로 동시 접속 시 서로 덮어쓰는 문제가 없습니다.
const PREFIX = 'presence:';
const TTL_MS = 45 * 1000;        // 45초 동안 핑이 없으면 접속 종료로 간주
const PURGE_MS = 10 * 60 * 1000; // 10분 지난 오래된 행은 정리
 
async function listActive(now) {
  const { data, error } = await supabase
    .from('scrim_data')
    .select('id, payload, updated_at')
    .like('id', `${PREFIX}%`)
    .gt('updated_at', now - TTL_MS);
 
  if (error) throw error;
 
  return (data || [])
    .map(row => ({
      id: row.payload?.id,
      name: row.payload?.name,
      isVoter: !!row.payload?.isVoter,
      // 서버/클라이언트 시계 차이를 피하기 위해 '몇 ms 전에 핑했는지'만 전달
      ageMs: Math.max(0, now - Number(row.updated_at))
    }))
    .filter(u => u.id);
}
 
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Accept, Content-Type');
  res.setHeader('Cache-Control', 'no-store');
 
  if (req.method === 'OPTIONS') return res.status(200).end();
 
  const now = Date.now();
 
  try {
    // GET: 현재 접속자 목록
    if (req.method === 'GET') {
      return res.status(200).json({ users: await listActive(now), serverTime: now });
    }
 
    // POST: 내 접속 핑 등록(또는 퇴장) 후 현재 접속자 목록 반환
    if (req.method === 'POST') {
      let body = req.body;
      if (typeof body === 'string') {
        try { body = JSON.parse(body); } catch (e) { body = {}; }
      }
      body = body || {};
 
      const id = String(body.id || '');
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) {
        return res.status(400).json({ error: 'invalid id' });
      }
 
      // 탭 닫음(pagehide → sendBeacon): 즉시 목록에서 제거
      if (body.leave === true) {
        const { error } = await supabase.from('scrim_data').delete().eq('id', PREFIX + id);
        if (error) throw error;
        return res.status(200).json({ success: true });
      }
 
      const name = String(body.name || '방문자').replace(/[\u0000-\u001f]/g, '').slice(0, 40) || '방문자';
 
      const { error } = await supabase.from('scrim_data').upsert({
        id: PREFIX + id,
        payload: { id, name, isVoter: body.isVoter === true },
        updated_at: now
      });
      if (error) throw error;
 
      // 가끔(약 10%) 오래된 접속 행 정리
      if (Math.random() < 0.1) {
        await supabase
          .from('scrim_data')
          .delete()
          .like('id', `${PREFIX}%`)
          .lt('updated_at', now - PURGE_MS);
      }
 
      return res.status(200).json({ users: await listActive(now), serverTime: now });
    }
 
    return res.status(405).json({ error: 'Method not allowed' });
  } catch (err) {
    console.error('Presence error:', err);
    return res.status(500).json({ error: err.message });
  }
}
