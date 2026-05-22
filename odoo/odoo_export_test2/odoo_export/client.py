import logging
import time
import xmlrpc.client
from typing import Any, cast

log = logging.getLogger(__name__)


class OdooClient:
    """
    Handles authentication and raw API calls to Odoo via XML-RPC.
    API key is used as the password for authentication.
    """

    def __init__(self, url: str, db: str, username: str, api_key: str):
        self.url = url
        self.db = db
        self.username = username
        self.api_key = api_key
        self.uid = None
        self._models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def verify_connection(self) -> None:
        """Authenticate and confirm the API key is valid."""
        log.info(f"Connecting to {self.url}...")
        try:
            common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
            version = cast(dict, common.version())
            log.info(f"Server reachable. Odoo version: {version.get('server_version', 'unknown')}")
            self.uid = common.authenticate(self.db, self.username, self.api_key, {})
        except Exception as e:
            log.error(f"Could not reach Odoo: {e}")
            raise

        if not self.uid:
            raise RuntimeError("Authentication failed — check your username and API key.")
        log.info(f"Authenticated as: {self.username} (uid={self.uid})")

    def valid_fields(self, model: str, requested: list[str]) -> list[str]:
        """Return only the fields from `requested` that are fetchable via search_read."""
        info = self.execute(model, "fields_get", attributes=["string"])
        available = set(info.keys())
        declared = [f for f in requested if f in available]

        skipped = [f for f in requested if f not in available]
        if skipped:
            log.debug(f"{model}: fields absent from fields_get: {skipped}")

        return self._probe_fields(model, declared)

    def _probe_fields(self, model: str, fields: list[str]) -> list[str]:
        """Binary-eliminate any fields that fields_get accepts but search_read rejects."""
        if not fields:
            return []
        try:
            self.execute(model, "search_read", domain=[], fields=fields, limit=1)
            return fields
        except RuntimeError:
            if len(fields) == 1:
                log.warning(f"{model}: field '{fields[0]}' rejected by search_read, skipping")
                return []
            mid = len(fields) // 2
            return self._probe_fields(model, fields[:mid]) + self._probe_fields(model, fields[mid:])

    def execute(self, model: str, method: str, max_retries: int = 3, **kwargs) -> Any:
        """
        Call any Odoo model method via XML-RPC execute_kw.
        Keyword args are passed directly; 'ids' and 'domain' are promoted to positional args.
        """
        if not self.uid:
            raise RuntimeError("Not authenticated. Call verify_connection() first.")

        args = []
        if "ids" in kwargs:
            args = [kwargs.pop("ids")]
        elif method in ("search", "search_read", "search_count"):
            args = [kwargs.pop("domain", [])]

        for attempt in range(1, max_retries + 1):
            try:
                return self._models.execute_kw(
                    self.db, self.uid, self.api_key,
                    model, method, args, kwargs,
                )
            except xmlrpc.client.Fault as e:
                raise RuntimeError(f"Odoo error ({model}.{method}): {e.faultString}") from e
            except (xmlrpc.client.ProtocolError, OSError, TimeoutError) as e:
                log.warning(f"Attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    wait = 2 ** attempt
                    log.info(f"Retrying in {wait}s...")
                    time.sleep(wait)

        raise RuntimeError(f"All {max_retries} attempts failed for {model}.{method}")
