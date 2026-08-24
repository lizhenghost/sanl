#!/bin/sh
# Sanl 回归测试（真实路由）
BASE="http://127.0.0.1:8899"
pass=0; fail=0
for ep in / /manifest.webmanifest /sw.js /api/health /api/version /api/nodes "/api/nodes?page=1&page_size=5" /api/nodes/stats /api/nodes/subscribe /api/sources /api/sources/presets /api/sources/health /api/cf/endpoints /api/cf/scan/meta /api/check/progress /api/check/history /api/tasks /api/tokens /api/tokens/stats /api/cache/status /api/map /api/map/countries /api/ranking /api/stats/trend /api/edgetunnel/config-example; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE$ep")
  if [ "$code" = "200" ]; then pass=$((pass+1)); echo "PASS $code $ep"; else fail=$((fail+1)); echo "FAIL $code $ep"; fi
done
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d '{"count":3}' "$BASE/api/edgetunnel/generate")
if [ "$code" = "200" ]; then pass=$((pass+1)); echo "PASS $code POST /api/edgetunnel/generate"; else fail=$((fail+1)); echo "FAIL $code POST /api/edgetunnel/generate"; fi
echo "== 回归结果: $pass 通过 / $fail 失败 =="
