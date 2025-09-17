from __future__ import annotations
import logging, re
from functools import lru_cache
from .http_client import VRChatHTTP

log = logging.getLogger(__name__)
_LOC_RE = re.compile(r"^(wrld_[0-9a-fA-F-]+)(?::(.+))?$")

class VRChatAPI:
    def __init__(self,http: VRChatHTTP)->None:
        self.http = http

    def list_friends(self,*,offline:bool,n:int =100)->list[dict]:
        out,offset,n=[],0,min(int(n),100)
        while True:
            r = self.http.s.get(
                "https://api.vrchat.cloud/api/1/auth/user/friends",
                params={"offset":offset,"n":n,"offline":str(offline).lower()},
            )
            if not r.ok:
                log.warning("Failed to fetch friends (offline=%s): %s %s",
                            offline,r.status_code,r.reason)
                break
            chunk = r.json() or []
            if not isinstance(chunk,list)or not chunk:
                break
            out.extend(chunk)
            if len(chunk)<n:
                break
            offset += n
        return out

    def fetch_all_friend_ids(self)->set[str]:
        ids : set[str]=set()
        for offline in (True,False):
            for f in self.list_friends(offline=offline):
                uid = f.get("id")or f.get("userId")
                if uid:
                    ids.add(uid)
        return ids

    @lru_cache(maxsize=2048)
    def display_name(self,user_id:str)->str:
        if not user_id:return ""
        r = self.http.s.get(f"https://api.vrchat.cloud/api/1/users/{user_id}")
        return (r.json() or {}).get("displayName","")if r.ok else ""

    @lru_cache(maxsize=2048)
    def world_name(self,world_id:str)->str:
        if not world_id:return ""
        r = self.http.s.get(f"https://api.vrchat.cloud/api/1/worlds/{world_id}")
        if r.ok:
            name = (r.json() or {}).get("name","")
            return name or world_id
        return world_id

    def parse_location_to_world(self,location: str)->str:
        if not location: return "(unknown)"
        m = _LOC_RE.match(location)
        return self.world_name(m.group(1)) if m else location