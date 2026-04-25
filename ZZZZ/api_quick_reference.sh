#!/bin/bash
# CV Reformatter API - Quick Reference Commands
# Replace <TOKEN> with your Supabase JWT
# Replace <SESSION_ID> with the session UUID returned from POST /sessions

BASE_URL="http://127.0.0.1:8000"
TOKEN="<SUPABASE_JWT_TOKEN>"

# ============================================================================
# HEALTH CHECK
# ============================================================================
echo "=== Health Check ==="
curl -s "$BASE_URL/health" | jq .


# ============================================================================
# CREATE SESSION
# ============================================================================
echo "=== Create Session ==="
curl -s -X POST "$BASE_URL/sessions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "target_format": "giz",
    "source_filename": "cv.docx",
    "proposed_position": "Senior Water Engineer",
    "category": "Senior Expert",
    "employer": "ABC Consulting",
    "years_with_firm": "5",
    "page_limit": 4,
    "job_description": "Lead water infrastructure projects"
  }' | jq .

# Save session_id from response
SESSION_ID="<RETURNED_SESSION_ID>"


# ============================================================================
# UPLOAD FILES
# ============================================================================
echo "=== Upload Source CV ==="
curl -s -X POST "$BASE_URL/sessions/$SESSION_ID/upload/source" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/cv.docx" | jq .

echo "=== Upload Terms of Reference ==="
curl -s -X POST "$BASE_URL/sessions/$SESSION_ID/upload/tor" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/tor.pdf" | jq .


# ============================================================================
# GET SESSION STATUS
# ============================================================================
echo "=== Get Session Status ==="
curl -s "$BASE_URL/sessions/$SESSION_ID/status" \
  -H "Authorization: Bearer $TOKEN" | jq .


# ============================================================================
# START PROCESSING (Phase 1)
# ============================================================================
echo "=== Start Processing ==="
curl -s -X POST "$BASE_URL/sessions/$SESSION_ID/start" \
  -H "Authorization: Bearer $TOKEN" | jq .


# ============================================================================
# POLL MANIFEST (check step progress)
# ============================================================================
echo "=== Poll Manifest ==="
curl -s "$BASE_URL/sessions/$SESSION_ID/manifest" \
  -H "Authorization: Bearer $TOKEN" | jq .


# ============================================================================
# APPROVE CHECKPOINTS (after each phase)
# ============================================================================
echo "=== Approve Checkpoint 1 ==="
curl -s -X POST "$BASE_URL/sessions/$SESSION_ID/approve/checkpoint_1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Approved"}' | jq .

echo "=== Approve Checkpoint 2 ==="
curl -s -X POST "$BASE_URL/sessions/$SESSION_ID/approve/checkpoint_2" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Approved"}' | jq .

echo "=== Approve Checkpoint 3 ==="
curl -s -X POST "$BASE_URL/sessions/$SESSION_ID/approve/checkpoint_3" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Approved"}' | jq .


# ============================================================================
# REVIEWER BLOCKED (if high-severity issues)
# ============================================================================
echo "=== Check Review Issues ==="
curl -s "$BASE_URL/sessions/$SESSION_ID/review" \
  -H "Authorization: Bearer $TOKEN" | jq .

echo "=== Resolve Issues ==="
curl -s -X POST "$BASE_URL/sessions/$SESSION_ID/resolve" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "overrides": {
      "generated_fields.0.content": "Fixed bullet text"
    },
    "force_pass": false
  }' | jq .


# ============================================================================
# GET FINAL OUTPUT
# ============================================================================
echo "=== Get Generated CV Data ==="
curl -s "$BASE_URL/sessions/$SESSION_ID/output" \
  -H "Authorization: Bearer $TOKEN" | jq .


# ============================================================================
# DOWNLOAD OUTPUT WORD DOCUMENT
# ============================================================================
echo "=== Get Signed Download URL ==="
SIGNED_URL=$(curl -s "$BASE_URL/sessions/$SESSION_ID/files/output/download-url" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.signed_url')
echo "Signed URL: $SIGNED_URL"

echo "=== Download Document ==="
curl -s "$SIGNED_URL" -o output_round_1.docx
echo "Downloaded to: output_round_1.docx"


# ============================================================================
# REVISION WORKFLOW (after session is completed)
# ============================================================================
echo "=== Submit Revision Comments ==="
curl -s -X POST "$BASE_URL/sessions/$SESSION_ID/comments" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "comment": "Please emphasize renewable energy expertise more"
  }' | jq .

# Session will re-run Phase 3, then halt at checkpoint_3_pending
# Approve checkpoint_3 again to re-render and get new output


# ============================================================================
# USEFUL QUERIES
# ============================================================================

# Poll until processing complete (simple bash loop)
echo "=== Monitor Until Complete (polling every 3s) ==="
while true; do
  STATUS=$(curl -s "$BASE_URL/sessions/$SESSION_ID/status" \
    -H "Authorization: Bearer $TOKEN" | jq -r '.status')
  echo "Status: $STATUS"
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  sleep 3
done

# Get all steps in pipeline
echo "=== List Pipeline Steps ==="
curl -s "$BASE_URL/sessions/$SESSION_ID/manifest" \
  -H "Authorization: Bearer $TOKEN" | jq '.steps[] | {name, status, completed_at}'

# Check for errors
echo "=== Check for Errors ==="
curl -s "$BASE_URL/sessions/$SESSION_ID/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.error_message'
