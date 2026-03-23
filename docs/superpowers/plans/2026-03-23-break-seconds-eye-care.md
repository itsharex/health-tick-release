# Break Seconds + 20-20-20 Eye Care Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow break duration down to 20 seconds and add a 20-20-20 eye care mode toggle that locks work=20min, break=20s, breakConfirm=off.

**Architecture:** Rename `breakMinutes` → `breakSeconds` throughout, add `eyeCareMode` bool + saved fields to AppConfig, add DB migration for old→new key, add toggle UI in AppTab below daily goal slider.

**Tech Stack:** Swift, SwiftUI, SQLite

**Spec:** `docs/superpowers/specs/2026-03-23-break-seconds-design.md`

---

### Task 1: Add localization strings

**Files:**
- Modify: `Sources/Strings.swift`

- [ ] **Step 1: Add new strings to `L` struct**

Add after `unitMinutes` (line ~100):

```swift
static var unitSeconds: String { isZh ? "秒" : "s" }
static var eyeCareMode: String { isZh ? "20-20-20 护眼模式" : "20-20-20 Eye Care" }
static var eyeCareDesc: String { isZh ? "每 20 分钟远眺 20 秒，保护视力" : "Look 20 feet away for 20s every 20 min" }
```

Update help text (line ~291) for break duration range:

```swift
static var helpFeatureBreakDuration: String { isZh ? "每次休息的倒计时时间，范围 20 秒至 15 分钟。" : "Break countdown duration, range 20 seconds to 15 minutes." }
```

- [ ] **Step 2: Build to verify no compile errors**

Run: `swift build 2>&1 | tail -5`
Expected: Build Succeeded

- [ ] **Step 3: Commit**

```bash
git add Sources/Strings.swift
git commit -m "feat: add eye care mode localization strings"
```

---

### Task 2: Rename breakMinutes → breakSeconds in AppConfig

**Files:**
- Modify: `Sources/AppState.swift:136-169`

- [ ] **Step 1: Update AppConfig struct**

Replace `var breakMinutes: Int = 2` with new fields:

```swift
var breakSeconds: Int = 120            // 默认 2 分钟 = 120 秒
var eyeCareMode: Bool = false
var savedWorkMinutes: Int = 60
var savedBreakSeconds: Int = 120
var savedBreakConfirm: Bool = true
```

- [ ] **Step 2: Update all breakMinutes references in AppState.swift**

There are 4 references to update:

1. Line ~361 `startSession` call:
```swift
// breakMinutes: config.breakMinutes → breakSeconds: config.breakSeconds
currentSessionId = db.startSession(workMinutes: config.workMinutes, breakSeconds: config.breakSeconds, dailyGoal: config.dailyGoal)
```

2. Line ~378 same pattern (after confirmation restart):
```swift
currentSessionId = db.startSession(workMinutes: config.workMinutes, breakSeconds: config.breakSeconds, dailyGoal: config.dailyGoal)
```

3. Line ~405 same pattern (new interval):
```swift
currentSessionId = db.startSession(workMinutes: config.workMinutes, breakSeconds: config.breakSeconds, dailyGoal: config.dailyGoal)
```

4. Line ~474 break duration calculation:
```swift
// config.breakMinutes * 60 → config.breakSeconds
let secs = config.breakSeconds
```

5. Line ~717 config change detection:
```swift
// newConfig.breakMinutes != old.breakMinutes → newConfig.breakSeconds != old.breakSeconds
(newConfig.breakSeconds != old.breakSeconds && phase == .breaking)
```

- [ ] **Step 3: Build to check — will fail because Database.swift still uses old signature**

Run: `swift build 2>&1 | tail -10`
Expected: Compile error on `db.startSession` signature mismatch

- [ ] **Step 4: Commit (WIP, will compile after Task 3)**

```bash
git add Sources/AppState.swift
git commit -m "refactor: rename breakMinutes to breakSeconds in AppConfig and AppState"
```

---

### Task 3: Update Database.swift

**Files:**
- Modify: `Sources/Database.swift`

- [ ] **Step 1: Update config defaults array (line ~66)**

Replace:
```swift
("break_minutes", "2"),
```
With:
```swift
("break_seconds", "120"),
("eye_care_mode", "0"),
("saved_work_minutes", "60"),
("saved_break_seconds", "120"),
("saved_break_confirm", "1"),
```

- [ ] **Step 2: Update loadConfig (line ~102)**

Replace the `case "break_minutes"` line:
```swift
case "break_minutes":
    // Migration: old key → convert minutes to seconds
    config.breakSeconds = (Int(value) ?? 2) * 60
case "break_seconds": config.breakSeconds = Int(value) ?? 120
case "eye_care_mode": config.eyeCareMode = value == "1"
case "saved_work_minutes": config.savedWorkMinutes = Int(value) ?? 60
case "saved_break_seconds": config.savedBreakSeconds = Int(value) ?? 120
case "saved_break_confirm": config.savedBreakConfirm = value == "1"
```

- [ ] **Step 3: Update saveConfig (line ~156)**

Replace:
```swift
exec("INSERT OR REPLACE INTO config (key, value) VALUES ('break_minutes', '\(config.breakMinutes)')")
```
With:
```swift
exec("INSERT OR REPLACE INTO config (key, value) VALUES ('break_seconds', '\(config.breakSeconds)')")
exec("INSERT OR REPLACE INTO config (key, value) VALUES ('eye_care_mode', '\(config.eyeCareMode ? "1" : "0")')")
exec("INSERT OR REPLACE INTO config (key, value) VALUES ('saved_work_minutes', '\(config.savedWorkMinutes)')")
exec("INSERT OR REPLACE INTO config (key, value) VALUES ('saved_break_seconds', '\(config.savedBreakSeconds)')")
exec("INSERT OR REPLACE INTO config (key, value) VALUES ('saved_break_confirm', '\(config.savedBreakConfirm ? "1" : "0")')")
```

Also add migration cleanup — delete old key after first save. Add at the end of `saveConfig`:
```swift
exec("DELETE FROM config WHERE key = 'break_minutes'")
```

- [ ] **Step 4: Update startSession signature (line ~359)**

Replace:
```swift
func startSession(workMinutes: Int, breakMinutes: Int, dailyGoal: Int) -> Int64 {
    let now = ISO8601DateFormatter().string(from: Date())
    let today = Self.todayString()
    let sql = "INSERT INTO sessions (date, work_start, work_minutes, break_minutes, daily_goal) VALUES ('\(today)', '\(now)', \(workMinutes), \(breakMinutes), \(dailyGoal))"
```
With:
```swift
func startSession(workMinutes: Int, breakSeconds: Int, dailyGoal: Int) -> Int64 {
    let now = ISO8601DateFormatter().string(from: Date())
    let today = Self.todayString()
    let breakMinutesValue = max(1, breakSeconds / 60)  // sessions table stores minutes, min 1
    let sql = "INSERT INTO sessions (date, work_start, work_minutes, break_minutes, daily_goal) VALUES ('\(today)', '\(now)', \(workMinutes), \(breakMinutesValue), \(dailyGoal))"
```

- [ ] **Step 5: Build to verify**

Run: `swift build 2>&1 | tail -5`
Expected: Build Succeeded

- [ ] **Step 6: Commit**

```bash
git add Sources/Database.swift
git commit -m "refactor: rename break_minutes to break_seconds in database layer with migration"
```

---

### Task 4: Update BreakOverlay.swift

**Files:**
- Modify: `Sources/BreakOverlay.swift:24-29`

- [ ] **Step 1: Update timerProgress calculation**

Replace:
```swift
let total = state.config.breakMinutes * 60
```
With:
```swift
let total = state.config.breakSeconds
```

- [ ] **Step 2: Build to verify**

Run: `swift build 2>&1 | tail -5`
Expected: Build Succeeded

- [ ] **Step 3: Commit**

```bash
git add Sources/BreakOverlay.swift
git commit -m "refactor: use breakSeconds directly in break overlay progress"
```

---

### Task 5: Update OnboardingView.swift

**Files:**
- Modify: `Sources/OnboardingView.swift`

- [ ] **Step 1: Update break duration state and slider**

Change state declaration (line ~19):
```swift
@State private var breakDuration: Double = 120  // seconds
```

Update the slider in step3View (line ~302-303) — replace the break slider section:
```swift
VStack(spacing: 6) {
    HStack {
        Image(systemName: "cup.and.saucer.fill")
            .foregroundStyle(.orange)
            .frame(width: 18)
        Text(L.onboardingBreakDuration)
            .font(.callout)
        Spacer()
        Text(formatBreakDuration(Int(breakDuration)))
            .font(.callout.bold().monospacedDigit())
            .foregroundStyle(.orange)
            .frame(width: 80, alignment: .trailing)
    }
    Slider(value: $breakDuration, in: 20...900, step: 10)
        .tint(.orange)
}
```

Add helper function in OnboardingView:
```swift
private func formatBreakDuration(_ seconds: Int) -> String {
    if seconds < 60 {
        return "\(seconds) \(L.unitSeconds)"
    } else if seconds % 60 == 0 {
        return "\(seconds / 60) \(L.unitMinutes)"
    } else {
        return "\(seconds / 60)\(L.unitMinutes)\(seconds % 60)\(L.unitSeconds)"
    }
}
```

- [ ] **Step 2: Update applySettings (line ~378)**

Replace:
```swift
state.config.breakMinutes = Int(breakDuration)
```
With:
```swift
state.config.breakSeconds = Int(breakDuration)
```

- [ ] **Step 3: Build to verify**

Run: `swift build 2>&1 | tail -5`
Expected: Build Succeeded

- [ ] **Step 4: Commit**

```bash
git add Sources/OnboardingView.swift
git commit -m "feat: update onboarding to support seconds-level break duration"
```

---

### Task 6: Update SettingsView.swift — break slider + eye care toggle

**Files:**
- Modify: `Sources/SettingsView.swift:346-580`

- [ ] **Step 1: Add formatBreakDuration helper**

Add a helper function to SettingsView (or AppTab) for formatting:

```swift
private func formatBreakDuration(_ seconds: Int) -> String {
    if seconds < 60 {
        return "\(seconds) \(L.unitSeconds)"
    } else if seconds % 60 == 0 {
        return "\(seconds / 60) \(L.unitMinutes)"
    } else {
        return "\(seconds / 60)\(L.unitMinutes)\(seconds % 60)\(L.unitSeconds)"
    }
}
```

- [ ] **Step 2: Replace break duration slider in AppTab**

Replace the existing break slider `sliderRow(icon: "cup.and.saucer.fill", ...)` with a custom VStack that formats seconds properly:

```swift
VStack(spacing: 4) {
    HStack {
        Image(systemName: "cup.and.saucer.fill").font(.callout).foregroundStyle(.orange).frame(width: 20)
        Text(L.breakDuration).font(.callout)
        Spacer()
        Text(formatBreakDuration(state.config.breakSeconds))
            .font(.callout.monospacedDigit().bold())
            .foregroundStyle(.orange)
            .frame(width: 90, alignment: .trailing)
    }
    Slider(value: Binding(
        get: { Double(state.config.breakSeconds) },
        set: { state.config.breakSeconds = Int($0) }
    ), in: 20...900, step: 10).tint(.orange)
}
.opacity(state.config.eyeCareMode ? 0.5 : 1.0)
.disabled(state.config.eyeCareMode)
```

- [ ] **Step 3: Add opacity/disabled to work duration slider when eye care is on**

Wrap the existing work duration `sliderRow` with modifiers:

```swift
sliderRow(icon: "deskclock.fill", label: L.workDuration, value: Binding(
    get: { Double(state.config.workMinutes) },
    set: { state.config.workMinutes = Int($0) }
), range: 1...120, unit: L.unitMinutes, color: .green)
.opacity(state.config.eyeCareMode ? 0.5 : 1.0)
.disabled(state.config.eyeCareMode)
```

- [ ] **Step 4: Add 20-20-20 eye care toggle below daily goal slider**

After the daily goal `sliderRow`, add:

```swift
Divider().padding(.vertical, 4)

VStack(spacing: 4) {
    HStack {
        Image(systemName: "eye").font(.callout).foregroundStyle(.cyan).frame(width: 20)
        Text(L.eyeCareMode).font(.callout)
        Spacer()
        Toggle("", isOn: Binding(
            get: { state.config.eyeCareMode },
            set: { newValue in
                if newValue {
                    // Save current values before locking
                    state.config.savedWorkMinutes = state.config.workMinutes
                    state.config.savedBreakSeconds = state.config.breakSeconds
                    state.config.savedBreakConfirm = state.config.breakConfirm
                    // Lock to 20-20-20
                    state.config.eyeCareMode = true
                    state.config.workMinutes = 20
                    state.config.breakSeconds = 20
                    state.config.breakConfirm = false
                } else {
                    // Restore saved values
                    state.config.eyeCareMode = false
                    state.config.workMinutes = state.config.savedWorkMinutes
                    state.config.breakSeconds = state.config.savedBreakSeconds
                    state.config.breakConfirm = state.config.savedBreakConfirm
                }
            }
        ))
        .toggleStyle(.switch)
        .labelsHidden()
    }
    Text(L.eyeCareDesc)
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.leading, 24)
}
```

- [ ] **Step 5: Build to verify**

Run: `swift build 2>&1 | tail -5`
Expected: Build Succeeded

- [ ] **Step 6: Commit**

```bash
git add Sources/SettingsView.swift
git commit -m "feat: add 20-20-20 eye care mode toggle and seconds-level break slider"
```

---

### Task 7: Update test files

**Files:**
- Modify: `Tests/test_time_logic.swift`
- Modify: `Tests/test_streak.swift`

- [ ] **Step 1: Check test files for breakMinutes references**

The sessions table schema in tests uses `break_minutes` column — this stays the same (table not changed). Check if any test references `config.breakMinutes` or `startSession(breakMinutes:)`.

If tests call `startSession`, update parameter name from `breakMinutes:` to `breakSeconds:` and adjust value (e.g., `2` → `120`).

- [ ] **Step 2: Build and run tests**

Run: `swift build 2>&1 | tail -5 && swift test 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add Tests/
git commit -m "test: update tests for breakSeconds parameter rename"
```

---

### Task 8: Build, test, and verify with dev app

- [ ] **Step 1: Full build**

Run: `swift build 2>&1 | tail -5`
Expected: Build Succeeded

- [ ] **Step 2: Run tests**

Run: `swift test 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 3: Build dev app and verify**

Run: `bash build.sh && open ~/Applications/HealthTick\ Dev.app`

Manual verification checklist:
- Settings → 计划 tab shows eye care toggle below daily goal
- Toggle ON: work=20min, break=20s, sliders disabled
- Toggle OFF: values restored to previous settings
- Break slider shows seconds format when < 60s
- Start a work session, verify timer works normally

- [ ] **Step 4: Commit any fixes if needed**
