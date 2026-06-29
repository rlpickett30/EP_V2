#!/usr/bin/env python3
"""
dev_fix_microphone_synced_import.py

Purpose:
    Patch node/communication/communication_dispatcher.py so it imports
    MICROPHONE_SYNCED from communication_event_services.py.

Why:
    communication_dispatcher.py uses MICROPHONE_SYNCED after the timing /
    communication stagger refactor, but the symbol was not included in the
    import list.

Run from repo root:
    python dev_fix_microphone_synced_import.py
"""

from pathlib import Path


TARGET_PATH = Path("node/communication/communication_dispatcher.py")


def main():
    if not TARGET_PATH.exists():
        raise FileNotFoundError(
            f"Could not find target file: {TARGET_PATH}"
        )

    text = TARGET_PATH.read_text(encoding="utf-8")

    if "    MICROPHONE_SYNCED,\n" in text:
        print("MICROPHONE_SYNCED is already imported.")
        return

    old_block = (
        "    AVIS_LITE,\n"
        "    NODE_REGISTER,\n"
    )

    new_block = (
        "    AVIS_LITE,\n"
        "    MICROPHONE_SYNCED,\n"
        "    NODE_REGISTER,\n"
    )

    if old_block not in text:
        raise RuntimeError(
            "Could not find the expected import location near "
            "AVIS_LITE and NODE_REGISTER. No changes were made."
        )

    patched = text.replace(
        old_block,
        new_block,
        1
    )

    TARGET_PATH.write_text(
        patched,
        encoding="utf-8",
        newline="\n"
    )

    print(f"Patched: {TARGET_PATH}")
    print("Added MICROPHONE_SYNCED to the communication_dispatcher import list.")


if __name__ == "__main__":
    main()