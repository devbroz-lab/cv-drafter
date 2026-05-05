# CV Reformatter — Detailed UI/UX Spec

**Audience**: Frontend developers building the React/Vue app.
**Scope**: 4 distinct pages covering the complete user journey.

---

## Page 1: Dashboard + Session Creation

**Route**: `/` or `/dashboard`

### Purpose
Allow users to create a new CV reformatting session by providing the CV, optional ToR, and job parameters. This populates the database session and triggers file uploads.

### Layout

```
┌────────────────────────────────────────────────────────┐
│  CV Reformatter — New Session                          │
├────────────────────────────────────────────────────────┤
│                                                        │
│  SECTION 1: Upload Files                              │
│  ────────────────────────────────────────────────────  │
│  [Drop zone or file picker] Curriculum Vitae (CV) *    │
│  Accepted: .docx, .pdf — max 10 MB                    │
│  File selected: resume_2024.pdf                       │
│                                                        │
│  [Drop zone or file picker] Terms of Reference (ToR)  │
│  Accepted: .docx, .pdf — optional                     │
│  No file selected                                      │
│                                                        │
│  SECTION 2: Job Position Details                      │
│  ────────────────────────────────────────────────────  │
│  Proposed Position: [__________ text input ________]   │
│  Example: "Senior Technical Expert – Energy"          │
│                                                        │
│  Job Description: [__________ large textarea ________] │
│  Paste full JD here...                                 │
│  [Expandable: 3 rows initially, up to 15 rows max]    │
│                                                        │
│  SECTION 3: Expert Background (Optional)              │
│  ────────────────────────────────────────────────────  │
│  Category: [Dropdown ▼] — e.g. "STE Pool 2"          │
│  Employer: [__________ text input ________]           │
│  Years with Firm: [__ number input __] years         │
│  Page Limit: [__ number input __] pages              │
│                                                        │
│  SECTION 4: Recruiter Notes (Optional)                │
│  ────────────────────────────────────────────────────  │
│  Initial Comments: [__________ large textarea ________]│
│  Highlight key strengths, red flags, etc...          │
│  [Expandable: 3 rows initially, up to 15 rows max]    │
│                                                        │
│  SECTION 5: Output Format                             │
│  ────────────────────────────────────────────────────  │
│  Target Format: [Dropdown ▼]                          │
│                 ├─ GIZ (default)                       │
│                 └─ World Bank (coming soon)           │
│                                                        │
│  ────────────────────────────────────────────────────  │
│                      [Start Processing] [Clear Form]   │
│                      (disabled until CV uploaded)      │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### User Interactions

#### 1. Upload Files

**CV Upload**
- Drag-and-drop zone OR file picker
- Accepted formats: `.docx`, `.pdf`
- Max file size: 10 MB
- On file select:
  - Validate extension client-side
  - Display filename + file size
  - Call `POST /sessions/{id}/upload/source` (async, show spinner)
  - On success: show checkmark, hide errors
  - On error (4xx/5xx): show error message inline (e.g., "File too large" or "Invalid format")
  - **Important**: Don't start processing yet — wait for "Start" button

**ToR Upload** (Optional)
- Same drag-and-drop + file picker
- Accepted formats: `.docx`, `.pdf`
- Call `POST /sessions/{id}/upload/tor` (async, show spinner)
- Success = show checkmark
- Can be skipped (optional)

#### 2. Form Inputs

| Field | Type | Validation | Required | API Param |
|-------|------|-----------|----------|-----------|
| Proposed Position | text | Max 200 chars | No | `proposed_position` |
| Job Description | textarea | Max 5000 chars | No | `job_description` |
| Category | dropdown | Predefined list | No | `category` |
| Employer | text | Max 150 chars | No | `employer` |
| Years with Firm | number | 0–100 | No | `years_with_firm` |
| Page Limit | number | 1–20 | No | `page_limit` |
| Recruiter Comments | textarea | Max 3000 chars | No | `recruiter_comments` |
| Target Format | dropdown | "giz", "world_bank" | Yes | `target_format` |

#### 3. Session Creation Flow

1. **User clicks "Start Processing"**
   - Validate: CV file required, target format selected
   - Show confirmation modal: "Ready to start? This cannot be undone."
   - On confirm:
     - Call `POST /sessions` with all form data
       ```json
       {
         "source_filename": "resume_2024.pdf",
         "tor_filename": "tor_2024.pdf", // if provided
         "proposed_position": "Senior Technical Expert",
         "job_description": "...",
         "category": "STE Pool 2",
         "employer": "Acme Corp",
         "years_with_firm": "5",
         "page_limit": 4,
         "recruiter_comments": "Emphasize renewable energy projects",
         "target_format": "giz"
       }
       ```
     - Backend creates session, returns `session_id`
     - Store `session_id` in state (for API calls)
     - Call `POST /sessions/{id}/start` to trigger `run_phase1`
     - Navigate to Processing Page

2. **Error Handling**
   - 429 Too Many Requests: "You have 3 active sessions. Wait for one to finish."
   - 400 Bad Request: Show form validation errors
   - 500 Server Error: "An error occurred. Please try again."

#### 4. UI States

| State | Show | Actions |
|-------|------|---------|
| Initial | Empty form | Upload CV |
| CV uploaded | Form enabled | Fill optional fields |
| Ready | All sections | Start Processing (enabled) |
| Processing | Spinner overlay | Disable form, navigate away |

---

## Page 2: Processing Dashboard

**Route**: `/processing/{session_id}`

### Purpose
Show real-time pipeline progress. Poll manifest every 2–3 seconds to track agent execution through 4 phases. Auto-navigate on block or completion.

### Layout

```
┌────────────────────────────────────────────────────────┐
│  Processing CV... (Session: abc-123-def)              │
├────────────────────────────────────────────────────────┤
│                                                        │
│  Phase 1: Text Extraction (Agents 1 & 2)             │
│  ─────────────────────────────────────────────────────│
│  ✓ CV Text Extraction                   [DONE]        │
│  ⟳ Terms of Reference Summary            [RUNNING]    │
│                                                        │
│  Phase 2: CV-to-ToR Mapping (Agent 3)                 │
│  ─────────────────────────────────────────────────────│
│  ○ CV-ToR Mapper                          [PENDING]   │
│                                                        │
│  Phase 3: Field Generation & Review (Agents 4, 5, 6) │
│  ─────────────────────────────────────────────────────│
│  ○ Fields Generator                       [PENDING]   │
│  ○ Content Reviewer                       [PENDING]   │
│  ○ Compressor                             [PENDING]   │
│                                                        │
│  Phase 4: Word Doc Rendering (Renderer)              │
│  ─────────────────────────────────────────────────────│
│  ○ GIZ Renderer                           [PENDING]   │
│                                                        │
│  Last updated: 2 seconds ago                          │
│  ⟳ [Refresh]                                          │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### Data Flow

1. **On page load**:
   - Call `GET /sessions/{id}/status` → fetch current session status
   - Call `GET /sessions/{id}/manifest` → fetch step-by-step progress
   - Display all 8 steps in a 4-phase timeline

2. **Polling logic** (every 2–3 seconds):
   ```javascript
   const poll = setInterval(async () => {
     const manifest = await fetch(`/sessions/{id}/manifest`)
     
     // Update step statuses
     manifest.steps.forEach(step => {
       updateStepUI(step.name, step.status)
     })
     
     // Check for transitions
     if (manifest.db_status === 'reviewer_blocked') {
       clearInterval(poll)
       navigateTo(`/blocked/${sessionId}`)
     }
     
     if (manifest.db_status === 'completed') {
       clearInterval(poll)
       navigateTo(`/output/${sessionId}`)
     }
     
     if (manifest.db_status === 'failed') {
       clearInterval(poll)
       navigateTo(`/error/${sessionId}`)
     }
   }, 3000)
   ```

3. **Step status visual mapping**:
   - `pending` → ○ hollow circle
   - `running` → ⟳ spinning icon
   - `done` → ✓ checkmark
   - `blocked` → ⚠ warning icon
   - `failed` → ✗ error icon

4. **Auto-navigation triggers**:
   - **Reviewer blocked** → `reviewer_blocked` status → navigate to `/blocked/{id}`
   - **All phases complete** → `completed` status → navigate to `/output/{id}`
   - **Pipeline failure** → `failed` status → navigate to `/error` with error message

5. **Error states**:
   - If manifest fetch fails: show "Connection lost" banner, retry every 5s
   - If session is in `failed` state: show error message and offer "New Session" button

### No User Input

This is a read-only monitoring page. Users just wait for the pipeline to finish.

---

## Page 3: Reviewer Block Resolution

**Route**: `/blocked/{session_id}`

### Purpose
Display content reviewer's flagged issues and allow user to either:
- Fix individual fields (dot-path editor)
- Override the issues and continue anyway

**Triggered when**: `status == "reviewer_blocked"`

### Layout

```
┌────────────────────────────────────────────────────────┐
│  Content Review Issues — Please Resolve                │
│  Session: abc-123-def                                  │
├────────────────────────────────────────────────────────┤
│                                                        │
│  🔴 HIGH SEVERITY ISSUES (Must be resolved)            │
│  ─────────────────────────────────────────────────────│
│                                                        │
│  Issue 1: Factual Inconsistency                        │
│  Field: relevant_projects.0.date_from                 │
│  Problem: Project start date (Jan 2019) contradicts    │
│           employment start date (Mar 2019)            │
│  Recommendation: Align dates or clarify overlap       │
│                                                        │
│  ┌─ Edit Field ──────────────────────────────────────┐│
│  │ Field: relevant_projects.0.date_from               ││
│  │ Current: Jan 2019                                  ││
│  │ New:     [__________ text input __________]        ││
│  │          [Save]  [Cancel]                          ││
│  └────────────────────────────────────────────────────┘│
│                                                        │
│  ─────────────────────────────────────────────────────│
│                                                        │
│  Issue 2: Unverifiable Claim                           │
│  Field: key_qualifications.2                          │
│  Problem: Claims "AWS Certified Solutions Architect"   │
│           but no certification in CV                  │
│  Recommendation: Remove or add certificate reference  │
│                                                        │
│  ┌─ Edit Field ──────────────────────────────────────┐│
│  │ Field: key_qualifications.2                        ││
│  │ Current: Designed and deployed 500+ instances on  ││
│  │          AWS with full HA setup. AWS CSA cert.    ││
│  │ New:     [__________ large textarea ________]      ││
│  │                                                    ││
│  │          [Save]  [Cancel]                          ││
│  └────────────────────────────────────────────────────┘│
│                                                        │
│  🟡 LOW SEVERITY ISSUES (Auto-fixed, shown for info)   │
│  ─────────────────────────────────────────────────────│
│  ✓ Fixed: "responsible for" → "designed"              │
│  ✓ Fixed: "involved in" → "architected"               │
│                                                        │
│  ─────────────────────────────────────────────────────│
│                                                        │
│  ☑ Override: "I acknowledge these issues and want to   │
│              proceed without fixing them"             │
│                                                        │
│                       [Continue]  [Back to Processing] │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### Data Fetch

**On page load**:
```javascript
const review = await fetch(`/sessions/{id}/review`)
// Returns:
{
  "session_id": "abc-123",
  "high_severity": [
    {
      "field": "relevant_projects.0.date_from",
      "issue": "Project start date contradicts employment start",
      "recommendation": "Align dates or clarify overlap"
    }
  ],
  "low_severity": [
    {
      "field": "key_qualifications.1",
      "issue": "Passive language",
      "original": "responsible for designing",
      "fixed": "designed"
    }
  ],
  "passed": false,
  "generation_warnings": []
}
```

### User Interactions

#### Option A: Fix Issues

1. User sees high-severity issue
2. Clicks "Edit Field" → inline editor appears
3. Edits the field value (text or textarea depending on field)
4. Clicks "Save" → validates input, stores override
5. Issue disappears from list
6. Repeat for all high-severity issues
7. When all fixed, "Continue" button becomes enabled

#### Option B: Override & Continue

1. User reviews issues
2. Checks "Override" checkbox → acknowledges the risk
3. Clicks "Continue" → force_pass=true
4. Pipeline resumes from compressor (no field fixes applied)

#### Option C: Go Back

1. Click "Back to Processing" → return to processing page
2. Can submit block resolution later

### API Call: Submit Resolution

```javascript
POST /sessions/{id}/resolve
{
  "overrides": {
    "relevant_projects.0.date_from": "Mar 2019",
    "key_qualifications.2": "Architected enterprise AWS infrastructure"
  },
  "force_pass": false  // true if using override option
}
```

**Response**:
```json
{
  "session_id": "abc-123",
  "status": "processing",
  "message": "Review resolved. Compressor starting."
}
```

**UI action**: Navigate to `/processing/{id}` to resume polling.

### Validation

- **Without overrides**: User must fix ALL high-severity issues before "Continue" is enabled
- **With overrides**: "Override" checkbox must be checked
- **Field edits**: Respect the field's data type (number fields get number input, etc.)

---

## Page 4: Final Output & Revision

**Route**: `/output/{session_id}`

### Purpose
Display the finalized CVData, let user download the formatted Word doc, and optionally submit feedback for revision rounds.

**Triggered when**: `status == "completed"`

### Layout

```
┌────────────────────────────────────────────────────────┐
│  CV Reformatting Complete ✓                            │
│  Session: abc-123-def | Round: 1                       │
├────────────────────────────────────────────────────────┤
│                                                        │
│  SECTION 1: Download Output                            │
│  ─────────────────────────────────────────────────────│
│  File: round_01_giz.docx                              │
│  Status: Ready to download                            │
│  Format: GIZ (2024 template)                           │
│  Pages: Estimated 4 pages                             │
│                                                        │
│              ⬇ [Download CV (DOCX)]                    │
│                                                        │
│  SECTION 2: Document Preview / Summary                │
│  ─────────────────────────────────────────────────────│
│  [Tab 1: Summary] [Tab 2: Full CV Data]               │
│                                                        │
│  ┌─ SUMMARY ─────────────────────────────────────────┐│
│  │                                                    ││
│  │ Personal Info:                                     ││
│  │  Name: John Smith | DOB: 15.03.1975               ││
│  │  Nationality: British | Languages: English (Native) ││
│  │                                                    ││
│  │ Position: Senior Technical Expert – Energy        ││
│  │                                                    ││
│  │ Key Qualifications:                                ││
│  │  • Designed grid-integration framework (3 prov.)  ││
│  │  • Led renewable energy transition in East Africa ││
│  │  • 15 years energy sector experience              ││
│  │                                                    ││
│  │ Education:                                         ││
│  │  MSc Energy Systems | TU Delft | 2008             ││
│  │  BSc Physics | Oxford | 2006                       ││
│  │                                                    ││
│  │ Experience Highlights:                             ││
│  │  [2018–Present] Lead Energy Consultant – World Bk ││
│  │  [2015–2018] Regional Director – GIZ Energy       ││
│  │  [2010–2015] Senior Engineer – Shell              ││
│  │                                                    ││
│  │ Languages:                                         ││
│  │  English (Native) | Spanish (B2) | French (B1)    ││
│  │                                                    ││
│  │ Compression: 12,500 → 8,200 words (-34%)          ││
│  │ Warnings: None                                     ││
│  │                                                    ││
│  └────────────────────────────────────────────────────┘│
│                                                        │
│  ┌─ FULL CV DATA (JSON Preview) ──────────────────────┐│
│  │ {                                                  ││
│  │   "personal_info": {                               ││
│  │     "full_name": "John Smith",                     ││
│  │     "date_of_birth": "15.03.1975",                ││
│  │     ...                                            ││
│  │   },                                               ││
│  │   "relevant_projects": [...],                      ││
│  │   ...                                              ││
│  │ }                                                  ││
│  │ [Scroll to see all fields]                         ││
│  └────────────────────────────────────────────────────┘│
│                                                        │
│  SECTION 3: Revision Feedback (Optional)              │
│  ─────────────────────────────────────────────────────│
│  💡 Ready to refine further?                           │
│                                                        │
│  Feedback for Round 2:                                │
│  [__________ large textarea ________]                │
│  Examples: "Add case studies", "Tone down jargon",   │
│            "Emphasize international experience", etc.  │
│  [Max 2000 chars] [600 chars used]                    │
│                                                        │
│                 [Submit Feedback & Revise]            │
│                                                        │
│  Note: A revision will re-run Agents 4–6 with your    │
│        feedback. Output file will be saved as         │
│        round_02_giz.docx.                             │
│                                                        │
│                       [New Session]                    │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### Data Fetch

**On page load**:
```javascript
// 1. Get session details (status, round, file info)
const session = await fetch(`/sessions/{id}/status`)

// 2. Get generated CV data
const output = await fetch(`/sessions/{id}/output`)
// Returns:
{
  "session_id": "abc-123",
  "cv_data": { ...full CVData object... },
  "generation_warnings": ["Unmatched ToR requirement: X"],
  "review": { "high_severity": [], "low_severity": [], "passed": true },
  "compression": {
    "original_word_count": 12500,
    "compressed_word_count": 8200,
    "target_word_count": 8000,
    "compression_ratio": 0.65
  }
}

// 3. Get signed download URL (1-hour expiry)
const downloadUrl = await fetch(`/sessions/{id}/files/output/download-url`)
// Returns: { signed_url: "https://...", expires_in: 3600 }
```

### User Interactions

#### 1. Download Word Doc
- Button click → use `signed_url` from API
- Browser downloads `round_01_giz.docx`
- If download link expires: refetch URL and retry

#### 2. Preview CV Data
- **Summary tab**: Display nicely formatted excerpt (name, position, key quals, recent projects, languages)
- **Full Data tab**: Show raw JSON (searchable, syntax-highlighted)
- No edits allowed on this page (data is immutable)

#### 3. Submit Revision Feedback
- User types feedback (max 2000 chars, show counter)
- Click "Submit Feedback & Revise"
  - Call `POST /sessions/{id}/comments`
    ```json
    {
      "comment": "Add case study examples. Tone down technical jargon."
    }
    ```
  - Response: `{ "status": "processing", "round": 2, "message": "Revision queued..." }`
  - UI shows: "Revision Round 2 in progress... (Agents 4–6 re-running)"
  - Navigate to `/processing/{id}` to show progress
  - When complete, return to `/output/{id}` with new file `round_02_giz.docx`

#### 4. Start New Session
- Click "New Session" → navigate to `/` (Dashboard)

### Compression Display

Show stats if available:
```
Original:   12,500 words
Compressed:  8,200 words (-34%)
Target:      8,000 words (based on page_limit)
Ratio:       65% of original
```

### Error States

- **Download expired**: "Link expired. Refresh page to get new link."
- **No output file**: "Output not ready yet. Please check processing."
- **Revision failed**: Show error, offer "Retry" button

---

## Error Page

**Route**: `/error/{session_id}`

### Purpose
Display when session processing fails.

### Layout

```
┌────────────────────────────────────────────────────────┐
│  Processing Failed ✗                                   │
│  Session: abc-123-def                                  │
├────────────────────────────────────────────────────────┤
│                                                        │
│  Error: Text extraction failed on CV file              │
│  Details: Could not parse PDF. Ensure file is not      │
│           encrypted or corrupted.                      │
│                                                        │
│  Troubleshooting:                                      │
│  1. Try a different file format (.docx instead of PDF)│
│  2. Ensure the file is not corrupted                   │
│  3. Check that the file is not password-protected      │
│                                                        │
│              [Download CV] [New Session] [Contact Help]│
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

## State Diagram

```
Dashboard ──[File + Form]──> Processing ──[Manifest Poll]──┬──> Blocked ──[Fix/Override]──┐
                                 ▲                          │      Block                     │
                                 │                          │      ▲                         │
                                 │                          │      │                         │
                                 └──[Auto-retry on failure]─┴──────┘                         │
                                                                                             │
                                                            ┌────────────────────────────────┘
                                                            │
                                                            ▼
                                                          Output ──[Revise]──┐
                                                            ▲                 │
                                                            │                 │
                                                            └─[Poll + Return]─┘
```

---

## API Summary Table

| Endpoint | Method | Body | Response | When |
|----------|--------|------|----------|------|
| `/sessions` | POST | Form data | `{ session_id, status }` | Dashboard |
| `/sessions/{id}/upload/source` | POST | File | `{ storage_key, signed_url }` | Dashboard |
| `/sessions/{id}/upload/tor` | POST | File | `{ storage_key, signed_url }` | Dashboard |
| `/sessions/{id}/start` | POST | — | `{ status: "processing" }` | Dashboard |
| `/sessions/{id}/manifest` | GET | — | `{ steps[], checkpoint_pending, reviewer_blocked }` | Processing (poll) |
| `/sessions/{id}/review` | GET | — | `{ high_severity[], low_severity[] }` | Blocked |
| `/sessions/{id}/resolve` | POST | `{ overrides, force_pass }` | `{ status: "processing" }` | Blocked |
| `/sessions/{id}/output` | GET | — | `{ cv_data, compression, warnings }` | Output |
| `/sessions/{id}/comments` | POST | `{ comment }` | `{ status: "processing", round }` | Output |
| `/sessions/{id}/files/output/download-url` | GET | — | `{ signed_url, expires_in }` | Output |

---

## Frontend Component Structure (Recommendation)

```
App
├── Dashboard
│   ├── FileUploadZone
│   ├── FormFields
│   └── SubmitButton
├── Processing
│   ├── PhaseTimeline
│   │   └── StepStatus (repeated)
│   └── ManifestPoller (hook)
├── Blocked
│   ├── IssueList
│   │   ├── HighSeverityIssue
│   │   │   └── InlineFieldEditor
│   │   └── LowSeverityIssue
│   └── OverrideCheckbox
└── Output
    ├── DownloadSection
    ├── PreviewTabs
    │   ├── SummaryTab
    │   └── FullDataTab
    └── RevisionFeedback
```

---

## Key Validations & Rules

### Dashboard
- CV file required before "Start"
- File type: .docx or .pdf only
- Session creation required before uploads

### Processing
- Poll every 2–3 seconds
- Stop polling on error/block/completion
- Handle connection loss gracefully

### Blocked
- All high-severity issues must be edited OR force_pass checked
- Field edits must respect data types
- Overrides stored as dot-path: value pairs

### Output
- Download URL expires in 1 hour
- Revision creates new round (increment counter)
- Can submit multiple rounds indefinitely

---

## Loading States & Spinners

- **File upload**: Spinner until signed_url returned
- **Session creation**: Spinner until session_id returned
- **Processing**: Spinning icon on step names, update every poll
- **Blocked resolution**: Spinner during POST /resolve
- **Revision submission**: Spinner until response received, then return to Processing

---

## Toast/Notification Messages

| Scenario | Type | Message |
|----------|------|---------|
| CV uploaded | Success | "CV uploaded successfully" |
| Session created | Success | "Session created. Starting pipeline..." |
| Processing error | Error | "[Agent name] failed: [error message]" |
| Blocked detected | Warning | "Content review blocked. Please resolve issues." |
| Revision submitted | Success | "Round 2 queued. Refreshing..." |
| Download expired | Error | "Download link expired. Refreshing..." |

