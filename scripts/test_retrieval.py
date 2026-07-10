"""
Quick CLI to verify retrieval quality.
Run: python -m scripts.test_retrieval "show me top branches by AUM"
"""
import sys
from app.agent.retriever import get_retriever


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m scripts.test_retrieval "your question"')
        sys.exit(1)
    q = " ".join(sys.argv[1:])
    r = get_retriever()

    print(f"\nQuery: {q}\n")
    print("--- Top schema tables ---")
    for h in r.retrieve_schema(q, k=5):
        print(f"  [{h.score:.3f}] {h.table}")
    print("\n--- Top few-shot examples ---")
    for h in r.retrieve_few_shots(q, k=4):
        print(f"  [{h.score:.3f}] ({h.category}) {h.question}")


if __name__ == "__main__":
    main()
