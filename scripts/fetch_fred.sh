#!/usr/bin/env bash
# Patient FRED fetcher. Retries each series until it downloads (or gives up after
# MAX_TRIES), writing the file only on a clean 200 so partial writes never persist.
# Usage: bash scripts/fetch_fred.sh
set -u
cd "$(dirname "$0")/.."
mkdir -p data/raw
SERIES="DEXINUS DEXMAUS DEXTHUS DEXSIUS DCOILBRENTEU"
MAX_TRIES=200
UA="idr-usd-fx/1.0 (portfolio analysis)"

fetch_one() {
  local s="$1" tmp code
  tmp=$(mktemp)
  for try in $(seq 1 "$MAX_TRIES"); do
    code=$(curl -sS --http1.1 --connect-timeout 8 --max-time 25 -A "$UA" \
      -o "$tmp" -w "%{http_code}" \
      "https://fred.stlouisfed.org/graph/fredgraph.csv?id=$s" 2>/dev/null)
    if [ "$code" = "200" ] && [ -s "$tmp" ] && head -1 "$tmp" | grep -qi "$s"; then
      mv "$tmp" "data/raw/$s.csv"
      echo "[$s] OK on try $try: $(wc -l < data/raw/$s.csv | tr -d ' ') lines"
      return 0
    fi
    sleep 5
  done
  rm -f "$tmp"
  echo "[$s] FAILED after $MAX_TRIES tries (last HTTP=$code)"
  return 1
}

fail=0
for s in $SERIES; do
  if [ -s "data/raw/$s.csv" ] && head -1 "data/raw/$s.csv" | grep -qi "$s"; then
    echo "[$s] already present, skipping"
    continue
  fi
  fetch_one "$s" || fail=1
done
echo "DONE (fail=$fail)"
exit $fail
