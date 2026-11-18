"""Best-effort host cloud region discovery, used only by the detached exporter."""

from __future__ import annotations

import re
from contextlib import closing
from functools import cache
from http.client import HTTPConnection, HTTPException

METADATA_HOST = "169.254.169.254"
METADATA_TIMEOUT_SECONDS = 0.2
MAX_METADATA_BYTES = 1024


def _read_metadata(path: str, headers: dict[str, str], *, method: str = "GET") -> str | None:
    try:
        # Connect directly: proxy settings must not route host metadata off the machine.
        with closing(HTTPConnection(METADATA_HOST, timeout=METADATA_TIMEOUT_SECONDS)) as connection:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            # HTTPConnection does not follow redirects or retry failed requests.
            if response.status != 200:
                return None
            body = response.read(MAX_METADATA_BYTES + 1)
            if len(body) <= MAX_METADATA_BYTES:
                return body.decode("ascii").strip()
    except (OSError, HTTPException, ValueError):
        pass
    return None


@cache
def client_region() -> str | None:
    """Cache successes and misses; API-target environment variables are not host location."""
    token = _read_metadata(
        "/latest/api/token", {"X-aws-ec2-metadata-token-ttl-seconds": "60"}, method="PUT"
    )
    if token:
        region = _read_metadata(
            "/latest/meta-data/placement/region", {"X-aws-ec2-metadata-token": token}
        )
        if region and re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region) and len(region) <= 64:
            return f"aws-{region}"

    region = _read_metadata(
        "/metadata/instance/compute/location?api-version=2021-02-01&format=text",
        {"Metadata": "true"},
    )
    if region and re.fullmatch(r"[a-z][a-z0-9]{1,63}", region):
        return f"azure-{region}"

    zone = _read_metadata("/computeMetadata/v1/instance/zone", {"Metadata-Flavor": "Google"})
    if zone and (match := re.fullmatch(r"projects/[^/\s]+/zones/([a-z]+-[a-z]+\d+)-[a-z]", zone)):
        region = match[1]
        if len(region) <= 64:
            return f"gcp-{region}"
    return None
