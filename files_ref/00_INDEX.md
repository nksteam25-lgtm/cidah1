# CIDAH / Bina — Canonical Product Set

**גרסה:** 3.0 (סט קנוני מאוחד)
**תאריך:** 24 אפריל 2026
**המטרה:** הגדרה טכנית וחווייתית של שכבת ה-Brain + Search של בינה (טלגרם),
מוכן להעתקה ל-CIDAH כשהתשתית תהיה בשלה.

---

## איך לקרוא את הסט הזה

**4 מסמכים. הירככיים. כל אחד מניח את הקודם לו.**

| # | מסמך | תפקיד | מי קורא |
|---|---|---|---|
| **0** | Ground Zero + UX | נקודת התחלה, לשוניות, חוויה | כולם |
| **1** | המטריצה הטכנית | מוחות, מסלולים, configs | מפתח / קוד |
| **2** | מוח החיפוש | orchestration של כלים (layer על 0+1) | מפתח / קוד |
| **3** | Anthropic API Pure | מראה של 1 ל-CLI, בלי חיפוש | מפתחים ב-CLI |

---

## עקרונות אבות (חלים על כל הסט)

1. **Sonnet 4.6 הוא ה-default הקנוני.**
 גם אם Anthropic משנים ברירות מחדל, שלנו נשאר Sonnet.

2. **מסלול ידני = ברירת המחדל הקנונית.**
 המערכת לא חוטפת משתמש למסלול בלי לחיצה מפורשת.

3. **חיפוש auto הוא רוחבי.**
 חל על כל מסלול, כולל ידני. במקרה של סתירה — **מוצר 2 גובר**.

4. **Trigger מפורש של משתמש תמיד עובד.**
 גם במסלול "ללא חיפוש" — אם המשתמש אומר "תחפש ב-X", הכלי מופעל.

5. **Intent detection לפי מהות, לא מילים.**
 המוח מזהה כוונת חיפוש לפי משמעות השאלה.

6. **Tool descriptions = DNA של ההחלטה.**
 איכות ה-description בכל כלי קובעת אם המוח יבחר בו נכון.

7. **Parallel כ-default אגרסיבי.**
 Sequential רק עם dependency מוכח.

8. **שקיפות מלאה.**
 Status bar תמיד גלוי. כל tool call מוצג. כל שינוי מוצג. אין "שקט".

9. **Measure, adjust.**
 כל החלטה נרשמת ב-audit. סקירה דו-שבועית.

10. **Server Tools (Anthropic) + Local Tools (Hostinger) — 2 שכבות נפרדות, שילוב חלק.**

---

## הירככיית עדיפות החלטה

בכל נקודת החלטה במערכת — הסדר הזה נשמר:

```
1. User explicit override     ← גבוה ביותר
 (מסלול / מוח / כלי / trigger מפורש)
2. Active route configuration
 (preset של המסלול הפעיל)
3. Intent detection
 (הפעלת כלי לפי מהות השאלה)
4. System defaults
 (Sonnet 4.6, thinking off, effort high, manual route) ← נמוך ביותר
```

---

## מקרא טרמינולוגי קנוני

| מונח | משמעות |
|---|---|
| **מוח** | מודל + thinking config + effort (ב-Anthropic speak: model configuration) |
| **מסלול** | preset של מוח + כלים + orchestration pattern |
| **ידני** | מסלול ברירת מחדל: Sonnet 4.6 סולו |
| **כלי** | tool (server או local) |
| **Server tool** | כלי שרץ על Anthropic (web_search, web_fetch, code_execution, tool_search) |
| **Local tool** | כלי שרץ על Hostinger שלנו (meili, scrape, crawl, memory, nevo, takdin) |
| **Intent detection** | זיהוי אוטומטי של הצורך בכלי, לפי מהות השאלה |
| **Trigger מפורש** | המשתמש אמר במפורש "תחפש ב-X" |
| **Preset חיפוש** | קבוצת כלים מוגדרת מראש לשימוש מיידי |
| **Effort** | רמת המאמץ של המודל — low/medium/high/xhigh/max |
| **Adaptive thinking** | המוח מחליט לבד כמה לחשוב (Opus 4.7 בלבד) |
| **Manual budget** | המפתח קובע budget_tokens מפורש (Haiku + Opus 4.6) |

---

## סיכום ההבדלים בין המוצרים — מבט-על

| שאלה | מוצר 0 | מוצר 1 | מוצר 2 | מוצר 3 |
|---|---|---|---|---|
| **מי הקהל?** | משתמש-קצה | מפתח | מפתח | מפתח |
| **איפה רץ?** | Telegram | Telegram | Telegram | Claude Code CLI |
| **חיפוש?** | ✅ רוחבי | ✅ לפי מסלול | ✅ שכבת orchestration | ❌ (בלי) |
| **UI?** | ✅ 4 לשוניות | — | — | CLI + `/commands` |
| **שולט במסלול?** | דרך לשונית | דרך config | חל על כולם | דרך `/model` / subagents |

---

**סוף מסמך 00 — הפתיחה הקנונית.**
**המשך במסמכים 0, 1, 2, 3.**
