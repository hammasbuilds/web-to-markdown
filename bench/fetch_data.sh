#!/usr/bin/env bash
# Download both benchmarks into data/ (about 57 MB). Safe to re-run: finished
# files are skipped, and the WCEB archive is fetched in resumable 1 MB ranges,
# because one long download over a slow link fails more often than 48 short ones.
set -euo pipefail
cd "$(dirname "$0")/.."
DATA=${WEB2MD_DATA:-data}

# scrapinghub/article-extraction-benchmark (MIT): 181 pages + ground truth.
AEB=https://raw.githubusercontent.com/scrapinghub/article-extraction-benchmark/master
mkdir -p "$DATA/aeb/html" "$DATA/aeb/published"
fetch() {  # url dest expected_size
  local url=$1 dest=$2 size=${3:-}
  for _ in 1 2 3 4 5; do
    if [ -s "$dest" ] && { [ -z "$size" ] || [ "$(wc -c < "$dest")" -eq "$size" ]; }; then
      return 0
    fi
    curl -sSL --retry 3 -m 600 -o "$dest" "$url" || true
  done
  echo "failed: $url" >&2
  return 1
}
fetch "$AEB/ground-truth.json" "$DATA/aeb/ground-truth.json" 924126
python - "$DATA/aeb/ground-truth.json" > "$DATA/aeb/ids.txt" <<'PY'
import json, sys
print("\n".join(json.load(open(sys.argv[1], encoding="utf-8"))))
PY
tr -d '\r' < "$DATA/aeb/ids.txt" | while read -r id; do
  fetch "$AEB/html/$id.html.gz" "$DATA/aeb/html/$id.html.gz"
done
# Published outputs of three tools, used only to check that bench/metrics.py
# reproduces the benchmark's own F1 numbers.
for name in trafilatura readability html-text; do
  fetch "$AEB/output/$name.json" "$DATA/aeb/published/$name.json"
done

# chatnoir-eu/web-content-extraction-benchmark (Bevendorff et al., 2023): the
# combined datasets archive, stored in Git LFS.
WCEB=https://media.githubusercontent.com/media/chatnoir-eu/web-content-extraction-benchmark/main/datasets/combined.tar.xz
SIZE=50103424
SHA=ed4e57ecad343cdce51d06fa560c1f50965367ea6714cd08e85a439102bc4b1a
mkdir -p "$DATA/wceb/parts"
if [ ! -d "$DATA/wceb/combined" ]; then
  CHUNK=1048576
  n=$(( (SIZE + CHUNK - 1) / CHUNK ))
  for i in $(seq 0 $((n - 1))); do
    start=$((i * CHUNK)); end=$((start + CHUNK - 1)); [ $end -ge $SIZE ] && end=$((SIZE - 1))
    part=$(printf "%s/wceb/parts/%05d" "$DATA" "$i")
    for _ in 1 2 3 4 5 6 7 8; do
      [ -f "$part" ] && [ "$(wc -c < "$part")" -eq $((end - start + 1)) ] && break
      curl -sSL -m 300 -r "$start-$end" -o "$part" "$WCEB" || true
    done
  done
  cat "$DATA"/wceb/parts/* > "$DATA/wceb/combined.tar.xz"
  echo "$SHA  $DATA/wceb/combined.tar.xz" | sha256sum -c -
  tar xJf "$DATA/wceb/combined.tar.xz" -C "$DATA/wceb"
  rm -rf "$DATA/wceb/parts" "$DATA/wceb/combined.tar.xz"
fi
# One packed file instead of 3,800 loose ones: much faster to load on a busy disk.
[ -f "$DATA/wceb/pages.jsonl.gz" ] || WEB2MD_DATA="$DATA" uv run python -m bench.datasets
echo "data ready in $DATA"
