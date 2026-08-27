"""
Prints the audit log in a readable form. This is the one place to look
when something needs debugging ("why did this patient's appointment
change?") or when demonstrating HIPAA access controls to an auditor.

Run: python3 scripts/view_audit_log.py [limit]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "mirror_system"))
from audit_log import read_recent


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    rows = read_recent(limit)
    if not rows:
        print("Audit log is empty.")
        return

    for timestamp, actor, action, patient_id, detail, success in rows:
        status = "OK" if success else "FAILED"
        pid = patient_id or "-"
        print(f"{timestamp}  [{status:6}] {actor:30} {action:28} patient={pid:10} {detail}")


if __name__ == "__main__":
    main()
