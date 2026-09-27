"""Operator deletion when a person cannot be recognized. Takes an opaque profile ID."""

import argparse

from dotenv import load_dotenv

from jarvis.memory import build_memory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id")
    args = parser.parse_args()
    load_dotenv()
    memory = build_memory()
    if not memory.enabled:
        raise SystemExit(
            "Memory is unavailable; configure the original encryption key and database"
        )
    try:
        print(memory.store.delete_user_data(args.user_id))
        memory.store.replay()
        print(memory.store.health())
    finally:
        memory.close()


if __name__ == "__main__":
    main()
