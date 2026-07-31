# Short Link Status Explanation

The system uses **status** values to control whether a short link can be accessed. Here's what each status means:

## Status Values

### 1. **`active`** (Default)
- **Meaning**: The link is working and can be redirected
- **When set**: Automatically set when a new link is created
- **Redirect behavior**: Returns `302 Found` → redirects to `original_url`
- **Requirements**: 
  - `status = "active"` 
  - AND `expires_at` is either `NULL` (permanent) or in the future
- **Can be changed**: Yes, via the disable API endpoint

### 2. **`disabled`**
- **Meaning**: The link was manually disabled by a user/admin
- **When set**: When someone calls `POST /api/links/{code}/disable`
- **Redirect behavior**: Redirects (`302`) to the friendly `/404.html` page
- **Can be changed**: Currently no API to re-enable (would require direct DB update)
- **Note**: Once disabled, the code can **never be reused** (per project rules)

### 3. **`blocked`**
- **Meaning**: The link was blocked (e.g., for policy violations, spam, etc.)
- **When set**: Currently only via direct database update (no API endpoint yet)
- **Redirect behavior**: Redirects (`302`) to the friendly `/404.html` page
- **Can be changed**: Only via direct database update
- **Note**: Once blocked, the code can **never be reused** (per project rules)

### 4. **`expired`** (Computed, not stored)
- **Meaning**: The link's `expires_at` date/time has passed
- **When set**: This is **not a stored status** - it's computed from `expires_at`
- **How it works**: 
  - If `expires_at` is `NULL` → never expires (permanent)
  - If `expires_at <= now()` → expired
- **Redirect behavior**: Redirects (`302`) to the friendly `/404.html` page
- **Can be changed**: No - expiration is based on time, cannot be undone
- **Note**: The `status` field remains `"active"`, but the link is treated as expired

## Status Flow Diagram

```
New Link Created
    ↓
status = "active"
    ↓
    ├─→ expires_at = NULL → Permanent (always active)
    │
    └─→ expires_at = future date → Active until that date
            ↓
        (time passes)
            ↓
        expires_at <= now() → Expired (302 → /404.html)
            ↓
        (status still "active" but treated as expired)

Manual Actions:
    ↓
POST /api/links/{code}/disable
    ↓
status = "disabled" → 302 → /404.html

Direct DB Update:
    ↓
status = "blocked" → 302 → /404.html
```

## Redirect Behavior Summary

| Status | expires_at | Redirect Result | HTTP Code |
|--------|------------|----------------|-----------|
| `active` | `NULL` (permanent) | ✅ Redirects to URL | `302 Found` |
| `active` | Future date | ✅ Redirects to URL | `302 Found` |
| `active` | Past date | ❌ Expired | `302` → `/404.html` |
| `disabled` | Any | ❌ Not found | `302` → `/404.html` |
| `blocked` | Any | ❌ Not found | `302` → `/404.html` |
| Not in DB | - | ❌ Not found | `302` → `/404.html` |
| Reserved code | - | ❌ Not found | `302` → `/404.html` |

## Important Notes

1. **Never Deleted**: Links are never deleted from the database. Status changes control access instead.

2. **Codes Never Reused**: Once a code is used (even if disabled/blocked/expired), it can **never be reused**. This is enforced by the database unique constraint.

3. **Expired vs Disabled** (both redirect visitors to `/404.html`):
   - **Expired**: Time-based, `status` still shows as `"active"`
   - **Disabled**: Manual action, `status` is `"disabled"`

4. **Filtering**: In the Manage page, you can filter by:
   - `active` - Shows only active, non-expired links
   - `expired` - Shows links where `expires_at <= now()`
   - `disabled` - Shows links with `status = "disabled"`
   - `blocked` - Shows links with `status = "blocked"`
   - `all` - Shows all links regardless of status

5. **Computed Field**: The API response includes `is_expired: boolean` to help distinguish between active and expired links (since expired links still have `status = "active"`).

## Example Scenarios

**Scenario 1: Permanent Link**
- Created: `status = "active"`, `expires_at = NULL`
- Result: Always redirects (302) until manually disabled

**Scenario 2: Temporary Link**
- Created: `status = "active"`, `expires_at = "2026-12-31 23:59:59"`
- Before expiry: Redirects (302)
- After expiry: Redirects (302) to `/404.html`
- Status field: Still shows `"active"` but `is_expired = true`

**Scenario 3: Disabled Link**
- Created: `status = "active"`
- User disables: `status = "disabled"`
- Result: Redirects (302) to `/404.html`
- Code: Can never be reused

**Scenario 4: Blocked Link**
- Created: `status = "active"`
- Admin blocks: `status = "blocked"` (via DB)
- Result: Redirects (302) to `/404.html`
- Code: Can never be reused
