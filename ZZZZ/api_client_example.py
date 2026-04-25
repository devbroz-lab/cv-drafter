"""
CV Reformatter API Client Example
Demonstrates how to interact with the API using Python requests library
"""

import json
import time
from pathlib import Path

import requests

# Configuration
BASE_URL = "http://127.0.0.1:8000"
TOKEN = "<SUPABASE_JWT_TOKEN>"  # Replace with your JWT token

# Headers for authenticated requests
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


class CVReformatterClient:
    """Simple client for CV Reformatter API"""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def health_check(self) -> dict:
        """Check if server is running"""
        resp = requests.get(f"{self.base_url}/health")
        return resp.json()

    def create_session(
        self,
        target_format: str,
        source_filename: str,
        proposed_position: str = "",
        category: str = "",
        employer: str = "",
        years_with_firm: str = "",
        page_limit: int = None,
        job_description: str = "",
    ) -> dict:
        """Create a new session"""
        payload = {
            "target_format": target_format,
            "source_filename": source_filename,
            "proposed_position": proposed_position,
            "category": category,
            "employer": employer,
            "years_with_firm": years_with_firm,
        }
        if page_limit:
            payload["page_limit"] = page_limit
        if job_description:
            payload["job_description"] = job_description

        resp = requests.post(
            f"{self.base_url}/sessions",
            headers=self.headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def get_session_status(self, session_id: str) -> dict:
        """Get current session status"""
        resp = requests.get(
            f"{self.base_url}/sessions/{session_id}/status",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    def upload_cv(self, session_id: str, filepath: str) -> dict:
        """Upload source CV file"""
        with open(filepath, "rb") as f:
            files = {"file": f}
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = requests.post(
                f"{self.base_url}/sessions/{session_id}/upload/source",
                headers=headers,
                files=files,
            )
        resp.raise_for_status()
        return resp.json()

    def upload_tor(self, session_id: str, filepath: str) -> dict:
        """Upload Terms of Reference file (optional)"""
        with open(filepath, "rb") as f:
            files = {"file": f}
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = requests.post(
                f"{self.base_url}/sessions/{session_id}/upload/tor",
                headers=headers,
                files=files,
            )
        resp.raise_for_status()
        return resp.json()

    def start_processing(self, session_id: str) -> dict:
        """Start Phase 1 processing"""
        resp = requests.post(
            f"{self.base_url}/sessions/{session_id}/start",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    def get_manifest(self, session_id: str) -> dict:
        """Get step-by-step progress manifest"""
        resp = requests.get(
            f"{self.base_url}/sessions/{session_id}/manifest",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    def approve_checkpoint(self, session_id: str, checkpoint: str, notes: str = "") -> dict:
        """Approve a checkpoint and resume pipeline"""
        payload = {"notes": notes}
        resp = requests.post(
            f"{self.base_url}/sessions/{session_id}/approve/{checkpoint}",
            headers=self.headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def get_review(self, session_id: str) -> dict:
        """Get content reviewer's assessment (high/low severity issues)"""
        resp = requests.get(
            f"{self.base_url}/sessions/{session_id}/review",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    def resolve_review(
        self, session_id: str, overrides: dict = None, force_pass: bool = False
    ) -> dict:
        """Resolve high-severity review issues"""
        payload = {
            "overrides": overrides or {},
            "force_pass": force_pass,
        }
        resp = requests.post(
            f"{self.base_url}/sessions/{session_id}/resolve",
            headers=self.headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def get_output(self, session_id: str) -> dict:
        """Get final generated CV data"""
        resp = requests.get(
            f"{self.base_url}/sessions/{session_id}/output",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    def get_download_url(self, session_id: str, file_type: str = "output") -> str:
        """
        Get signed download URL for a file.
        file_type: 'source', 'tor', or 'output'
        """
        resp = requests.get(
            f"{self.base_url}/sessions/{session_id}/files/{file_type}/download-url",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()["signed_url"]

    def submit_revision(self, session_id: str, comment: str) -> dict:
        """Submit revision feedback (only for completed sessions)"""
        payload = {"comment": comment}
        resp = requests.post(
            f"{self.base_url}/sessions/{session_id}/comments",
            headers=self.headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def wait_for_checkpoint(self, session_id: str, checkpoint: str, timeout: int = 600):
        """Poll until a checkpoint is reached"""
        elapsed = 0
        while elapsed < timeout:
            manifest = self.get_manifest(session_id)
            if manifest.get("checkpoint_pending") == checkpoint:
                return True
            if manifest.get("db_status") == "failed":
                raise RuntimeError(f"Session failed: {self.get_session_status(session_id)}")
            time.sleep(3)
            elapsed += 3
        raise TimeoutError(f"Timeout waiting for {checkpoint}")


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Initialize client
    client = CVReformatterClient(BASE_URL, TOKEN)

    # 1. Health check
    print("1. Health check...")
    health = client.health_check()
    print(f"   Status: {health['status']}")

    # 2. Create session
    print("\n2. Creating session...")
    session = client.create_session(
        target_format="giz",
        source_filename="cv.docx",
        proposed_position="Senior Water Engineer",
        category="Senior Expert",
        employer="ABC Consulting",
        years_with_firm="5",
        page_limit=4,
    )
    session_id = session["session_id"]
    print(f"   Session ID: {session_id}")
    print(f"   Status: {session['status']}")

    # 3. Upload CV
    print("\n3. Uploading CV...")
    upload = client.upload_cv(session_id, "/path/to/cv.docx")
    print(f"   Storage key: {upload['storage_key']}")

    # 4. Upload ToR (optional)
    print("\n4. Uploading Terms of Reference...")
    upload = client.upload_tor(session_id, "/path/to/tor.pdf")
    print(f"   Storage key: {upload['storage_key']}")

    # 5. Start processing (Phase 1)
    print("\n5. Starting processing...")
    start = client.start_processing(session_id)
    print(f"   Status: {start['status']}")

    # 6. Wait for checkpoint 1
    print("\n6. Waiting for checkpoint 1...")
    client.wait_for_checkpoint(session_id, "checkpoint_1", timeout=300)
    print("   Checkpoint 1 reached!")

    # 7. Check manifest
    manifest = client.get_manifest(session_id)
    print(f"   Steps completed:")
    for step in manifest["steps"]:
        if step["status"] == "done":
            print(f"     ✓ {step['name']}")

    # 8. Approve checkpoint 1 (resume Phase 2)
    print("\n7. Approving checkpoint 1...")
    approval = client.approve_checkpoint(session_id, "checkpoint_1", notes="Looks good")
    print(f"   Next phase: {approval['next_phase']}")

    # 9. Wait for checkpoint 2
    print("\n8. Waiting for checkpoint 2...")
    client.wait_for_checkpoint(session_id, "checkpoint_2", timeout=300)
    print("   Checkpoint 2 reached!")

    # 10. Approve checkpoint 2 (resume Phase 3)
    print("\n9. Approving checkpoint 2...")
    client.approve_checkpoint(session_id, "checkpoint_2", notes="Approved")

    # 11. Wait for checkpoint 3 or reviewer_blocked
    print("\n10. Waiting for checkpoint 3 or reviewer block...")
    manifest = client.get_manifest(session_id)
    if manifest.get("reviewer_blocked"):
        print("   Reviewer blocked - checking issues...")
        review = client.get_review(session_id)
        print(f"   High severity issues: {len(review['high_severity'])}")
        # Resolve and re-run
        client.resolve_review(session_id, force_pass=False)
        client.wait_for_checkpoint(session_id, "checkpoint_3")

    # 12. Approve checkpoint 3 (resume Phase 4 - renderer)
    print("\n11. Approving checkpoint 3...")
    client.approve_checkpoint(session_id, "checkpoint_3")

    # 13. Wait for completion
    print("\n12. Waiting for processing to complete...")
    while True:
        status = client.get_session_status(session_id)
        if status["status"] == "completed":
            print("   ✓ Processing complete!")
            break
        if status["status"] == "failed":
            print(f"   ✗ Failed: {status['error_message']}")
            break
        time.sleep(3)

    # 14. Get output data
    print("\n13. Retrieving final CV data...")
    output = client.get_output(session_id)
    print(f"   Position: {output['cv_data']['proposed_position']}")
    print(f"   Warnings: {len(output['generation_warnings'])}")

    # 15. Download output document
    print("\n14. Getting download URL...")
    url = client.get_download_url(session_id, "output")
    print(f"   URL: {url[:80]}...")
    # Download file if needed:
    # import urllib.request
    # urllib.request.urlretrieve(url, "output.docx")

    # 16. Revision example (after completion)
    print("\n15. Submitting revision comment...")
    revision = client.submit_revision(session_id, "Please emphasize renewable energy more")
    print(f"   Round: {revision['round']}")
    print(f"   Status: {revision['status']}")

    print("\n✓ Workflow complete!")
