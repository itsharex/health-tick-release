# Release Skill

本地构建并发布 HealthTick 新版本。

## 使用方式

用户说"发版"或调用 `/release` 时执行。

## 步骤

1. **升版本号**：编辑 `Sources/Info.plist`，将 `CFBundleShortVersionString` +1（patch），`CFBundleVersion` +1
2. **清理构建缓存**：`rm -rf .build`
3. **编译 arm64**：`swift build -c release --arch arm64`
4. **编译 x86_64**：`swift build -c release --arch x86_64`
5. **打包两个 DMG**：
   - 为 Apple-Silicon 和 Intel 分别创建 `HealthTick.app` bundle
   - arm64 binary → Apple-Silicon DMG
   - x86_64 binary → Intel DMG
   - 每个 app bundle 包含：binary、Info.plist、Resources，并 ad-hoc 签名
6. **Git 提交推送**：`git add -A && git commit -m "v版本号" && git tag v版本号 && git push origin main --tags`
7. **发布到公开 repo**：使用 `gh release create` 发布到 `lifedever/health-tick-release`，上传两个 DMG，release notes 用中文
8. **清理临时文件**

## Release Notes 模板

```
## HealthTick v{VERSION}

### 下载
- **Apple Silicon (M1/M2/M3/M4)**: `HealthTick-v{VERSION}-Apple-Silicon.dmg`
- **Intel**: `HealthTick-v{VERSION}-Intel.dmg`

### 安装方式
打开 `.dmg` 文件，将 HealthTick 拖入 Applications 文件夹。
首次打开请前往 **系统设置 → 隐私与安全性** 点击"仍要打开"。
```

## 关键路径

- 版本号：`Sources/Info.plist` 中的 `CFBundleShortVersionString` 和 `CFBundleVersion`
- arm64 binary：`.build/arm64-apple-macosx/release/HealthTick`
- x86_64 binary：`.build/x86_64-apple-macosx/release/HealthTick`
- App 资源：`Sources/Resources/`
- 公开发布 repo：`lifedever/health-tick-release`

## 注意事项

- 发版前检查 tag 是否已存在，避免冲突
- 不要运行 build.sh 或替换本地 app
- 使用 `pkill -f "HealthTick Dev.app"` 终止 dev 版，不要用 `killall HealthTick`
- 临时文件放在 `/tmp/health-tick-release-{VERSION}/`
