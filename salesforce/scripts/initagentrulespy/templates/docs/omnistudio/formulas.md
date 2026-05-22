# OmniStudio Formulas

OmniStudio formulas look like a single, unified mini-language across the suite, but they are **not**: the same `=FILTER(...)` expression that works in an Integration Procedure (IP) silently fails in an OmniScript (OS), and the same `=PMT(...)` that works in OS throws in an IP. The reason is that formulas are evaluated by **two completely different runtimes** depending on where you put them.

This doc gives you (1) the architectural model of why that split exists, (2) a category-by-category function reference, (3) the exclusivity matrix that tells you exactly what fails where, and (4) the {{ORG_NAME}} `PRM_FormulaProbe` IP for empirically validating list-formula behavior.

> Source-of-truth references: Salesforce Help, [OmniScript Functions](https://help.salesforce.com/s/articleView?id=xcloud.os_omniscript_functions.htm&type=5) and [Function Reference](https://help.salesforce.com/s/articleView?id=xcloud.os_function_reference.htm&type=5). The lists below are distilled from those pages and from the `propertySetConfig` of real OmniStudio metadata.

---

## Architectural summary: the OmniStudio formula split

In OmniStudio, the formula engine behaves differently depending on where the execution occurs. This dichotomy is rooted in the runtime environment:

- **Integration Procedures (IP) and Data Mappers / DataRaptors (DM/DR)** run **server-side**. Their formula engine is powered by Apex. It excels at array manipulation, list aggregations, and calling backend services.
- **OmniScripts (OS)** run **client-side** (in the browser). Their formula engine is powered by JavaScript (historically utilizing a library that mimics Excel functions). It excels at real-time UI updates, date manipulation, and conditional rendering.

Per the **server-side first** directive, complex calculations, array sorting, and heavy logical operations must be offloaded to IPs, leaving only lightweight UI-specific logic in the OS `SetValues` or `Formula` elements.

```mermaid
flowchart LR
    subgraph Browser [Browser tier]
        OS[OmniScript<br/>JS formula engine]
    end

    subgraph Server [Server tier]
        IP[Integration Procedure<br/>Apex formula engine]
        DR[DataRaptor<br/>Apex formula engine]
    end

    OS -- "list ops, FUNCTION()" -. forbidden .-> IP
    IP -- "PMT(), MOMENT()" -. forbidden .-> OS

    OS -. "supports" .- OSFns([Date math, financials,<br/>regex, JS-style strings])
    IP -. "supports" .- IPFns([Lists, type conv,<br/>Apex bridge FUNCTION])
```

When the same function name (e.g. `LISTSIZE`) appears to work in both runtimes, the two implementations behave subtly differently — the OS version operates on plain JS arrays and is unreliable for nested JSON; the IP/DR version operates on Apex `List` and is reliable. The Exclusivity Matrix later in this doc captures every known gotcha.

---

## Formula syntax basics

Every formula starts with `=`. References to JSON nodes use `%path%` merge syntax (see the merge field tables in [`omniscripts.md`](omniscripts.md#merge-field-syntax) and [`integration-procedures.md`](integration-procedures.md#merge-fields-and-the-payload)).

```text
=IF(ISBLANK(%FirstName%), "Anonymous", %FirstName%)
=ROUND(%Price% * 1.0825, 2)
=DATEDIFF(%StartDate%, %EndDate%)
=FILTER(%AccountList%, 'Status == "Active"')
```

A few common syntactic patterns:

| Pattern | Use |
|---------|-----|
| `=NULL` | Explicit null assignment in `Set Values` |
| `="literal"` | A string literal — note the equals sign is still required at the start |
| `=%FieldName%` | Pure pass-through of one JSON node into another |
| `=fn1(fn2(%a%), fn3(%b%))` | Nested function calls |
| `=IF(cond, then, else)` | Ternary conditional |
| Argument quoting in IP-only functions like `FILTER`/`SORTBY` | The condition string uses single quotes around its outer body and double-quoted comparison values: `FILTER(%list%, 'Status == "Active"')` |

The string-quoting rules are the most error-prone part of OmniStudio formulas. When in doubt, write the formula and test it through the [PRM_FormulaProbe IP](#probing-formula-behavior).

---

## Function reference (by category)

Each function is listed with where it works (OS = OmniScript, IP/DR = Integration Procedure / DataRaptor). Functions appearing in both runtimes generally have implementations that match for scalars but diverge for lists.

### Math

| Function | OS | IP/DR | Description | Example |
|----------|----|-------|-------------|---------|
| `ABS(n)` | ✅ | ✅ | Absolute value | `=ABS(-5)` → `5` |
| `CEILING(n)` | ✅ | ✅ | Round up | `=CEILING(2.3)` → `3` |
| `FLOOR(n)` | ✅ | ✅ | Round down | `=FLOOR(2.9)` → `2` |
| `ROUND(n, digits)` | ✅ | ✅ | Round to N decimals | `=ROUND(3.14159, 2)` → `3.14` |
| `MAX(a, b, ...)` | ✅ | ✅ | Largest argument | `=MAX(1, 2, 3)` → `3` |
| `MIN(a, b, ...)` | ✅ | ✅ | Smallest argument | `=MIN(1, 2, 3)` → `1` |
| `MOD(n, divisor)` | ✅ | ✅ | Remainder | `=MOD(10, 3)` → `1` |
| `POWER(base, exp)` | ✅ | ✅ | Exponentiation | `=POWER(2, 10)` → `1024` |
| `SQRT(n)` | ✅ | ✅ | Square root | `=SQRT(16)` → `4` |
| `EXP(n)` | ✅ | ✅ | e raised to n | `=EXP(1)` → `2.71828...` |
| `LN(n)` | ✅ | ✅ | Natural log | `=LN(2.71828)` → `1` |
| `LOG(n)` | ✅ | ✅ | Log base 10 | `=LOG(100)` → `2` |
| `RAND()` | ✅ | ✅ | Random in `[0, 1)` | `=RAND()` |

### Date and time

| Function | OS | IP/DR | Description | Example |
|----------|----|-------|-------------|---------|
| `TODAY()` / `%TODAY%` | ✅ | ✅ | Today's date | `=TODAY()` |
| `NOW()` / `%NOW%` | ✅ | ✅ | Current datetime | `=NOW()` |
| `DATE(y, m, d)` | ✅ | ✅ | Construct a date | `=DATE(2026, 1, 15)` |
| `DATEVALUE(text)` | ✅ | ✅ | Parse a date string | `=DATEVALUE("2026-01-15")` |
| `DATETIMEVALUE(text)` | ✅ | ✅ | Parse a datetime string | `=DATETIMEVALUE("2026-01-15T12:00:00Z")` |
| `DATEDIFF(d1, d2)` | ✅ | ✅ | Days between two dates | `=DATEDIFF(%Start%, %End%)` |
| `DATEDIFFINMINUTES(t1, t2)` | ✅ | ✅ | Minutes between two datetimes | `=DATEDIFFINMINUTES(%Start%, %End%)` |
| `ADDDAYS(d, n)` | ✅ | ✅ | Add N days | `=ADDDAYS(%TODAY%, 14)` |
| `ADDMONTHS(d, n)` | ✅ | ✅ | Add N months | `=ADDMONTHS(%StartDate%, 3)` |
| `ADDYEARS(d, n)` | ✅ | ✅ | Add N years | `=ADDYEARS(%TODAY%, -1)` |
| `AGE(birthdate)` | ✅ | ✅ | Years since birthdate | `=AGE(%Birthdate%)` |
| `DAY(d)` | ✅ | ✅ | Day-of-month (1–31) | `=DAY(%TODAY%)` |
| `MONTH(d)` | ✅ | ✅ | Month-of-year (1–12) | `=MONTH(%TODAY%)` |
| `YEAR(d)` | ✅ | ✅ | Year | `=YEAR(%TODAY%)` |
| `HOUR(t)` | ✅ | ✅ | Hour (0–23) | `=HOUR(%NOW%)` |
| `MINUTE(t)` | ✅ | ✅ | Minute (0–59) | `=MINUTE(%NOW%)` |
| `SECOND(t)` | ✅ | ✅ | Second (0–59) | `=SECOND(%NOW%)` |
| `WEEKDAY(d)` | ✅ | ✅ | Day-of-week (1=Sunday) | `=WEEKDAY(%TODAY%)` |
| `FORMATDATE(d, fmt)` | ✅ | ✅ | Format a date with a pattern | `=FORMATDATE(%TODAY%, "MM/dd/yyyy")` |
| `MOMENT(...)` | ✅ ⚠️ | ❌ | Wraps moment.js — deprecated, OS only, never use in IP | — |

### String

| Function | OS | IP/DR | Description | Example |
|----------|----|-------|-------------|---------|
| `CONCAT(a, b, ...)` | ✅ | ✅ | Concatenate | `=CONCAT(%First%, " ", %Last%)` |
| `LEN(s)` | ✅ | ✅ | String length | `=LEN(%Phone%)` |
| `LOWER(s)` | ✅ | ✅ | Lowercase | `=LOWER(%Email%)` |
| `UPPER(s)` | ✅ | ✅ | Uppercase | `=UPPER(%State%)` |
| `LEFT(s, n)` | ✅ | ✅ | First n characters | `=LEFT(%Code%, 3)` |
| `RIGHT(s, n)` | ✅ | ✅ | Last n characters | `=RIGHT(%Code%, 4)` |
| `MID(s, start, len)` | ✅ | ✅ | Substring (1-based) | `=MID(%SSN%, 6, 4)` |
| `SUBSTRING(s, start, end)` | ✅ | ✅ | Substring (0-based, half-open) | `=SUBSTRING(%Phone%, 0, 3)` |
| `TRIM(s)` | ✅ | ✅ | Strip leading/trailing whitespace | `=TRIM(%Input%)` |
| `REPLACE(s, find, replace)` | ✅ | ✅ | Replace all occurrences | `=REPLACE(%Phone%, "-", "")` |
| `SUBSTITUTE(s, old, new)` | ✅ | ✅ | Single substitution | `=SUBSTITUTE(%Text%, "foo", "bar")` |
| `CONTAINS(haystack, needle)` | ✅ | ✅ | Boolean: substring present? | `=CONTAINS(%Email%, "@")` |
| `BEGINS(s, prefix)` | ✅ | ✅ | Boolean: starts-with | `=BEGINS(%Code%, "PRM_")` |
| `ENDS(s, suffix)` | ✅ | ✅ | Boolean: ends-with | `=ENDS(%File%, ".pdf")` |
| `SPLIT(s, sep)` | ✅ | ✅ | Split into list | `=SPLIT(%CSV%, ",")` |
| `JOIN(list, sep)` | ⚠️ | ✅ | Concatenate list with separator (OS struggles with deeply-nested lists) | `=JOIN(%Tags%, ", ")` |
| `REVERSE(s)` | ✅ | ✅ | Reverse a string | `=REVERSE(%Word%)` |

### Logical / boolean

| Function | OS | IP/DR | Description | Example |
|----------|----|-------|-------------|---------|
| `IF(cond, then, else)` | ✅ | ✅ | Ternary | `=IF(%Age% >= 18, "Adult", "Minor")` |
| `AND(a, b, ...)` | ✅ | ✅ | All truthy | `=AND(%Active%, %Verified%)` |
| `OR(a, b, ...)` | ✅ | ✅ | Any truthy | `=OR(%Active%, %Pending%)` |
| `NOT(b)` | ✅ | ✅ | Boolean negation | `=NOT(%Pending%)` |
| `ISBLANK(v)` | ✅ | ✅ | True if null, undefined, or empty string | `=ISBLANK(%MiddleName%)` |
| `ISNOTBLANK(v)` | ✅ | ✅ | Inverse of `ISBLANK` | `=ISNOTBLANK(%Email%)` |
| `ISNULL(v)` | ✅ | ✅ | True if null only | `=ISNULL(%Field%)` |
| `ISNUMBER(v)` | ✅ | ✅ | Type check | `=ISNUMBER(%Input%)` |
| `ISTEXT(v)` | ✅ | ✅ | Type check | `=ISTEXT(%Input%)` |
| `ISDATE(v)` | ✅ | ✅ | Type check | `=ISDATE(%Input%)` |
| `EQUALS(a, b)` | ✅ | ✅ | Equality (same as `==`) | `=EQUALS(%Status%, "Active")` |

### List / array (IP/DR only)

These functions are the workhorses of server-side payload manipulation. They **do not work** in OS — see the Exclusivity Matrix.

| Function | OS | IP/DR | Description | Example |
|----------|----|-------|-------------|---------|
| `LIST(args...)` | ❌ | ✅ | Wraps args (or a node) as an Apex `List` | `=LIST(%singleObject%)` |
| `LISTSIZE(list)` | ❌ | ✅ | Count of elements | `=LISTSIZE(%Order:LineItems%)` |
| `FILTER(list, condition)` | ❌ | ✅ | Filter a list of objects by a condition string | `=FILTER(%Accounts%, 'Status == "Active"')` |
| `VLOOKUP(list1, list2, key1, key2)` | ❌ | ✅ | Cross-reference two lists, returning matching rows | `=VLOOKUP(%Contacts%, %Accounts%, 'AccountId', 'Id')` |
| `SORTBY(list, field, direction)` | ❌ | ✅ | Sort a list of objects | `=SORTBY(%Products%, 'Price', 'DESC')` |
| `INDEX(list, n)` | ❌ | ✅ | Get the nth element | `=INDEX(%List%, 0)` |
| `FIRST(list)` | ❌ | ✅ | First element (alias for `INDEX(list, 0)`) | `=FIRST(%List%)` |
| `LAST(list)` | ❌ | ✅ | Last element | `=LAST(%List%)` |
| `COUNT(list)` | ❌ | ✅ | Same as `LISTSIZE` | `=COUNT(%List%)` |
| `SUM(list, field)` | ❌ | ✅ | Sum of `field` across the list | `=SUM(%LineItems%, 'Amount')` |
| `AVG(list, field)` | ❌ | ✅ | Average | `=AVG(%LineItems%, 'Score')` |
| `MAXBY(list, field)` | ❌ | ✅ | Element with max value of `field` | `=MAXBY(%Bids%, 'Amount')` |
| `MINBY(list, field)` | ❌ | ✅ | Element with min value of `field` | `=MINBY(%Bids%, 'Amount')` |
| `DISTINCT(list, field)` | ❌ | ✅ | Distinct values of `field` | `=DISTINCT(%Tags%, 'Name')` |
| `UNION(a, b)` | ❌ | ✅ | List union | `=UNION(%ListA%, %ListB%)` |
| `INTERSECT(a, b)` | ❌ | ✅ | List intersection | `=INTERSECT(%ListA%, %ListB%)` |

### Type conversion (IP/DR only)

These are essential for safe payload construction. The OS engine is dynamically typed and rarely needs them; the Apex engine is strict and absolutely needs them.

| Function | OS | IP/DR | Description | Example |
|----------|----|-------|-------------|---------|
| `TOSTRING(v)` | ⚠️ | ✅ | Cast to string | `=TOSTRING(%Number%)` |
| `TONUMBER(v)` | ⚠️ | ✅ | Generic numeric cast | `=TONUMBER(%Text%)` |
| `TODOUBLE(v)` | ❌ | ✅ | Cast to Apex `Double` | `=TODOUBLE(%PriceString%) * 1.15` |
| `TOINTEGER(v)` | ❌ | ✅ | Cast to Apex `Integer` | `=TOINTEGER(%Quantity%)` |
| `TOBOOLEAN(v)` | ⚠️ | ✅ | Cast to boolean | `=TOBOOLEAN(%FlagText%)` |
| `TODATE(v)` | ✅ | ✅ | Parse a date | `=TODATE(%DateText%)` |
| `TODATETIME(v)` | ✅ | ✅ | Parse a datetime | `=TODATETIME(%DateTimeText%)` |

### Financial (OS only)

These come from the JavaScript spreadsheet-functions library bundled with OmniScript. The Apex IP/DR engine has no equivalents.

| Function | OS | IP/DR | Description | Example |
|----------|----|-------|-------------|---------|
| `PMT(rate, nper, pv)` | ✅ | ❌ | Periodic payment for an annuity loan | `=PMT(%Rate%/12, %Months%, %Principal%)` |
| `FV(rate, nper, pmt)` | ✅ | ❌ | Future value | `=FV(%Rate%/12, %Months%, %Pmt%)` |
| `PV(rate, nper, pmt)` | ✅ | ❌ | Present value | `=PV(%Rate%/12, %Months%, %Pmt%)` |
| `NPV(rate, cashflows)` | ✅ | ❌ | Net present value | `=NPV(0.05, %Cashflows%)` |
| `IPMT(rate, period, nper, pv)` | ✅ | ❌ | Interest portion of a payment | `=IPMT(%Rate%, 1, %N%, %PV%)` |
| `PPMT(rate, period, nper, pv)` | ✅ | ❌ | Principal portion of a payment | `=PPMT(%Rate%, 1, %N%, %PV%)` |
| `RATE(nper, pmt, pv)` | ✅ | ❌ | Implied interest rate | — |

If you need any of these in an IP context, the workaround is to compute them in OS and pass them in, or write Apex and call it via Remote Action / `FUNCTION()`.

### Apex bridge (IP/DR only)

The single function that lets a server-side formula call into custom Apex.

| Function | OS | IP/DR | Description | Example |
|----------|----|-------|-------------|---------|
| `FUNCTION(class, method, args...)` | ❌ | ✅ | Invokes an Apex class's method as if it were a formula. The Apex class must implement the OmniStudio Formula extension interface. | `=FUNCTION('TaxCalculatorUtil', 'calculateRegionalTax', %BaseAmount%, %State%)` |

OS cannot evaluate Apex inside a formula — the OmniScript runtime is in the browser. To get equivalent behavior in OS, configure a **Remote Action** element that calls the Apex method, then reference its output from `Set Values`.

---

## The Exclusivity Matrix

To ensure you do not encounter runtime errors or silent failures, adhere strictly to these boundaries:

| Formula / concept | Works in OS (client)? | Works in IP / DR (server)? | Architectural workaround / rationale |
|-------------------|----------------------|----------------------------|--------------------------------------|
| `FUNCTION()` (Apex call) | ❌ | ✅ | OS must use a Remote Action element to call backend Apex; it cannot evaluate Apex inside a `Set Values` formula. |
| `FILTER()`, `VLOOKUP()`, `SORTBY()` | ❌ | ✅ | OS lacks native JSON array manipulation in formulas. If you need to filter a list, pass it to an IP, process it, and return the pruned list. |
| `LISTSIZE()` | ❌ (unreliable) | ✅ | In OS, you generally have to use a custom LWC or route to an IP to count array length reliably. OS struggles with deep JSON array traversal. |
| `LIST()`, `INDEX()`, `FIRST()`, `LAST()`, `COUNT()`, `SUM()`, `AVG()` | ❌ | ✅ | Same constraint as above — these are Apex-list-aware. |
| `TODOUBLE()`, `TOINTEGER()` | ❌ | ✅ | Strict Apex casts. OS uses dynamic JS coercion (`Number(v)`) instead. |
| `PMT()`, `FV()`, `NPV()`, `IPMT()`, `PPMT()` | ✅ | ❌ | IP/DR Apex engine does not contain native financial spreadsheet functions. These must be calculated in OS, or handled via custom Apex called via `FUNCTION()` in IP. |
| `MOMENT()` (JS library) | ✅ ⚠️ deprecated | ❌ | Old Vlocity templates used moment.js. This will crash an IP. Always use standard DateTime formatting strings (`FORMATDATE`) in IPs. |
| Complex JS regex (with backreferences, lookbehinds) | ✅ | ❌ | OS evaluates JS regex patterns. IP requires Apex `Pattern` class via custom `FUNCTION()`. |
| OS-only special variables (`%LANGUAGE%`, `%CURRENCY%`) | ✅ | ❌ | Only the OS runtime resolves these from session context. Pass them explicitly into the IP input. |
| List-vs-scalar coercion | ⚠️ inconsistent | ✅ consistent | OS treats `null`, `[]`, and missing-key the same in many places; IP/Apex differentiates. See [Probing formula behavior](#probing-formula-behavior) below. |

### Final architectural recommendation

When designing your stack, map out your formulas during the architectural-logic phase. If your UI requires a dynamic dropdown filtered from a larger list, do **not** attempt to filter it in the OmniScript. Instead, invoke an IP with `useFuture: false`, use `FILTER()` on the server side, and return only the necessary key-value pairs (using `responseJSONNode` and `additionalOutput` to trim the response) back to the client.

A practical heuristic: if your candidate formula references `%path%` of something that came from a server Action, the formula belongs **in that Action**, not after it.

---

## Type coercion and list-vs-object caveats

These are the bugs that cost the most debugging time across the entire OmniStudio surface. They are subtle, runtime-version-dependent, and rarely surface in unit tests because the test data is too uniform. Read this section before writing any formula that touches a list, and probe with [`PRM_FormulaProbe`](#probing-formula-behavior) when the behavior surprises you.

### 1. A single-item list often collapses to an object

The single most common gotcha. When a DataRaptor, sub-IP, or Apex callable returns a list with **exactly one element**, the JSON serialization in the IP runtime frequently emits the bare object instead of a 1-element array. The same code returning two or more elements emits an array.

```text
# DR returns 0 rows:    payload.accounts = []           # or null, or {}, depending on DR config
# DR returns 1 row:     payload.accounts = { Id: "a" }  # COLLAPSED to object!
# DR returns 2 rows:    payload.accounts = [{Id:"a"}, {Id:"b"}]
```

Downstream formulas blow up:

| Expression | Returns when 1 row | Returns when 2 rows | Expected |
|------------|--------------------|--------------------|----------|
| `LISTSIZE(%accounts%)` | 1 (counts object keys → wrong) | 2 | 1 / 2 |
| `FILTER(%accounts%, '...')` | empty (FILTER expects list) | works | filtered list |
| `%accounts[0].Id%` | undefined | `"a"` | `"a"` |
| `SORTBY(%accounts%, 'Id', 'ASC')` | error / empty | sorted list | sorted list |

**Fix: always wrap with `LIST()`** to force list semantics:

```text
=LISTSIZE(LIST(%accounts%))
=FILTER(LIST(%accounts%), 'Status == "Active"')
=SORTBY(LIST(%accounts%), 'Id', 'ASC')
=FIRST(LIST(%accounts%))
```

`LIST()` is idempotent — calling it on something already a list returns the list unchanged. Wrap defensively.

### 2. `FILTER` output collapses too

`FILTER` is itself a list-returning function and exhibits the same collapse: a `FILTER` that matches exactly one element may emit an object, not a 1-element list. The fix is to wrap the whole `FILTER` call in `LIST()`:

```text
# Vulnerable
=FILTER(LIST(%accounts%), 'Id == "x"')

# Safer — guaranteed to be a list
=LIST(FILTER(LIST(%accounts%), 'Id == "x"'))
```

The same applies to `SORTBY`, `DISTINCT`, `UNION`, `INTERSECT`, and any other list-returning helper. When in doubt, double-wrap: `LIST(SORTBY(LIST(%list%), 'Field', 'ASC'))`.

### 3. The `:Field` colon traversal behaves differently on objects vs lists

OmniStudio's merge-field traversal `%path:Field%` walks differently when `%path%` is an object vs a list:

| `%path%` shape | `%path:Field%` resolves to |
|----------------|----------------------------|
| `{Field: "A"}` (object) | `"A"` (scalar) |
| `[{Field: "A"}]` (1-element list) | `["A"]` (1-element list) |
| `[{Field: "A"}, {Field: "B"}]` (multi list) | `["A", "B"]` (list) |
| `null` / missing | empty / `null` (depends on engine) |

This means **the same merge field returns three different shapes** depending on what the upstream node ended up being. Followups like `LISTSIZE(%path:Field%)`, `IF(ISBLANK(%path:Field%), ...)`, or `JOIN(%path:Field%, ", ")` all behave differently across shapes.

Combined with the collapse caveat (1), this is why `%accounts:Id%` may resolve to `"a"` on a 1-row read but `["a", "b"]` on a 2-row read.

**Fix:** if you need consistent list semantics, build the list explicitly upstream in a `Set Values`:

```text
# Set Values (forces array, picks the field)
{
  "accountIds": "=LIST(%accounts:Id%)"
}
```

Then `%accountIds%` is always a list.

### 4. `ISBLANK` and `LISTSIZE` disagree on empty / missing / single-object

| Input shape | `ISBLANK` | `ISNOTBLANK` | `LISTSIZE` |
|-------------|-----------|--------------|------------|
| `null` (missing key) | `true` | `false` | `0` (or error in some runtimes) |
| `[]` (empty list) | varies — sometimes `true`, sometimes `false` | inverse | `0` |
| `{}` (empty object) | varies | inverse | `0` |
| `{Id: "x"}` (single object — collapsed list?) | `false` | `true` | `1` (counts as "has content") |
| `[{Id: "x"}]` (true list of 1) | `false` | `true` | `1` |

Two practical rules:
- **Don't trust `ISBLANK` for "is this list empty?"** Use `LISTSIZE(LIST(%x%)) == 0` instead.
- **Don't trust `LISTSIZE` for "is this populated?"** A collapsed object returns 1, indistinguishable from a true 1-element list.

For "this list has at least one item", the bulletproof formula is:

```text
=AND(ISNOTBLANK(%list%), LISTSIZE(LIST(%list%)) > 0)
```

### 5. DataRaptor `[]` vs `[*]` mapping syntax

In DataRaptor mapping tables:

| Syntax | Meaning |
|--------|---------|
| `Account[*].Id` | Iterate all rows of `Account`, take `Id` from each |
| `output.ids[]` | Append to an array path on the output |
| `Account.Id` (no `[*]`, no `[]`) | First row's `Id`, written as a scalar |
| `output.account.Id` | Scalar at `output.account.Id` |

A DR Extract that ought to return an array but uses `Account.Id -> output.id` (no array brackets) returns a scalar — and silently drops every row after the first. Always check both sides of the mapping for array brackets when the source might return multiple rows.

### 6. Empty SOQL results: `{}` vs `null` vs missing

A DR Extract that finds zero rows can produce **any** of:
- `null` (the JSON path doesn't exist at all)
- `{}` (empty object at the path)
- `[]` (empty array at the path)

Which one happens depends on the DR's output mapping shape and whether `[*]`/`[]` brackets are used. `IF(ISBLANK(%result%), "no rows", "found")` is unreliable across these three shapes — `ISBLANK({})` and `ISBLANK([])` may differ from `ISBLANK(null)`.

**Fix:** standardize at the DR level. Use `[*]` and `[]` everywhere there could be 0..N rows; the DR will reliably emit `[]` for zero rows. Then `LISTSIZE(LIST(%result%)) == 0` is the safe empty check.

### 7. Date / DateTime coerce inconsistently across boundaries

Dates flow through OmniStudio as one of:
- An ISO string (`"2026-05-08"`) — what OmniScript serializes
- An Apex `Date` / `DateTime` — what Apex callables and DRs return
- A formatted display string (`"5/8/2026"`) — what some `FORMATDATE` outputs

When these cross a runtime boundary (OS → IP, IP → Apex, Apex → IP), the coercion is **best-effort**, not guaranteed. A common bug is:

```text
# In Apex, %TerminationDate% is a Date.
# In the JSON sent to the IP, it's serialized as "2026-05-08".
# Downstream:  =DATEDIFF(%TerminationDate%, %TODAY%)
# Sometimes works (auto-parse), sometimes returns NaN, depending on runtime version.
```

**Fix:** be explicit. In IPs, parse with `=TODATE(%TerminationDate%)` before passing to date arithmetic. In OS, `%TODAY%` is already an ISO string and arithmetic functions parse it.

Timezone trap: `%TODAY%` in OS is the **user's** timezone. `Date.today()` in Apex is the **org's** default timezone. For a user in Pacific time at 11 PM filling out a form, the OS's `%TODAY%` and the resulting Apex `Date.today()` differ by one day.

### 8. Boolean coercion: real `true` vs string `"true"`

Picklist booleans, especially when sourced from external systems or custom metadata, frequently arrive as the **strings** `"true"` / `"false"` rather than real booleans. Then:

```text
=IF(%flag%, "yes", "no")
# %flag% = true       → "yes"
# %flag% = "true"     → "yes"  (truthy string)
# %flag% = "false"    → "yes"  (also truthy string!)  ← BUG
# %flag% = false      → "no"
```

**Fix:** explicit comparison: `=IF(%flag% == true, "yes", "no")` or `=IF(EQUALS(%flag%, "true"), "yes", "no")` if you know it's a string.

In IPs, `=TOBOOLEAN(%flag%)` normalizes to a real boolean before comparison.

### 9. Picklist values: API name vs label

Picklist input elements bind the **API name (value)** by default — but the user sees the **label**. Source-of-truth code paths (DR Loads, Apex inserts) want the API name; display formulas want the label.

If `%Status%` arrives as `"Active"`, that may be either the label or the API name — they often coincide for English picklists but diverge for translated or refactored picklists. Cross-reference against the SObject's picklist field metadata before using the value in a formula or comparison.

For multi-select picklists, the runtime layer matters: OS exposes them as arrays, but a DR Load expects a semicolon-delimited string (`"A;B;C"`). Use a Transform DR or `JOIN(%values%, ";")` to convert.

### 10. `%CONTEXTID%` is a URL string, not a record ID

The OmniScript launching URL parameter `c__ContextId` is a string. Salesforce treats `"001Ov00001TslLyIAJ"` as a 18-char Id when it's at the right length, but if the URL passes a 15-char Id, downstream SOQL and DML treat it as a 15-char Id consistently — except in a few edge cases where Apex auto-converts it to 18. If you're persisting `%CONTEXTID%` to a custom field, normalize to 18 chars first via Apex.

### 11. Reserved-ish JSON keys

A handful of JSON keys are intercepted by the OmniStudio framework and have special meaning:

| Key | Special meaning |
|-----|-----------------|
| `error`, `errorMessage`, `errorCode` | Some runtimes interpret a non-empty value here as an action failure |
| `vlcStatus`, `vlcMessage` | Vlocity-internal status fields |
| `IPResult` | Default IP response wrapper key |
| `Action` | Reserved in some contexts |

Avoid using these as your own data keys. If you must, prefix them (`PRM_error`, `applicationError`).

### 12. Element API Name collisions silently overwrite

Two sibling elements with the same API Name don't error at design time. The **second one wins** at runtime, and the first one silently disappears from the data JSON. Always namespace inputs by Step (`In_FirstName`, `In_LastName`) or domain (`Account_Id`, `Contact_Id`) to avoid this.

### 13. `Set Values` rows referencing each other

Within a single `Set Values` element, whether row 2 can reference row 1's freshly-written value is **runtime-dependent**. Some Vlocity versions evaluate top-to-bottom (later rows see earlier writes); some evaluate as a snapshot (later rows don't see earlier writes within the same element).

**Fix:** if row 2 depends on row 1, split into two separate `Set Values` elements. The element boundary is a guaranteed sequencing point.

---

## Diagnostic checklist for "my formula is wrong"

When a formula returns the wrong value, walk this list in order:

1. **Identify the runtime.** OS or IP/DR? Check the exclusivity matrix above.
2. **Check the input shape.** Is it `null` / `[]` / `{}` / collapsed object / true list? Use [`PRM_FormulaProbe`](#probing-formula-behavior) or temporarily set `includeAllActionsInResponse: true` on the IP.
3. **Add `LIST()` defensively** to any list operation. Wrap `FILTER`, `SORTBY`, `LISTSIZE` arguments.
4. **Check colon-traversal cardinality.** `%path:Field%` returns scalar from object, list from list. Snap shapes upstream in a `Set Values` if the downstream code expects one shape.
5. **Check type coercion.** Boolean strings, Date strings, Number-vs-Integer. Cast explicitly with `=TOBOOLEAN()`, `=TODATE()`, `=TODOUBLE()` in IPs.
6. **Check Set Values evaluation order.** If row 2 depends on row 1, split.
7. **Run the probe.** Empirical truth beats documentation every time.

---

## Probing formula behavior

Most of the gotchas above are subtle list-vs-scalar coercion bugs, and the only reliable way to characterize them is to test formulas against representative inputs. The repo includes [`PRM_FormulaProbe_Procedure_1.oip-meta.xml`](../../force-app/main/default/omniIntegrationProcedures/PRM_FormulaProbe_Procedure_1.oip-meta.xml) — a small Integration Procedure whose entire job is to compute `LISTSIZE`, `ISNOTBLANK`, and `FILTER` against four input shapes (empty list, single-element list, two-element list, and a bare object) and return the results.

To run it:

```bash
scripts/ip-debug/run_ip.sh \
  --ip PRM_FormulaProbe \
  --input scripts/ip-debug/inputs/formula-probe.json
```

The runner emits the response and full debug log to `scripts/ip-debug/outputs/`. Inspect the response JSON to see what the formulas evaluated to. From there, extend the probe with your own formula expressions or input shapes — adding a new `Set Values` element is a one-line metadata edit.

This is the empirical fallback whenever the function reference disagrees with what you observe in production. Trust the probe.

---

## When in doubt

1. **Start in the IP.** Server-side formulas are nearly always more reliable.
2. **Check this matrix.** Most "weird formula bug" tickets reduce to a function on the wrong side of the OS↔IP line.
3. **Run the probe.** If list-vs-scalar coercion is involved, the probe will tell you exactly what the runtime sees.
4. **Bail to Apex.** If a formula is becoming a maze of nested `IF`/`AND`/`FUNCTION` calls, write a small Apex method and `FUNCTION()` it in.

---

## Cross-references

- [`omniscripts.md#merge-field-syntax`](omniscripts.md#merge-field-syntax) — `%path%` syntax in OS
- [`integration-procedures.md#merge-fields-and-the-payload`](integration-procedures.md#merge-fields-and-the-payload) — `%path%` syntax in IPs
- [`integration-procedures.md#payload-shape-caveats`](integration-procedures.md#payload-shape-caveats) — IP-side payload caveats (Pre/Post-Transform naming, additionalOutput interactions, sub-IP nesting, `%input%` namespace)
- [`patterns.md#anti-patterns`](patterns.md#anti-patterns) — formula-related anti-patterns
- [`patterns.md#debugging`](patterns.md#debugging) — diagnosing element-skip and pruning issues
- [`scripts/ip-debug/README.md`](../../scripts/ip-debug/README.md) — running the formula probe
