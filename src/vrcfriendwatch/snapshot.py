# snapshot.py
from __future__ import annotations
from colorama import Fore, Style
from .vrchat_api import VRChatAPI

def _status_color(status: str | None) -> str:
    if not status: return Fore.WHITE
    s = status.lower()
    if s in ("active", "online"): return Fore.GREEN
    if s in ("busy",):            return Fore.RED
    if s in ("join me", "joinme"):return Fore.CYAN
    if s in ("ask me", "askme", "away"): return Fore.YELLOW
    return Fore.WHITE

def print_initial_snapshot(api: VRChatAPI, target_ids: set[str]) -> None:
    all_friends = api.list_friends(offline=True) + api.list_friends(offline=False)

    by_id: dict[str, dict] = {}
    for f in all_friends:
        uid = f.get("id") or f.get("userId") or (f.get("user") or {}).get("id") or f.get("userID")
        if uid:
            by_id[uid] = f
    all_friends = list(by_id.values())
    show_ids = target_ids or {(f.get("id") or f.get("userId")) for f in all_friends if (f.get("id") or f.get("userId"))}

    print("---- Initial Snapshot ----")
    dropped = 0
    for f in all_friends:
        uid = f.get("id") or f.get("userId") or (f.get("user") or {}).get("id") or f.get("userID")
        if not uid or uid not in show_ids:
            dropped += 1
            continue
        name   = f.get("displayName") or api.display_name(uid) or uid
        status = f.get("status") or "unknown"
        world  = api.parse_location_to_world(f.get("location") or "")
        color  = _status_color(status)
        print(color + f"{name} ({uid}) status={status} location={world}" + Style.RESET_ALL)

    if dropped:
        print(Fore.MAGENTA + f"[SNAPSHOT] dropped: {dropped}" + Style.RESET_ALL)
    print(Fore.CYAN + f"[SNAPSHOT] |all_friends|={len(all_friends)} |targets|={len(show_ids)}" + Style.RESET_ALL)
