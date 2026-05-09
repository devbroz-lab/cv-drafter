# Field Editor — Skip Transparency & Apply-Bias Fixes

**Scope**: Two targeted changes to `pipeline/agents/field_editor.py`.
**Problems addressed**:
- Fix 1 — Skip reasons are silently discarded; the user never learns why an edit was rejected.
- Fix 4 — The assistant prefill does not bias Claude toward `apply`; the model freely chooses `skip`.

**Sequencing decision**: Fix 1 is applied immediately. Fix 4 is deferred — see the Fix 4 section for the rationale.

---

## Fix 1 — Surface skip reasons to the API response

### Problem

When Claude returns `{"action": "skip", "reason": "..."}`, the reason string
is logged at `INFO` level (line 419) and then **thrown away**. The `skipped`
list returned by `run_field_editor()` and `run()` contains only the bare
`field_path` string. The HTTP handler forwards that list directly into the
`POST /field-edit` response, so the user sees:

```json
{
  "skipped": ["key_qualifications[2]"]
}
```

There is no way for the frontend to tell the user why the edit was rejected,
or how to rephrase the instruction to get a different outcome.

The Python-level skips (path resolution failure, non-scalar value) share the
same problem — their reasons are only in server logs.

### Solution

Change `skipped` from `list[str]` to `list[dict]` with a `path` and `reason`
key at every accumulation point, then thread this through to the HTTP response.

#### 1a. `run_field_editor()` — accumulate dicts instead of strings

```python
# BEFORE (three separate append sites, all the same pattern):
skipped.append(field_path)

# AFTER — each site supplies a reason string:

# Path resolution failure (line ~387):
skipped.append({"path": field_path, "reason": f"path resolution failed: {exc}"})

# Non-scalar guard (line ~397):
skipped.append({
    "path": field_path,
    "reason": (
        f"resolved value is {type(current_value).__name__}, not a scalar. "
        "Use a more specific path (e.g. list[N]) to target a scalar element."
    ),
})

# LLM chose skip (line ~420):
skipped.append({"path": field_path, "reason": result["reason"]})

# API / parse error (line ~414):
skipped.append({"path": field_path, "reason": f"API or parse error: {exc}"})

# Write-back failure (line ~429):
skipped.append({"path": field_path, "reason": f"write-back failed: {exc}"})
```

Update the return type annotation accordingly:

```python
def run_field_editor(
    ...
) -> tuple[dict, list[str], list[dict]]:   # skipped is now list[dict]
```

#### 1b. `run()` — return list[dict] unchanged

`run()` just returns what `run_field_editor()` returns, so no logic changes
are needed there. Update only the return type annotation:

```python
def run(
    ...
) -> tuple[list[str], list[dict]]:   # skipped is now list[dict]
```

#### 1c. HTTP handler (`api/routers/sessions.py`) — forward dicts as-is

The handler already includes `skipped` in the JSON response. Because the
elements are now dicts rather than strings, the serialisation is automatic —
no structural change needed. The response shape becomes:

```json
{
  "session_id": "...",
  "status": "checkpoint_3_pending",
  "round": 2,
  "applied": ["relevant_projects[1].location"],
  "skipped": [
    {
      "path": "key_qualifications[2]",
      "reason": "Instruction requires adding a certification not present in the original value."
    }
  ],
  "message": "Field edits applied. Awaiting checkpoint_3 approval before re-render."
}
```

#### 1d. API documentation — update `POST /field-edit` response description

In `API.md`, update the `skipped` field description:

```
# BEFORE
- `skipped`: Paths the agent could not resolve or could not apply without fabricating information

# AFTER
- `skipped`: Objects with `path` and `reason` keys for each edit that was not applied.
  Reason categories: path resolution failure, non-scalar target, LLM skip decision,
  API error, write-back failure.
```

Update the example response block in `API.md` to match the new shape.

#### 1e. Frontend — display reasons to the user

Where the frontend currently renders the `skipped` array (e.g. as a warning
banner or inline annotation on the field), update it to read `item.path` and
`item.reason` rather than treating each element as a plain string. Display the
reason inline beneath the field that was skipped so the user can rephrase
their instruction immediately.

---

## Fix 4 — Force `apply` via assistant prefill

### Problem

The current prefill is:

```python
ASSISTANT_PREFILL = '{"action": "'
```

This locks the response to valid JSON and prevents preamble, but it does not
constrain which action the model chooses. Claude still freely selects `apply`
or `skip` as the next token, and the distribution skews toward `skip` more
than intended.

### Solution

Advance the prefill further so that the `action` value is already committed
to `"apply"`:

```python
# BEFORE
ASSISTANT_PREFILL = '{"action": "'

# AFTER
ASSISTANT_PREFILL = '{"action": "apply", "value": "'
```

With this prefill, Claude's continuation begins inside the `value` string.
The `skip` path is structurally unreachable because the word `"skip"` can
never appear as the action — the model is already past that token.

#### Effect on `call_claude()`

The JSON assembly and parsing logic in `call_claude()` works the same way.
The full response is still:

```python
full_response = ASSISTANT_PREFILL + continuation
```

After parsing, `result["action"]` will always be `"apply"` and
`result["value"]` will be the edited field text. The `elif action == "skip"`
branch in the parse-and-validate block becomes unreachable but does no harm
if left in place.

#### Effect on `run_field_editor()`

The `if result["action"] == "skip"` dispatch block (line ~418) also becomes
unreachable. It can be left in place for safety — removing it is not recommended
as the block costs nothing and preserves the code path if the prefill is ever
rolled back.

#### Trade-off to document

Forcing `apply` removes the agent's only mechanism for declining an
impossible instruction. If a user instruction is genuinely unsatisfiable
(e.g. "add the candidate's PhD qualification" when no such qualification
exists), the model will now attempt a best-effort application rather than
refusing. In practice this means it will either leave the value unchanged
or make a minimal plausible edit — both outcomes are acceptable given that
the user is a trusted recruiter operating on their own CV session.

This is an explicit design decision: **user instructions on the frontend are
treated as reliable and are applied without challenge.**

#### Interaction with the system prompt (Fix 2) — Option B decision

Fix 4 makes the `skip` path structurally unreachable at the model level.
This means the `skip`-related sections of `SYSTEM_PROMPT_A7` — the `"skip"`
JSON shape in `RESPONSE FORMAT`, the `DEFAULT: ALWAYS USE "apply"` block,
the `DO NOT use "skip"` list, and the single `skip` trigger rule — become
dead text that the model reads but can never act on.

**Decision: keep the prompt unchanged (Option B).**

The `skip` scaffolding is left in place deliberately. Fix 4 is currently
deferred (see below), meaning the prefill is still neutral and the `skip`
path is live. When Fix 4 is eventually applied, keeping the prompt intact
means no second prompt change is needed at that point — the `skip` sections
simply become inert without causing any harm to `apply` behaviour.

If Fix 4 is later rolled back, the prompt is already ready to handle both
actions correctly without any rewrite.

**Consequence**: once Fix 4 is applied, the `skip` prompt sections are inert.
This is acceptable and deliberate — they do not interfere with `apply`
behaviour.

#### Sequencing — why Fix 4 is deferred

Fix 1 alone gives something Fix 4 would take away: **observable skip data
under the new prompt (Fix 2)**. With Fix 1 live and Fix 4 deferred, real
sessions will produce skip reasons visible in the API response. That data
allows an evidence-based decision: if skips drop to an acceptable rate under
the rewritten prompt, Fix 4 may never be needed. If skips remain excessive,
Fix 4 is applied at that point with confirmation rather than speculation.

Applying Fix 4 now would make the skip path structurally unreachable before
that data exists, removing the ability to measure whether Fix 2 alone was
sufficient.

**Fix 4 is applied after observing skip rates in production under Fix 1 + Fix 2.**

---

## Files to modify

| File | Change |
|---|---|
| `pipeline/agents/field_editor.py` | Fix 1: change all `skipped.append(field_path)` to `skipped.append({"path": ..., "reason": ...})` and update return type annotations. Fix 4 (deferred): change `ASSISTANT_PREFILL` constant when sequencing decision is made. |
| `api/models/requests.py` (or `models.py`) | Fix 1: add `class FieldEditSkip(BaseModel): path: str; reason: str` and set `skipped: list[FieldEditSkip]` on the field-edit response model. |
| `api/routers/sessions.py` | Fix 1: verify `skipped` is forwarded as-is (no string coercion). Update response model annotation to `list[FieldEditSkip]`. |
| `API.md` | Fix 1: update `skipped` field description and example response. |
| Frontend field-edit UI component | Fix 1: read `item.path` / `item.reason` from skipped array; display reason to user. |

---

## What is NOT changed by these two fixes

- The system prompt wording — Fix 2 is addressed separately. Fix 4 makes the `skip` sections of the prompt inert but does not remove them (Option B — see above).
- The model selection — addressed separately and outside the scope of this document.
- The path resolution logic, word-limit lookup, or context-building behaviour.
- The `applied` list shape (still `list[str]`).
- The overall `run()` / `run_field_editor()` call signatures (only return types change).
