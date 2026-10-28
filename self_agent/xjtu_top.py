"""Signed XJTU TOP adapter for the verified fresh-conversation text flow.

Only the runtime process opens its protected credential file. No account key is
included in a release archive, command argument, URL, or log entry.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


MAX_JSON = 1024 * 1024
MAX_STREAM = 4 * 1024 * 1024
REGION = "cn-north-1"
SERVICE = "aigw"
VERSION = "2023-08-01"


@dataclass(frozen=True)
class Credentials:
    access_key_id: str
    access_key_secret: str
    account_id: str
    workspace_id: str
    model_service_id: str

    @classmethod
    def from_file(cls, filename: str) -> Credentials:
        path = Path(filename)
        if not path.is_file() or path.stat().st_size > 4096:
            raise ValueError("Protected XJTU credential file is missing or oversized")
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("Invalid XJTU credential file")
        keys = ("access_key_id", "access_key_secret", "account_id", "workspace_id", "model_service_id")
        if set(values) != set(keys) or not all(isinstance(values[k], str) and values[k].strip() for k in keys):
            raise ValueError("Incomplete XJTU credential file")
        return cls(*(values[k].strip() for k in keys))

    @classmethod
    def from_archive(cls, filename: str, account_id: str, workspace_id: str, model_service_id: str) -> Credentials:
        """Read only the tiny AK/SK entry at runtime; never extract the ZIP."""
        path = Path(filename)
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("Protected XJTU archive is missing or oversized")
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("Protected XJTU archive permissions are too broad")
        with zipfile.ZipFile(path) as archive:
            matches = [item for item in archive.infolist() if item.filename.startswith("secrets/") and item.filename.endswith(".txt")]
            if len(matches) != 1 or matches[0].file_size > 4096:
                raise ValueError("Expected exactly one small XJTU key entry")
            raw = archive.read(matches[0]).decode("utf-8-sig")
        values: dict[str, str] = {}
        try:
            document = json.loads(raw)
            if isinstance(document, dict):
                for name, value in document.items():
                    values[re.sub(r"[^a-z0-9]", "", name.lower())] = str(value).strip()
        except ValueError:
            for line in raw.splitlines():
                parts = re.split(r"\s*[:：=]\s*", line, maxsplit=1)
                if len(parts) == 2:
                    values[re.sub(r"[^a-z0-9]", "", parts[0].lower())] = parts[1].strip()
        access_key_id = next((values[name] for name in ("accesskeyid", "accesskey", "ak") if values.get(name)), "")
        access_key_secret = next((values[name] for name in ("accesskeysecret", "secretaccesskey", "secretkey", "sk") if values.get(name)), "")
        if not (8 <= len(access_key_id) <= 256 and 8 <= len(access_key_secret) <= 256):
            raise ValueError("XJTU archive key format is not recognized")
        if not all(value and len(value) <= 128 for value in (account_id, workspace_id, model_service_id)):
            raise ValueError("XJTU account/workspace/model IDs are required")
        return cls(access_key_id, access_key_secret, account_id, workspace_id, model_service_id)


class TopError(Exception):
    """Generic upstream failure; never include sensitive payloads in messages."""
    def __init__(self,message,*,action=None,http_status=None,upstream_code=None,rate_receipt=None):
        super().__init__(message);self.action=action;self.http_status=http_status;self.upstream_code=upstream_code;self.rate_receipt=rate_receipt

def error_code(raw):
    try:value=json.loads(raw).get('ResponseMetadata',{}).get('Error',{}).get('Code')
    except (ValueError,AttributeError,TypeError):return None
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',value) else None



@dataclass(frozen=True)
class ModelRoute:
    public_id: str
    service_id: str
    upstream_name: str
    source_type: str


def _mac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def sign_headers(credentials: Credentials, host: str, query: str, body: bytes, now: dt.datetime) -> dict[str, str]:
    stamp = now.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    body_hash = hashlib.sha256(body).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Host": host,
        "X-Content-Sha256": body_hash,
        "X-Date": stamp,
        "X-Top-Service": SERVICE,
    }
    ordered = sorted(headers.items(), key=lambda pair: pair[0].lower())
    canonical_headers = "".join(name.lower() + ":" + value + "\n" for name, value in ordered)
    signed_headers = ";".join(name.lower() for name, _ in ordered)
    canonical_request = "\n".join(("POST", "/", query, canonical_headers, signed_headers, body_hash))
    scope = f"{date}/{REGION}/{SERVICE}/request"
    signing_text = "\n".join(("HMAC-SHA256", stamp, scope, hashlib.sha256(canonical_request.encode()).hexdigest()))
    signing_key = _mac(_mac(_mac(_mac(credentials.access_key_secret.encode(), date.encode()), REGION.encode()), SERVICE.encode()), b"request")
    signature = _mac(signing_key, signing_text.encode()).hex()
    headers["Authorization"] = f"HMAC-SHA256 Credential={credentials.access_key_id}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    return headers


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, msg, headers, newurl):
        return None


class TopClient:
    def __init__(self, credentials: Credentials, url: str = "http://ai.xjtu.edu.cn:30040/", allow_campus_http: bool = False, observer=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("Invalid XJTU TOP URL")
        if parsed.scheme == "http" and not (allow_campus_http and parsed.hostname == "ai.xjtu.edu.cn") and parsed.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("Plain HTTP is restricted to the verified campus host")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Invalid XJTU TOP URL")
        self.credentials = credentials
        self.observer=observer
        self.url = f"{parsed.scheme}://{parsed.netloc}/"
        self.host = parsed.netloc
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _notify(self,action,phase,**values):
        if self.observer:self.observer({'action':action,'phase':phase,'at':dt.datetime.now(dt.timezone.utc).timestamp(),**values})

    def _request(self, action: str, payload: dict, stream: bool = False):
        query = {
            "Action": action,
            "Version": VERSION,
            "X-Account-Id": self.credentials.account_id,
        }
        encoded = "&".join(
            urllib.parse.quote(key, safe="-_.~") + "=" + urllib.parse.quote(value, safe="-_.~")
            for key, value in sorted(query.items())
        )
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = sign_headers(self.credentials, self.host, encoded, body, dt.datetime.now(dt.timezone.utc))
        if stream:
            headers["Accept"] = "text/event-stream"
        request = urllib.request.Request(self.url + "?" + encoded, data=body, headers=headers, method="POST")
        self._notify(action,'sending')
        try:
            response=self.opener.open(request, timeout=120 if stream else 20)
            self._notify(action,'received',http_status=response.status)
            return response
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError) as exc:
            status=exc.code if isinstance(exc,urllib.error.HTTPError) else None;code=None;receipt=None
            if isinstance(exc,urllib.error.HTTPError):
                try:
                    body=exc.read(65536);code=error_code(body)
                    from .native_rate import rate_receipt
                    receipt=rate_receipt(status,body,dict(exc.headers or {}))
                except OSError:pass
                finally:exc.close()
            self._notify(action,'failed',http_status=status,upstream_code=code,rate_receipt=receipt)
            raise TopError("XJTU TOP request failed",action=action,http_status=status,upstream_code=code,rate_receipt=receipt) from None

    def call(self, action: str, payload: dict) -> dict:
        with self._request(action, payload) as response:
            if response.status != 200:
                raise TopError("XJTU TOP request failed")
            raw = response.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise TopError("XJTU TOP response too large")
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("not an object")
            if result.get("ResponseMetadata", {}).get("Error"):
                raise TopError("XJTU TOP rejected the request",action=action,http_status=200,upstream_code=error_code(raw))
            return result["Result"]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise TopError("Unexpected XJTU TOP response") from None

    def open_chat(self, session_id: str, message_id: str):
        payload = {"SessionID": session_id, "MessageID": message_id, "WorkspaceID": self.credentials.workspace_id}
        response = self._request("Chat", payload, stream=True)
        if response.status != 200 or "text/event-stream" not in response.headers.get("Content-Type", ""):
            response.close()
            raise TopError("XJTU Chat did not return an event stream")
        return response

    def iter_chat(self, response, conversation_id: str):
        chunks: list[str] = []
        total = 0
        finished = False
        while True:
            line = response.readline(65537)
            if not line:
                break
            total += len(line)
            if total > MAX_STREAM or len(line) > 65536:
                raise TopError("XJTU Chat response too large")
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                finished = True
                break
            try:
                event = json.loads(data)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("error"):
                raise TopError("XJTU Chat failed")
            for choice in event.get("choices", []):
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                content = delta.get("content") if isinstance(delta, dict) else None
                if isinstance(content, str) and content:
                    chunks.append(content)
                    yield content
                reason = choice.get("finish_reason")
                if reason not in (None, "stop"):
                    raise TopError("XJTU Chat did not finish normally")
                if reason == "stop":
                    finished = True
        answer = "".join(chunks).strip()
        if not answer:
            raise TopError("XJTU Chat returned no text")
        if not finished:
            # The verified sample did not document a mandatory terminal event.
            # Accept EOF only if the stored assistant reply exactly matches it.
            stored = self.call("GetConversationMessages", {
                "ConversationID": conversation_id,
                "WorkspaceID": self.credentials.workspace_id,
            })
            entries = stored.get("MessageList", stored.get("Messages", []))
            if not isinstance(entries, list) or not any(
                isinstance(entry, dict)
                and str(entry.get("AuthorRole")) == "1"
                and isinstance(entry.get("Content"), str)
                and entry["Content"].strip() == answer
                for entry in entries
            ):
                raise TopError("XJTU Chat completion was not confirmed")
        return answer

    def list_text_models(self) -> dict[str, ModelRoute]:
        result = self.call("ListModelByWorkspaceGrant", {"WorkspaceID": self.credentials.workspace_id})
        items = result.get("Items")
        if not isinstance(items, list):
            raise TopError("Invalid TOP model catalog")
        routes: dict[str, ModelRoute] = {}
        for item in items:
            if (not isinstance(item, dict) or item.get("Type") != "text-generation" or item.get("Status") != "Running"
                    or item.get("Granted") is not True or item.get("IsPublished") is not True):
                continue
            public_id, service_id = item.get("Name"), item.get("ID")
            upstream_name, source_type = item.get("ModelName"), item.get("PublishSourceType")
            if not all(isinstance(value, str) and value and len(value) <= 128 for value in (public_id, service_id, upstream_name, source_type)):
                continue
            if public_id in routes:
                raise TopError("Duplicate TOP model name")
            routes[public_id] = ModelRoute(public_id, service_id, upstream_name, source_type)
        return routes

    def prepare(self, question: str, model: ModelRoute | None = None) -> tuple[str, str, str]:
        workspace = self.credentials.workspace_id
        route = model or ModelRoute("kimi-k3", self.credentials.model_service_id, "qwen/kimi^kimi-k3", "external")
        created = self.call("CreateConversation", {
            "ConversationName": "MatterSwarm API",
            "WorkspaceID": workspace,
            "Models": [{"ModelServiceID": route.service_id, "ModelName": route.upstream_name, "PublishSourceType": route.source_type}],
        })["ConversationInfo"]
        conversation_id = created["ConversationID"]
        session_id = created["ProjectList"][0]["SessionID"]
        self._notify("CreateConversation","prepared",conversation_id=conversation_id,session_id=session_id)
        inserted = self.call("BatchCreateMessages", {
            "ConversationID": conversation_id,
            "WorkspaceID": workspace,
            "MessageList": [{"SessionID": session_id, "ContentType": "text", "Content": question}],
        })["MessageList"][0]
        self._notify("BatchCreateMessages","prepared",conversation_id=conversation_id,session_id=session_id,message_id=inserted["MessageID"])
        return conversation_id, session_id, inserted["MessageID"]

    def complete(self, question: str, model: ModelRoute | None = None) -> str:
        conversation_id, session_id, message_id = self.prepare(question, model)
        with self.open_chat(session_id, message_id) as response:
            answer="".join(self.iter_chat(response, conversation_id)).strip()
        self._notify("Chat","completed",conversation_id=conversation_id)
        return answer
