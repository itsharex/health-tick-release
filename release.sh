#!/bin/bash
set -e
cd "$(dirname "$0")"

# Read version from Info.plist
VERSION=$(grep -A1 CFBundleShortVersionString Sources/Info.plist | tail -1 | sed 's/.*<string>\(.*\)<\/string>.*/\1/')
TAG="v${VERSION}"
REPO="lifedever/health-tick-release"

echo "=== HealthTick Release ${TAG} ==="
echo ""

# Check if tag already exists on remote
if git ls-remote --tags origin | grep -q "refs/tags/${TAG}$"; then
    echo "Error: tag ${TAG} already exists. Bump version in Sources/Info.plist first."
    exit 1
fi

# Build for each architecture separately
echo "[1/5] Building binaries..."
swift build -c release --arch arm64
echo "  Built arm64"
swift build -c release --arch x86_64
echo "  Built x86_64"

# Package app bundles
echo "[2/5] Packaging apps..."
STAGE="/tmp/health-tick-release-${VERSION}"
rm -rf "$STAGE"

for label in Apple-Silicon Intel; do
    if [ "$label" = "Apple-Silicon" ]; then
        BIN=".build/arm64-apple-macosx/release/HealthTick"
    else
        BIN=".build/x86_64-apple-macosx/release/HealthTick"
    fi
    APP_DIR="${STAGE}/${label}/HealthTick.app/Contents"
    mkdir -p "$APP_DIR/MacOS" "$APP_DIR/Resources"
    cp "$BIN" "$APP_DIR/MacOS/"
    cp Sources/Info.plist "$APP_DIR/"
    if [ -d "Sources/Resources" ]; then
        cp -R Sources/Resources/* "$APP_DIR/Resources/"
    fi
    codesign --force --deep --sign - "${STAGE}/${label}/HealthTick.app"
done

# Create DMGs
echo "[3/5] Creating DMGs..."
for label in Apple-Silicon Intel; do
    DMG_NAME="HealthTick-${TAG}-${label}.dmg"
    DMG_DIR="${STAGE}/dmg-${label}"
    mkdir -p "$DMG_DIR"
    cp -R "${STAGE}/${label}/HealthTick.app" "$DMG_DIR/"
    ln -s /Applications "$DMG_DIR/Applications"
    hdiutil create -volname "HealthTick" -srcfolder "$DMG_DIR" -ov -format UDZO \
        "${STAGE}/${DMG_NAME}" -quiet
    echo "  Created ${DMG_NAME}"
done

# Git commit, tag, push
echo "[4/5] Pushing tag ${TAG}..."
git add -A
git diff --cached --quiet || git commit -m "${TAG}"
git tag "$TAG" 2>/dev/null || true
git push origin main --tags

# Upload to public release repo
echo "[5/5] Publishing release to ${REPO}..."
gh release create "$TAG" \
    --repo "$REPO" \
    --title "HealthTick ${TAG}" \
    --notes "## HealthTick ${TAG}

### 下载
- **Apple Silicon (M1/M2/M3/M4)**: \`HealthTick-${TAG}-Apple-Silicon.dmg\`
- **Intel**: \`HealthTick-${TAG}-Intel.dmg\`

### 安装方式
打开 \`.dmg\` 文件，将 HealthTick 拖入 Applications 文件夹。
首次打开请前往 **系统设置 → 隐私与安全性** 点击\"仍要打开\"。" \
    "${STAGE}/HealthTick-${TAG}-Apple-Silicon.dmg" \
    "${STAGE}/HealthTick-${TAG}-Intel.dmg"

echo ""
echo "=== Done! Released ${TAG} to ${REPO} ==="
echo "https://github.com/${REPO}/releases/tag/${TAG}"

# Cleanup
rm -rf "$STAGE"
