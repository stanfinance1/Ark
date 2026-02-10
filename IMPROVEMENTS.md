# Reminder System Code Improvements

## Issues Found and Fixed

### 1. **Monthly Calculation Bug** ❌ → ✅
**Problem:** Original code added 30 days to calculate next month, which:
- Could skip months (Jan 31 + 30 days = Mar 2)
- Could land in wrong month
- Didn't handle day overflow (Jan 31 → Feb 31 invalid)

**Fix:** Use proper month arithmetic with calendar module:
```python
# Before (WRONG)
next_month = current_fire + timedelta(days=30)
return next_month.replace(day=day_of_month)

# After (CORRECT)
month = current_fire.month + 1
if month > 12:
    month = 1
    year += 1
max_day = calendar.monthrange(year, month)[1]
day = min(day_of_month, max_day)
return current_fire.replace(year=year, month=month, day=day)
```

### 2. **Code Duplication** ❌ → ✅
**Problem:** AM/PM time parsing logic duplicated 4 times (lines 202-212, 231-240, 262-273, 294-304)

**Fix:** Extract to helper function:
```python
def _parse_time(hour: int, minute: int, ampm: Optional[str]) -> Tuple[int, int]:
    """Convert 12-hour time with AM/PM to 24-hour format."""
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return hour, minute
```

### 3. **Weekly Calculation Complexity** ❌ → ✅
**Problem:** Nested if/else for handling same-day scheduling was confusing and error-prone

**Fix:** Simplified logic:
```python
# Before (CONFUSING)
if days_ahead == 0:
    fire_time = now.replace(...)
    if fire_time <= now:
        days_ahead = 7
    else:
        fire_time = now + timedelta(days=days_ahead)
        ...
else:
    fire_time = now + timedelta(days=days_ahead)
    ...

# After (CLEAR)
days_ahead = (day_num - now.weekday()) % 7
fire_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
if days_ahead == 0 and fire_time <= now:
    days_ahead = 7
fire_time = now + timedelta(days=days_ahead)
fire_time = fire_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
```

### 4. **Input Validation Missing** ❌ → ✅
**Problem:** No validation for invalid day_of_month (e.g., "monthly on the 32nd")

**Fix:** Added validation:
```python
if day_of_month < 1 or day_of_month > 31:
    return None, None
```

### 5. **Type Hints Compatibility** ❌ → ✅
**Problem:** Used `tuple[...]` syntax (Python 3.10+) instead of `Tuple[...]` (compatible with 3.7+)

**Fix:** Import and use `Tuple` from typing module

### 6. **Better Error Handling** ❌ → ✅
**Problem:** ValueError catch was too broad

**Fix:** More specific handling with calendar.monthrange for day overflow

## Performance Notes

✅ **Already Good:**
- Single database connection per operation (using context manager)
- Index on (next_fire_time, status) for fast queries
- 30-second scheduler interval balances responsiveness vs CPU usage

## No Changes Needed

✅ **User isolation** - Already correct (uses user_id from creator)
✅ **Database schema** - Well designed with proper indexes
✅ **Scheduler loop** - Simple and robust
✅ **Error handling in tools.py** - Already has try/catch

## Recommendation

Replace `reminders.py` with `reminders_improved.py` to fix the bugs, especially the monthly calculation bug which will cause incorrect scheduling.
