#!/usr/bin/env python3
"""Prints a quick reference of every command in this project.

Usage:
    python scripts/help.py
"""

SECTIONS = [
    ("First-time setup", [
        ("python scripts/setup.py", "Create config.json, generate the encryption key, "
                                     "and enter secrets (Telegram token, RPC API keys)."),
        ("python scripts/migrate_secrets.py", "Already have a config.json with real secrets "
                                                "in plaintext? Run this instead -- it extracts "
                                                "and encrypts them, then rewrites config.json "
                                                "to use ${placeholders}."),
    ]),
    ("Running", [
        ("python main.py", "Run directly (needs venv + requirements.txt installed)."),
        ("docker compose up -d --build", "Build and run in the background via Docker."),
        ("docker compose logs -f", "Follow logs when running via Docker."),
        ("docker compose down", "Stop the Docker container."),
        ("sudo systemctl start aave-monitor", "Run via systemd (bare-metal, no Docker)."),
        ("sudo systemctl status aave-monitor", "Check systemd service status."),
        ("journalctl -u aave-monitor -f", "Follow logs when running via systemd."),
    ]),
    ("Secrets", [
        ("python scripts/update_secret.py", "List known secrets, then update one interactively."),
        ("python scripts/update_secret.py <name>", "Update a specific secret directly, e.g. "
                                                     "telegram_bot_token."),
    ]),
    ("Maintenance", [
        ("pip install -r requirements.txt", "Install/update Python dependencies."),
        ("python scripts/help.py", "Show this message."),
    ]),
]


def main():
    print("Aave Monitor -- command reference\n")

    for title, rows in SECTIONS:
        print(f"{title}:")
        width = max(len(cmd) for cmd, _ in rows)
        for cmd, desc in rows:
            print(f"  {cmd.ljust(width)}  {desc}")
        print()


if __name__ == "__main__":
    main()
