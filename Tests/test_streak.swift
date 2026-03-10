#!/usr/bin/env swift
import Foundation
import SQLite3

// MARK: - Test helpers

var testCount = 0
var passCount = 0
var failCount = 0

func assertEqual(_ actual: Int, _ expected: Int, _ msg: String, file: String = #file, line: Int = #line) {
    testCount += 1
    if actual == expected {
        passCount += 1
        print("  PASS: \(msg)")
    } else {
        failCount += 1
        print("  FAIL: \(msg) -- expected \(expected), got \(actual) (line \(line))")
    }
}

func dateStr(_ daysAgo: Int) -> String {
    let fmt = DateFormatter()
    fmt.dateFormat = "yyyy-MM-dd"
    return fmt.string(from: Calendar.current.date(byAdding: .day, value: -daysAgo, to: Date())!)
}

func todayString() -> String { dateStr(0) }

// MARK: - Database helpers

func openDB() -> OpaquePointer? {
    var db: OpaquePointer?
    sqlite3_open(":memory:", &db)
    sqlite3_exec(db, """
        CREATE TABLE records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL
        );
        CREATE INDEX idx_records_date ON records(date);
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            work_start TEXT NOT NULL,
            work_end TEXT,
            work_minutes INTEGER NOT NULL,
            break_start TEXT,
            break_end TEXT,
            break_minutes INTEGER NOT NULL,
            break_actual_seconds INTEGER,
            skipped INTEGER NOT NULL DEFAULT 0,
            daily_goal INTEGER NOT NULL
        );
        CREATE INDEX idx_sessions_date ON sessions(date);
    """, nil, nil, nil)
    return db
}

func addRecords(_ db: OpaquePointer?, date: String, count: Int) {
    let now = ISO8601DateFormatter().string(from: Date())
    for _ in 0..<count {
        sqlite3_exec(db, "INSERT INTO records (timestamp, date) VALUES ('\(now)', '\(date)')", nil, nil, nil)
    }
}

func addSession(_ db: OpaquePointer?, date: String, goal: Int) {
    let now = ISO8601DateFormatter().string(from: Date())
    sqlite3_exec(db, "INSERT INTO sessions (date, work_start, work_minutes, break_minutes, daily_goal) VALUES ('\(date)', '\(now)', 60, 2, \(goal))", nil, nil, nil)
}

// MARK: - streakDays (with per-day goal from sessions)

func streakDays(_ db: OpaquePointer?, goal: Int) -> Int {
    var stmt: OpaquePointer?
    let sql = """
        SELECT r.date, r.cnt, COALESCE(s.goal, \(goal)) as day_goal
        FROM (SELECT date, COUNT(*) as cnt FROM records GROUP BY date) r
        LEFT JOIN (SELECT date, daily_goal as goal FROM sessions GROUP BY date HAVING id = MAX(id)) s ON r.date = s.date
        ORDER BY r.date DESC
        """
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return 0 }
    defer { sqlite3_finalize(stmt) }

    let today = todayString()
    var streak = 0

    while sqlite3_step(stmt) == SQLITE_ROW {
        let ds = String(cString: sqlite3_column_text(stmt, 0))
        let cnt = Int(sqlite3_column_int(stmt, 1))
        let dayGoal = Int(sqlite3_column_int(stmt, 2))

        if ds == today && cnt < dayGoal { continue }

        if cnt >= dayGoal {
            streak += 1
        } else {
            break
        }
    }

    return streak
}

// MARK: - maxStreakDays (with per-day goal from sessions)

func maxStreakDays(_ db: OpaquePointer?, goal: Int) -> Int {
    var stmt: OpaquePointer?
    let sql = """
        SELECT r.date, r.cnt, COALESCE(s.goal, \(goal)) as day_goal
        FROM (SELECT date, COUNT(*) as cnt FROM records GROUP BY date) r
        LEFT JOIN (SELECT date, daily_goal as goal FROM sessions GROUP BY date HAVING id = MAX(id)) s ON r.date = s.date
        ORDER BY r.date
        """
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return 0 }
    defer { sqlite3_finalize(stmt) }
    var maxS = 0, curS = 0

    while sqlite3_step(stmt) == SQLITE_ROW {
        let cnt = Int(sqlite3_column_int(stmt, 1))
        let dayGoal = Int(sqlite3_column_int(stmt, 2))
        if cnt >= dayGoal {
            curS += 1
            maxS = max(maxS, curS)
        } else {
            curS = 0
        }
    }

    return maxS
}

// MARK: - Tests

print("=== streakDays basic tests ===\n")

// 1. Empty
do {
    let db = openDB()
    assertEqual(streakDays(db, goal: 3), 0, "1. empty db -> 0")
    sqlite3_close(db)
}

// 2. Today met
do {
    let db = openDB()
    addRecords(db, date: dateStr(0), count: 3)
    addSession(db, date: dateStr(0), goal: 3)
    assertEqual(streakDays(db, goal: 3), 1, "2. today met -> 1")
    sqlite3_close(db)
}

// 3. Today in progress, yesterday met
do {
    let db = openDB()
    addRecords(db, date: dateStr(0), count: 1)
    addSession(db, date: dateStr(0), goal: 3)
    addRecords(db, date: dateStr(1), count: 3)
    addSession(db, date: dateStr(1), goal: 3)
    assertEqual(streakDays(db, goal: 3), 1, "3. today in-progress, yesterday met -> 1")
    sqlite3_close(db)
}

// 4. Today no records, yesterday met
do {
    let db = openDB()
    addRecords(db, date: dateStr(1), count: 3)
    addSession(db, date: dateStr(1), goal: 3)
    assertEqual(streakDays(db, goal: 3), 1, "4. today no records, yesterday met -> 1")
    sqlite3_close(db)
}

// 5. Two days met
do {
    let db = openDB()
    addRecords(db, date: dateStr(1), count: 3)
    addSession(db, date: dateStr(1), goal: 3)
    addRecords(db, date: dateStr(2), count: 3)
    addSession(db, date: dateStr(2), goal: 3)
    assertEqual(streakDays(db, goal: 3), 2, "5. 2-day streak -> 2")
    sqlite3_close(db)
}

// 6. Today in progress, yesterday NOT met -> break
do {
    let db = openDB()
    addRecords(db, date: dateStr(0), count: 1)
    addSession(db, date: dateStr(0), goal: 3)
    addRecords(db, date: dateStr(1), count: 1)
    addSession(db, date: dateStr(1), goal: 3)
    assertEqual(streakDays(db, goal: 3), 0, "6. today in-progress, yesterday not met -> 0")
    sqlite3_close(db)
}

// 7. No records for several days, old record met
do {
    let db = openDB()
    addRecords(db, date: dateStr(5), count: 3)
    addSession(db, date: dateStr(5), goal: 3)
    assertEqual(streakDays(db, goal: 3), 1, "7. 5 days ago met, no records since -> 1")
    sqlite3_close(db)
}

// 8. Long streak: 7 days met
do {
    let db = openDB()
    for i in 1...7 {
        addRecords(db, date: dateStr(i), count: 3)
        addSession(db, date: dateStr(i), goal: 3)
    }
    assertEqual(streakDays(db, goal: 3), 7, "8. 7-day streak -> 7")
    sqlite3_close(db)
}

// 9. Leave scenario: 3 days no app, before that 5 days met
do {
    let db = openDB()
    for i in 4...8 {
        addRecords(db, date: dateStr(i), count: 3)
        addSession(db, date: dateStr(i), goal: 3)
    }
    assertEqual(streakDays(db, goal: 3), 5, "9. 3 days no app, 5-day streak -> 5")
    sqlite3_close(db)
}

print("\n=== Goal change tests (KEY FIX) ===\n")

// 10. User's exact scenario: yesterday goal=5 done=5, today goal=6 done=3
do {
    let db = openDB()
    addRecords(db, date: dateStr(1), count: 5)
    addSession(db, date: dateStr(1), goal: 5)
    addRecords(db, date: dateStr(0), count: 3)
    addSession(db, date: dateStr(0), goal: 6)
    let streak = streakDays(db, goal: 6)
    assertEqual(streak, 1, "10. yesterday goal=5 done=5, today goal=6 in-progress -> 1")
    sqlite3_close(db)
}

// 11. Goal changed mid-streak: day3 goal=3 done=3, day2 goal=5 done=5, day1 goal=8 done=4
do {
    let db = openDB()
    addRecords(db, date: dateStr(3), count: 3)
    addSession(db, date: dateStr(3), goal: 3)
    addRecords(db, date: dateStr(2), count: 5)
    addSession(db, date: dateStr(2), goal: 5)
    addRecords(db, date: dateStr(1), count: 4)
    addSession(db, date: dateStr(1), goal: 8) // not met!
    let streak = streakDays(db, goal: 8)
    assertEqual(streak, 0, "11. yesterday goal=8 done=4 -> break -> 0")
    sqlite3_close(db)
}

// 12. Goal lowered: yesterday goal=10 done=6 (not met), but if current goal=5 it should still use day's goal
do {
    let db = openDB()
    addRecords(db, date: dateStr(1), count: 6)
    addSession(db, date: dateStr(1), goal: 10)
    let streak = streakDays(db, goal: 5)
    assertEqual(streak, 0, "12. yesterday goal=10 done=6 -> not met even with current goal=5 -> 0")
    sqlite3_close(db)
}

// 13. Goal raised today, past days all met their own goals
do {
    let db = openDB()
    addRecords(db, date: dateStr(3), count: 3)
    addSession(db, date: dateStr(3), goal: 3)
    addRecords(db, date: dateStr(2), count: 4)
    addSession(db, date: dateStr(2), goal: 4)
    addRecords(db, date: dateStr(1), count: 5)
    addSession(db, date: dateStr(1), goal: 5)
    let streak = streakDays(db, goal: 8) // current goal=8, but past days had their own goals
    assertEqual(streak, 3, "13. goal raised today, past days all met own goals -> 3")
    sqlite3_close(db)
}

// 14. No sessions for old data (COALESCE fallback to current goal)
do {
    let db = openDB()
    addRecords(db, date: dateStr(1), count: 5)
    // no session record for this day
    let streak = streakDays(db, goal: 3)
    assertEqual(streak, 1, "14. no session data, fallback to current goal -> 1")
    sqlite3_close(db)
}

// 15. No sessions, fallback, not met
do {
    let db = openDB()
    addRecords(db, date: dateStr(1), count: 2)
    let streak = streakDays(db, goal: 3)
    assertEqual(streak, 0, "15. no session data, fallback goal=3, done=2 -> 0")
    sqlite3_close(db)
}

print("\n=== maxStreakDays tests ===\n")

// 16. Max streak with per-day goals
do {
    let db = openDB()
    for i in 1...5 {
        addRecords(db, date: dateStr(i), count: 3)
        addSession(db, date: dateStr(i), goal: 3)
    }
    assertEqual(maxStreakDays(db, goal: 3), 5, "16. max streak 5 -> 5")
    sqlite3_close(db)
}

// 17. Max streak respects per-day goal changes
do {
    let db = openDB()
    addRecords(db, date: dateStr(5), count: 3)
    addSession(db, date: dateStr(5), goal: 3) // met
    addRecords(db, date: dateStr(4), count: 3)
    addSession(db, date: dateStr(4), goal: 5) // NOT met (3 < 5)
    addRecords(db, date: dateStr(3), count: 5)
    addSession(db, date: dateStr(3), goal: 5) // met
    addRecords(db, date: dateStr(2), count: 5)
    addSession(db, date: dateStr(2), goal: 5) // met
    addRecords(db, date: dateStr(1), count: 5)
    addSession(db, date: dateStr(1), goal: 5) // met
    assertEqual(maxStreakDays(db, goal: 5), 3, "17. max streak with goal change break -> 3")
    sqlite3_close(db)
}

// 18. Max streak with user's scenario
do {
    let db = openDB()
    addRecords(db, date: dateStr(1), count: 5)
    addSession(db, date: dateStr(1), goal: 5) // met
    addRecords(db, date: dateStr(0), count: 3)
    addSession(db, date: dateStr(0), goal: 6) // today not met, but current goal=6
    assertEqual(maxStreakDays(db, goal: 6), 1, "18. max streak user scenario -> 1")
    sqlite3_close(db)
}

// MARK: - Summary

print("\n============================")
print("Total: \(testCount), Passed: \(passCount), Failed: \(failCount)")
if failCount > 0 {
    print("SOME TESTS FAILED!")
    exit(1)
} else {
    print("ALL TESTS PASSED!")
}
