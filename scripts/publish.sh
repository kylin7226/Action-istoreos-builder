#!/bin/bash
set -euo pipefail
cd "$GITHUB_WORKSPACE/out"
sha256sum -c SHA256SUMS.txt
DATE=$(date -u +%Y.%m.%d)
DTAG="v${DATE}.${GITHUB_RUN_NUMBER}.${GITHUB_RUN_ATTEMPT}"
ASSETS=(*)
if gh release view "$DTAG" -R "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
	printf 'Release %s already exists; rerun with a new attempt rather than overwriting history.\n' "$DTAG" >&2
	exit 1
fi
gh release create "$DTAG" -R "$GITHUB_REPOSITORY" --draft --target "$GITHUB_SHA" \
	--title "Cyber3588-AIB iStoreOS $DTAG" \
	--notes "Commit $GITHUB_SHA; IB SHA256 $IB_SHA. Immutable historical firmware; verify SHA256SUMS.txt before flashing." \
	"${ASSETS[@]}"
gh release edit "$DTAG" -R "$GITHUB_REPOSITORY" --draft=false --latest=false
if ! gh release view firmware -R "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
	gh release create firmware -R "$GITHUB_REPOSITORY" --draft --target "$GITHUB_SHA" \
		--title 'Cyber3588-AIB iStoreOS（最新）'
fi
# Publish the update marker only after the firmware and its checksums are verified remotely.
UPLOAD=()
for asset in "${ASSETS[@]}"; do
	[ "$asset" = ib-source-sha256.txt ] || UPLOAD+=("$asset")
done
gh release upload firmware -R "$GITHUB_REPOSITORY" --clobber "${UPLOAD[@]}"
CHECK=$(mktemp -d "$RUNNER_TEMP/release-check.XXXXXX")
trap 'rm -rf "$CHECK"' EXIT
gh release download firmware -R "$GITHUB_REPOSITORY" --dir "$CHECK"
cp ib-source-sha256.txt "$CHECK/"
(cd "$CHECK" && sha256sum -c "$GITHUB_WORKSPACE/out/SHA256SUMS.txt")
gh release edit firmware -R "$GITHUB_REPOSITORY" --draft=false --latest \
	--notes "Latest build: $DTAG; commit $GITHUB_SHA. For an immutable, internally consistent download use the dated release. The rolling tag itself is not the source revision; see build-commit.txt."
gh release upload firmware -R "$GITHUB_REPOSITORY" --clobber ib-source-sha256.txt
printf 'Published %s and firmware\n' "$DTAG"
