"""
End-to-end agent test from the command line.
Run: python -m scripts.ask "How many customers do we have by occupation?"
"""
import json
import logging
import sys

from app.agent.runner import run


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

    if len(sys.argv) < 2:
        print('Usage: python -m scripts.ask "your question"')
        sys.exit(1)

    q = " ".join(sys.argv[1:])
    res = run(q)

    print("\n" + "=" * 72)
    print(f"Q: {res.question}")
    print("=" * 72)
    print(f"Success: {res.success}    Latency: {res.total_elapsed_ms} ms    Attempts: {len(res.attempts)}")
    print(f"Retrieved tables : {res.retrieved_tables}")
    print(f"Retrieved examples: {res.retrieved_examples[:3]}{'...' if len(res.retrieved_examples) > 3 else ''}")
    print()

    for i, a in enumerate(res.attempts, 1):
        marker = "✓" if (a.safety_ok and a.exec_ok) else "✗"
        why = ""
        if not a.safety_ok:
            why = f"safety/{a.safety_stage}: {a.safety_reason}"
        elif a.exec_ok is False:
            why = f"exec: {a.exec_error}"
        print(f"  attempt {i} {marker}  {a.elapsed_ms} ms  {why}")

    if res.success:
        print(f"\nSQL:\n{res.sql}\n")
        print(f"{res.row_count} row(s){' (truncated)' if res.truncated else ''}")
        print(json.dumps(res.rows[:10], indent=2, default=str))
    else:
        print(f"\nFAILED: {res.error}")


if __name__ == "__main__":
    main()
