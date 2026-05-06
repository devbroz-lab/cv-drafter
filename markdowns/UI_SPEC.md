# CV Reformatter UI/UX Spec

**Purpose**: Functional breakdown of the UI pages and user inputs required to drive the backend pipeline through all 4 phases and optional revision cycle.

---

## Overview: User Journey

```
1. Upload Page        → User creates session & uploads CV (+ optional ToR)
2. Processing Page    → Pipeline runs 4 phases with 3 checkpoints in between
3. Checkpoint Pages   → User reviews & approves each checkpoint
4. Reviewer Block     → [OPTIONAL] If Agent 5 flags critical issues
5. Blocked Resolution → User fixes issues & resumes
6. Final Output       → User downloads formatted Word doc
7. Revision Cycle     → [OPTIONAL] User submits feedback for re-run
```

---

## Page 1: Upload & Session Creation

**Route**: `/upload`

### User Inputs Required

| Input | Field Name | Type | Backend Parameter | Required? | Notes |
|-------|-----------|------|-------------------|-----------|-------|
| CV File | source_filename | File | `source_storage_key` | Yes | Accept .docx, .pdf only |
| Terms of Reference | tor_filename | File | `tor_storage_key` | No | Optional, same file types |
| Proposed Position | proposed_position | Text | `proposed_position` | No | Job title candidate is applying for |
| Job Description | job_description | Text | `job_description` | No | Full JD text to reference |
| Category | category | Dropdown | `category` | No | E.g., "Senior Manager", "Technical Expert" |
| Employer | employer | Text | `employer` | No | Current/previous company name |
| Years with Firm | years_with_firm | Number | `years_with_firm` | No | Years of experience |
| Page Limit | page_limit | Number | `page_limit` | No | Max pages for output (e.g., 3–5) |
| Recruiter Comments | recruiter_comments | Long Text | `recruiter_comments` | No | Initial feedback/instructions |
| Donor Format | target_format | Dropdown | `target_format` | Yes | Currently: "giz" only |

### Actions

1. **Create Session** (POST `/sessions`)
   - Parameters passed to backend
   - Session transitions to `queued` state
   - Returns `session_id` for future API calls

2. **Upload Source CV** (POST `/sessions/{id}/upload/source`)
   - File form upload
   - Stored in Supabase at `{session_id}/source/{filename}`
   - Updates `source_storage_key`

3. **Upload ToR** (POST `/sessions/{id}/upload/tor`) *[Optional]*
   - File form upload
   - Stored in Supabase at `{session_id}/tor/{filename}`
   - Updates `tor_storage_key`

4. **Start Processing** (POST `/sessions/{id}/start`)
   - Only enabled when both session exists AND source file uploaded
   - Triggers background task: `run_phase1`
   - Session transitions to `processing` state

### Validation

- CV file required before start
- File type validation (`.docx` or `.pdf`)
- File not empty
- Rate limit check: max 3 active sessions per user (returns 429)

---

## Page 2: Processing & Manifest Polling

**Route**: `/processing/{session_id}`

### Purpose

Show real-time pipeline progress across 4 phases. UI polls `/sessions/{id}/manifest` continuously to update step status.

### User Inputs Required

**None** — This is read-only monitoring.

### Displayed Data

Fetch from `GET /sessions/{id}/manifest`:
- **Fine-grained steps**: `cv_extractor`, `tor_summarizer`, `cv_tor_mapper`, `fields_generator`, `content_reviewer`, `compressor`, `renderer`, etc.
- **Step statuses**: `pending`, `running`, `done`, `blocked`, `failed`
- **Checkpoint pending**: Which checkpoint (if any) is awaiting approval
- **Reviewer blocked flag**: True if Agent 5 blocked the pipeline

### UI Behavior: Before Checkpoint

1. **Poll manifest every 2–3 seconds**
2. **Display step progress** (e.g., Extractor → running, Mapper → pending)
3. **When checkpoint_N becomes "pending"**:
   - Hide processing UI
   - Show Checkpoint Approval Page (see below)

### UI Behavior: Reviewer Block

If `reviewer_blocked=true`:
   - Hide processing UI
   - Show Blocked Resolution Page (see Page 4 below)

---

## Page 3: Checkpoint Approval Pages (3 total)

**Route**: `/checkpoint/{checkpoint_id}` or tab within `/processing`

### Checkpoint 1: CV Extraction & ToR Summarization

**When triggered**: After Agents 1 & 2 complete
**User inputs required**:
- **Review checkbox**: "I have reviewed the extracted CV data"
- **Approve button**: Triggers `POST /sessions/{id}/approve/checkpoint_1`


---

### Checkpoint 2: CV-to-ToR Mapping

**When triggered**: After Agent 3 (CV-ToR Mapper) completes
**User inputs required**:
- **Review checkbox**: "I have reviewed the mapping"
- **Approve button**: Triggers `POST /sessions/{id}/approve/checkpoint_2`

**Data to display**:
- Mapped fields (e.g., "Position in CV" → "Position in ToR")
- Any unmatched fields highlighted

---

### Checkpoint 3: Field Generation & Compression

**When triggered**: After Agents 4 & 5 complete (assuming Agent 5 passed)
**User inputs required**:
- **Review checkbox**: "I approve the final formatted output"
- **Approve button**: Triggers `POST /sessions/{id}/approve/checkpoint_3`

**Data to display**:
- Preview of final CVData (fetch `/sessions/{id}/output`)
- Compression stats: original word count → compressed word count
- Page estimate (e.g., "Estimated 4 pages")
- Generation warnings (if any)

---

## Page 4: Blocked Resolution Page [OPTIONAL]

**Route**: `/blocked/{session_id}`
**Triggered when**: `status == "reviewer_blocked"`

### User Inputs Required

1. **Review Issues** (read-only display)
   - Fetch `GET /sessions/{id}/review`
   - Show `high_severity` list and `low_severity` list
   - Example: "Missing work dates in Section 3", "Unrecognized language code"

2. **Field Overrides** (optional)
   - For each high-severity issue, provide **inline editor** or **modal**
   - Edit the flagged field directly
   - Format: dot-path to field (e.g., `work_experience.0.date_from`)
   - **Example**:
     ```
     Issue: "Missing start date for role #1"
     Field: work_experience.0.date_from
     Input: [User types "Jan 2020"]
     ```

3. **Force Pass Option** (checkbox)
   - Label: "I acknowledge these issues and wish to proceed anyway"
   - Only enabled if user has reviewed issues

### Actions

**Submit Override + Continue** (POST `/sessions/{id}/resolve`)
- Body:
  ```json
  {
    "overrides": {
      "work_experience.0.date_from": "Jan 2020",
      "languages.1.reading_cefr": "B1"
    },
    "force_pass": false
  }
  ```
- Triggers background task: `run_phase3_resume`
- Session transitions to `processing`
- Redirect to Processing Page

**Force Pass** (POST `/sessions/{id}/resolve`)
- Body:
  ```json
  {
    "overrides": {},
    "force_pass": true
  }
  ```
- Skips field edits, marks reviewer as passed
- Resumes from compressor

---

## Page 5: Final Output Page

**Route**: `/output/{session_id}`
**Triggered when**: `status == "completed"`

### Edit Document Flow (NEW)
- "Edit Document" button appears at completed status
- Opens field_edit panel in SessionWorkspacePage
- Can edit any field before downloading
- On save: POST /field-edit returns checkpoint_3_pending
- No polling needed (synchronous)

### User Inputs Required

1. **Review Output** (read-only display)
   - Fetch `GET /sessions/{id}/output`
   - Display full CVData as formatted table/sections
   - Show compression stats & warnings

2. **Download Button**
   - Fetch signed URL from `GET /sessions/{id}/files/output/download-url`
   - Download `round_01_giz.docx` (or higher round number if revised)

3. **Submit Revision Feedback** (textarea + submit button)
   - Becomes visible 10 seconds after output loads (UX choice)
   - Label: "Revise this CV? Submit feedback below."
   - Input: Long text (recruiter comments)
   - **Example**: "Please tone down the technical jargon. Add 3 case study examples."
   - Button: "Submit Feedback & Revise"

### Actions

**Submit Revision** (POST `/sessions/{id}/comments`)
- Body:
  ```json
  {
    "comment": "Please tone down the technical jargon. Add 3 case study examples."
  }
  ```
- Response includes next `round` number (e.g., round 2)
- Session transitions to `processing`
- Fetches `run_phase3_resume` in background (Agents 4, 5, 6 re-run with new recruiter_comments)
- Output filename increments: `round_02_giz.docx`
- **Poll manifest again** to show progress
- When complete, return to Final Output Page with new round number

---

## Summary: User Input Points

### Required Inputs (Session Creation)

1. Source CV file ✓
2. Target format (giz) ✓
3. Proposed position (optional)
4. Job description (optional)
5. Category (optional)
6. Employer (optional)
7. Years with firm (optional)
8. Page limit (optional)
9. Recruiter comments (optional)

### At Each Checkpoint

- **Checkpoint 1, 2, 3**: Review checkbox + Approve button

### On Reviewer Block

- Field overrides (dot-path → new value)
- Force pass checkbox

### On Final Output

- Revision feedback (textarea + submit)

---

## Technical Notes for Frontend

### Polling Strategy

```javascript
// Processing page
const poll = setInterval(async () => {
  const manifest = await GET `/sessions/${id}/manifest`
  
  if (manifest.checkpoint_pending) {
    // Show checkpoint page
    clearInterval(poll)
    navigateTo(`/checkpoint/${manifest.checkpoint_pending}`)
  }
  
  if (manifest.reviewer_blocked) {
    // Show blocked resolution page
    clearInterval(poll)
    navigateTo(`/blocked/${id}`)
  }
  
  if (manifest.db_status === 'completed') {
    // Show final output page
    clearInterval(poll)
    navigateTo(`/output/${id}`)
  }
}, 3000)
```

### Error Handling

- **409 Conflict**: Session status mismatch → show user-friendly message
- **429 Too Many Requests**: Rate limit hit → inform user to wait
- **400 Bad Request**: Validation error → highlight field
- **500 Internal Server Error**: Log and show generic "processing failed" message

### Session Status States (for UI routing)

```
queued           → Show Upload Page (can upload files, start when ready)
processing       → Show Processing/Manifest Page (poll manifest)
checkpoint_1_pending → Show Checkpoint 1 Page
checkpoint_2_pending → Show Checkpoint 2 Page
checkpoint_3_pending → Show Checkpoint 3 Page
reviewer_blocked → Show Blocked Resolution Page
completed        → Show Final Output Page
failed           → Show Error Page (display error_message from DB)
```

---

## Revision Cycle Flow

1. User on Final Output Page downloads `round_01_giz.docx`
2. Reviews document
3. Submits feedback: "Add case studies"
4. UI shows "Revision queued..." (status briefly = processing)
5. Backend re-runs Phase 3 (Agents 4, 5, 6 with updated `recruiter_comments`)
6. UI polls manifest, detects completion
7. Final Output Page refreshes with new `round_02_giz.docx`
8. User can download again or submit another round of feedback

---

## File Download URLs

All download URLs are **signed** and **time-limited** (default 1 hour):

- Source CV: `GET /sessions/{id}/files/source/download-url`
- ToR: `GET /sessions/{id}/files/tor/download-url`
- Output: `GET /sessions/{id}/files/output/download-url`

Each returns `{ signed_url: "https://...", expires_in: 3600 }`

---

## Key Constraints

- **Max 3 concurrent active sessions per user** (rate limit)
- **World Bank format not yet supported** — only GIZ
- **Session ownership**: Users can only access their own sessions
- **File types**: .docx or .pdf only
- **ToR is optional** — pipeline handles gracefully if missing
- **Reviewer block is conditional** — only if Agent 5 flags high-severity issues
