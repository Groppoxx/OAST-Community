from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import ssl
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_NAME = "OAST Community"
VERSION = "1.0.0"

ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

DEFAULT_DOMAIN = "oastify.com"
DEFAULT_POLL_HOST = "polling.oastify.com"
DEFAULT_INTERVAL = 5.0
DEFAULT_TIMEOUT = 15.0

STATE_VERSION = 1
STATE_DIR = Path.home() / ".oast-community"

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class Console:
    def __init__(
        self,
        no_color: bool = False,
        debug_enabled: bool = False,
    ) -> None:
        self.no_color = no_color or not sys.stdout.isatty()
        self.debug_enabled = debug_enabled

    def color(
        self,
        text: str,
        code: str,
    ) -> str:
        if self.no_color:
            return text

        return f"{code}{text}{RESET}"

    def log(
        self,
        marker: str,
        message: str,
        color: str = RESET,
    ) -> None:
        timestamp = (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        prefix = self.color(
            f"[{timestamp}]",
            DIM,
        )

        print(
            f"{prefix} "
            f"{self.color(marker, color)} "
            f"{message}",
            flush=True,
        )

    def info(
        self,
        message: str,
    ) -> None:
        self.log(
            "[*]",
            message,
            CYAN,
        )

    def ok(
        self,
        message: str,
    ) -> None:
        self.log(
            "[+]",
            message,
            GREEN,
        )

    def warn(
        self,
        message: str,
    ) -> None:
        self.log(
            "[!]",
            message,
            YELLOW,
        )

    def error(
        self,
        message: str,
    ) -> None:
        self.log(
            "[-]",
            message,
            RED,
        )

    def debug(
        self,
        message: str,
    ) -> None:
        if self.debug_enabled:
            self.log(
                "[d]",
                message,
                DIM,
            )


console = Console()


# ============================================================
# UI helpers
# ============================================================

def visible_len(
    text: str,
) -> int:
    return len(
        ANSI_RE.sub(
            "",
            text,
        )
    )


def box_top(
    width: int,
) -> str:
    return console.color(
        "╭"
        + ("─" * width)
        + "╮",
        MAGENTA,
    )


def box_separator(
    width: int,
) -> str:
    return console.color(
        "├"
        + ("─" * width)
        + "┤",
        MAGENTA,
    )


def box_bottom(
    width: int,
) -> str:
    return console.color(
        "╰"
        + ("─" * width)
        + "╯",
        MAGENTA,
    )


def box_line(
    content: str,
    width: int,
) -> str:
    padding = max(
        0,
        width
        - visible_len(content),
    )

    return (
        console.color(
            "│",
            MAGENTA,
        )
        + content
        + (" " * padding)
        + console.color(
            "│",
            MAGENTA,
        )
    )


def wrap_box_text(
    text: str,
    width: int,
    indent: str = "  ",
) -> list[str]:
    available = max(
        1,
        width
        - visible_len(indent),
    )

    parts = textwrap.wrap(
        text,
        width=available,
        replace_whitespace=False,
        drop_whitespace=False,
        break_long_words=True,
        break_on_hyphens=False,
    )

    if not parts:
        return [indent]

    return [
        indent + part
        for part in parts
    ]


def pause() -> None:
    try:
        input(
            console.color(
                "Press Enter to return...",
                DIM,
            )
        )

    except (
        EOFError,
        KeyboardInterrupt,
    ):
        print("")


# ============================================================
# Data models
# ============================================================

@dataclass(
    frozen=True
)
class Config:
    domain: str
    poll_host: str

    interval: float
    timeout: float

    state_file: Path | None


@dataclass
class ClientContext:
    biid: str

    counter: int = 0

    payloads: dict[
        str,
        int,
    ] = field(
        default_factory=dict
    )

    @classmethod
    def create(
        cls,
    ) -> "ClientContext":
        raw_biid = os.urandom(
            32
        )

        biid = (
            base64
            .b64encode(
                raw_biid
            )
            .decode(
                "ascii"
            )
        )

        return cls(
            biid=biid
        )

    @property
    def raw_biid(
        self,
    ) -> bytes:
        raw = (
            base64
            .b64decode(
                self.biid,
                validate=True,
            )
        )

        if len(raw) != 32:
            raise ValueError(
                "Invalid BIID length"
            )

        return raw

    def payload_number(
        self,
        interaction_id: Any,
    ) -> int | None:
        if not isinstance(
            interaction_id,
            str,
        ):
            return None

        return self.payloads.get(
            interaction_id
        )

    def latest_payload(
        self,
        config: Config,
    ) -> tuple[
        int,
        str,
    ] | None:
        if not self.payloads:
            return None

        interaction_id = max(
            self.payloads,
            key=self.payloads.get,
        )

        number = (
            self.payloads[
                interaction_id
            ]
        )

        return (
            number,
            f"{interaction_id}.{config.domain}",
        )

    def to_dict(
        self,
        config: Config,
    ) -> dict[
        str,
        Any,
    ]:
        return {
            "version":
                STATE_VERSION,

            "domain":
                config.domain,

            "poll_host":
                config.poll_host,

            "biid":
                self.biid,

            "counter":
                self.counter,

            "payloads":
                self.payloads,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[
            str,
            Any,
        ],
        config: Config,
    ) -> "ClientContext":
        if (
            data.get(
                "version"
            )
            != STATE_VERSION
        ):
            raise ValueError(
                "Unsupported state version"
            )

        if (
            data.get(
                "domain"
            )
            != config.domain
            or
            data.get(
                "poll_host"
            )
            != config.poll_host
        ):
            raise ValueError(
                "State belongs to a different "
                "Collaborator server"
            )

        biid = data.get(
            "biid"
        )

        counter = data.get(
            "counter"
        )

        payloads = data.get(
            "payloads"
        )

        if not isinstance(
            biid,
            str,
        ):
            raise ValueError(
                "Invalid BIID"
            )

        raw_biid = (
            base64
            .b64decode(
                biid,
                validate=True,
            )
        )

        if len(raw_biid) != 32:
            raise ValueError(
                "Invalid BIID length"
            )

        if (
            not isinstance(
                counter,
                int,
            )
            or counter < 0
        ):
            raise ValueError(
                "Invalid payload counter"
            )

        if not isinstance(
            payloads,
            dict,
        ):
            raise ValueError(
                "Invalid payload registry"
            )

        clean_payloads: dict[
            str,
            int,
        ] = {}

        for (
            interaction_id,
            number,
        ) in payloads.items():

            if (
                isinstance(
                    interaction_id,
                    str,
                )
                and interaction_id
                and isinstance(
                    number,
                    int,
                )
                and number > 0
            ):
                clean_payloads[
                    interaction_id
                ] = number

        if clean_payloads:
            counter = max(
                counter,
                max(
                    clean_payloads.values()
                ),
            )

        return cls(
            biid=biid,
            counter=counter,
            payloads=clean_payloads,
        )


# ============================================================
# Payload generation
# ============================================================

def base36_encode(
    number: int,
) -> str:
    if number < 0:
        raise ValueError(
            "Number must be non-negative"
        )

    if number == 0:
        return ALPHABET[0]

    result: list[str] = []

    while number:
        (
            number,
            remainder,
        ) = divmod(
            number,
            36,
        )

        result.append(
            ALPHABET[
                remainder
            ]
        )

    return "".join(
        reversed(
            result
        )
    )


def checksum_char(
    value: str,
) -> str:
    checksum = sum(
        ord(character)
        for character in value
    )

    return ALPHABET[
        checksum % 36
    ]


def derive_key_hash(
    raw_biid: bytes,
) -> str:
    digest = (
        hashlib
        .sha1(
            raw_biid
        )
        .digest()
    )

    encoded = (
        base36_encode(
            int.from_bytes(
                digest,
                byteorder="big",
                signed=False,
            )
        )
        .rjust(
            20,
            "a",
        )
    )

    key = encoded[
        :20
    ]

    left = key[
        :10
    ]

    right = key[
        10:20
    ]

    return (
        left
        + checksum_char(
            left
        )
        + right
        + checksum_char(
            right
        )
    )


def encrypt_interaction_id(
    plaintext: str,
) -> str:
    salt_1 = secrets.choice(
        ALPHABET
    )

    salt_2 = secrets.choice(
        ALPHABET
    )

    state = [
        salt_1,
        salt_2,
    ]

    encrypted: list[
        str
    ] = []

    for (
        index,
        character,
    ) in enumerate(
        plaintext
    ):

        if character not in ALPHABET:
            raise ValueError(
                "Unsupported payload "
                f"character: {character!r}"
            )

        register = (
            index % 2
        )

        cipher_index = (
            ALPHABET.index(
                character
            )
            + ALPHABET.index(
                state[
                    register
                ]
            )
        ) % 36

        cipher_character = (
            ALPHABET[
                cipher_index
            ]
        )

        encrypted.append(
            cipher_character
        )

        state[
            register
        ] = (
            cipher_character
        )

    salt_checksum = (
        ALPHABET[
            (
                ord(
                    salt_1
                )
                + ord(
                    salt_2
                )
            ) % 36
        ]
    )

    return (
        salt_1
        + salt_2
        + salt_checksum
        + "".join(
            encrypted
        )
    )


# ============================================================
# Collaborator client
# ============================================================

class CollaboratorClient:
    def __init__(
        self,
        config: Config,
        context: ClientContext,
    ) -> None:
        self.config = config
        self.context = context

        self.ssl_context = (
            ssl.create_default_context()
        )

    def generate_payload(
        self,
    ) -> tuple[
        int,
        str,
    ]:
        key_hash = (
            derive_key_hash(
                self.context.raw_biid
            )
        )

        client_part = (
            f"{self.context.counter:x}y"
        )

        plaintext = (
            f"{key_hash}"
            f"1g"
            f"{client_part}"
            f"z"
        )

        interaction_id = (
            encrypt_interaction_id(
                plaintext
            )
        )

        number = (
            self.context.counter
            + 1
        )

        self.context.counter += 1

        self.context.payloads[
            interaction_id
        ] = number

        hostname = (
            f"{interaction_id}."
            f"{self.config.domain}"
        )

        return (
            number,
            hostname,
        )

    def poll(
        self,
    ) -> list[
        dict[
            str,
            Any,
        ]
    ]:
        query = (
            urllib.parse
            .urlencode(
                {
                    "biid":
                        self.context.biid
                }
            )
        )

        url = (
            f"https://"
            f"{self.config.poll_host}"
            f"/burpresults?"
            f"{query}"
        )

        console.debug(
            f"Polling "
            f"{self.config.poll_host}"
        )

        request = (
            urllib.request.Request(
                url,
                method="GET",
                headers={
                    "Accept":
                        "application/json",

                    "User-Agent":
                        (
                            "OASTCommunity/"
                            f"{VERSION}"
                        ),

                    "Connection":
                        "close",
                },
            )
        )

        with (
            urllib.request
            .urlopen(
                request,
                timeout=(
                    self.config.timeout
                ),
                context=(
                    self.ssl_context
                ),
            )
        ) as response:

            body = (
                response
                .read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )

        if not body.strip():
            return []

        parsed = (
            json.loads(
                body
            )
        )

        if not isinstance(
            parsed,
            dict,
        ):
            raise ValueError(
                "Unexpected Collaborator response"
            )

        responses = (
            parsed.get(
                "responses",
                [],
            )
        )

        if not isinstance(
            responses,
            list,
        ):
            raise ValueError(
                "Unexpected interactions field"
            )

        interactions = [
            item
            for item
            in responses
            if isinstance(
                item,
                dict,
            )
        ]

        console.debug(
            f"Received "
            f"{len(interactions)} "
            f"raw interaction(s)"
        )

        return interactions


# ============================================================
# Configuration / state
# ============================================================

def validate_hostname(
    value: str,
    name: str,
) -> str:
    value = (
        value
        .strip()
        .rstrip(".")
        .lower()
    )

    if (
        not value
        or "://" in value
        or "/" in value
    ):
        raise ValueError(
            f"{name} must be a hostname"
        )

    for label in value.split(
        "."
    ):

        if (
            not label
            or len(label) > 63
            or label.startswith(
                "-"
            )
            or label.endswith(
                "-"
            )
            or not label.isascii()
            or not all(
                character.isalnum()
                or character == "-"
                for character in label
            )
        ):
            raise ValueError(
                f"Invalid {name}"
            )

    return value


def get_state_path(
    domain: str,
    poll_host: str,
) -> Path:
    identifier = (
        hashlib
        .sha256(
            (
                f"{domain}|"
                f"{poll_host}"
            ).encode()
        )
        .hexdigest()
        [:12]
    )

    return (
        STATE_DIR
        / f"state-{identifier}.json"
    )


def save_context(
    context: ClientContext,
    config: Config,
) -> None:
    if config.state_file is None:
        return

    config.state_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        os.chmod(
            config.state_file.parent,
            0o700,
        )

    except OSError:
        pass

    temporary = (
        config.state_file
        .with_suffix(
            ".tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            context.to_dict(
                config
            ),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    try:
        os.chmod(
            temporary,
            0o600,
        )

    except OSError:
        pass

    temporary.replace(
        config.state_file
    )

    try:
        os.chmod(
            config.state_file,
            0o600,
        )

    except OSError:
        pass


def backup_invalid_state(
    path: Path,
) -> Path | None:
    if not path.exists():
        return None

    timestamp = (
        datetime
        .now(
            timezone.utc
        )
        .strftime(
            "%Y%m%dT%H%M%SZ"
        )
    )

    backup = (
        path.with_name(
            f"{path.stem}"
            f".invalid-"
            f"{timestamp}"
            f"{path.suffix}"
        )
    )

    try:
        path.replace(
            backup
        )

        return backup

    except OSError:
        return None


def load_context(
    config: Config,
    new_context: bool = False,
) -> ClientContext:
    if config.state_file is None:

        console.debug(
            "Using ephemeral "
            "in-memory context"
        )

        return (
            ClientContext.create()
        )

    if new_context:

        context = (
            ClientContext.create()
        )

        save_context(
            context,
            config,
        )

        console.debug(
            "Created a new persistent "
            "client context"
        )

        return context

    if not config.state_file.exists():

        context = (
            ClientContext.create()
        )

        save_context(
            context,
            config,
        )

        console.debug(
            f"Created state: "
            f"{config.state_file}"
        )

        return context

    try:

        data = json.loads(
            config
            .state_file
            .read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "State root must "
                "be an object"
            )

        context = (
            ClientContext
            .from_dict(
                data,
                config,
            )
        )

        console.debug(
            f"Loaded state: "
            f"{config.state_file}"
        )

        return context

    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:

        backup = (
            backup_invalid_state(
                config.state_file
            )
        )

        if backup is not None:

            console.warn(
                "Invalid state moved to "
                f"{backup}"
            )

        else:

            console.warn(
                "Invalid state file; "
                "creating a new context"
            )

        console.debug(
            f"State error: "
            f"{error}"
        )

        context = (
            ClientContext.create()
        )

        save_context(
            context,
            config,
        )

        return context


# ============================================================
# Interaction parsing
# ============================================================

def decode_base64_text(
    value: Any,
) -> str:
    if (
        not isinstance(
            value,
            str,
        )
        or not value
    ):
        return ""

    try:

        raw = (
            base64
            .b64decode(
                value,
                validate=False,
            )
        )

        return raw.decode(
            "utf-8",
            errors="replace",
        )

    except Exception:
        return ""


def format_time(
    value: Any,
) -> str:
    try:

        date = (
            datetime
            .fromtimestamp(
                int(value) / 1000,
                tz=timezone.utc,
            )
        )

        return (
            date
            .isoformat(
                timespec="milliseconds"
            )
            .replace(
                "+00:00",
                "Z",
            )
        )

    except (
        TypeError,
        ValueError,
        OSError,
        OverflowError,
    ):

        return str(
            value
            or "unknown"
        )


def dns_type_name(
    value: Any,
) -> str:
    record_types = {
        1: "A",
        2: "NS",
        5: "CNAME",
        12: "PTR",
        15: "MX",
        16: "TXT",
        28: "AAAA",
    }

    try:

        number = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return str(
            value
            or "?"
        )

    return (
        record_types.get(
            number,
            f"TYPE{number}",
        )
    )


def interaction_source(
    interaction: dict[
        str,
        Any,
    ],
) -> str:
    host = interaction.get(
        "client",
        "unknown",
    )

    port = (
        interaction.get(
            "clientPort"
        )
    )

    if port is None:
        return str(
            host
        )

    return (
        f"{host}:"
        f"{port}"
    )


def interaction_fingerprint(
    interaction: dict[
        str,
        Any,
    ],
) -> str:
    canonical = (
        json.dumps(
            interaction,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )
        .encode(
            "utf-8"
        )
    )

    return (
        hashlib
        .sha256(
            canonical
        )
        .hexdigest()
    )


def group_interactions(
    interactions: list[
        dict[
            str,
            Any,
        ]
    ],
) -> dict[
    str,
    list[
        dict[
            str,
            Any,
        ]
    ],
]:
    grouped: dict[
        str,
        list[
            dict[
                str,
                Any,
            ]
        ],
    ] = {}

    for interaction in interactions:

        interaction_id = str(
            interaction.get(
                "interactionString",
                "unknown",
            )
        )

        grouped.setdefault(
            interaction_id,
            [],
        ).append(
            interaction
        )

    return grouped


def protocol_counts(
    interactions: list[
        dict[
            str,
            Any,
        ]
    ],
) -> dict[
    str,
    int,
]:
    counts: dict[
        str,
        int,
    ] = {}

    for interaction in interactions:

        protocol = str(
            interaction.get(
                "protocol",
                "unknown",
            )
        ).upper()

        counts[
            protocol
        ] = (
            counts.get(
                protocol,
                0,
            )
            + 1
        )

    return counts


def summary_text(
    counts: dict[
        str,
        int,
    ],
) -> str:
    preferred = [
        "DNS",
        "HTTP",
        "HTTPS",
        "SMTP",
        "SMTPS",
    ]

    parts: list[
        str
    ] = []

    for protocol in preferred:

        if protocol in counts:

            parts.append(
                f"{counts[protocol]} "
                f"{protocol}"
            )

    for protocol in sorted(
        counts
    ):

        if protocol not in preferred:

            parts.append(
                f"{counts[protocol]} "
                f"{protocol}"
            )

    return " · ".join(
        parts
    )


def payload_label(
    context: ClientContext,
    interaction_id: str,
) -> str:
    number = (
        context.payload_number(
            interaction_id
        )
    )

    if number is None:
        return "Unknown payload"

    return (
        f"Payload #{number}"
    )


def dns_details(
    interactions: list[
        dict[
            str,
            Any,
        ]
    ],
) -> tuple[
    list[str],
    list[str],
    list[str],
]:
    types: set[
        str
    ] = set()

    queries: set[
        str
    ] = set()

    resolvers: set[
        str
    ] = set()

    for item in interactions:

        data = item.get(
            "data"
        )

        if not isinstance(
            data,
            dict,
        ):
            data = {}

        types.add(
            dns_type_name(
                data.get(
                    "type"
                )
            )
        )

        query = data.get(
            "subDomain"
        )

        if (
            isinstance(
                query,
                str,
            )
            and query
        ):
            queries.add(
                query
            )

        client = item.get(
            "client"
        )

        if client is not None:

            resolvers.add(
                str(
                    client
                )
            )

    return (
        sorted(
            types
        ),
        sorted(
            queries
        ),
        sorted(
            resolvers
        ),
    )


# ============================================================
# Interaction rendering
# ============================================================

def render_payload_box(
    context: ClientContext,
    interaction_id: str,
    interactions: list[
        dict[
            str,
            Any,
        ]
    ],
) -> None:
    counts = (
        protocol_counts(
            interactions
        )
    )

    label = (
        payload_label(
            context,
            interaction_id,
        )
    )

    dns_items = [
        item
        for item
        in interactions
        if str(
            item.get(
                "protocol",
                "",
            )
        ).lower()
        == "dns"
    ]

    http_items = [
        item
        for item
        in interactions
        if str(
            item.get(
                "protocol",
                "",
            )
        ).lower()
        in {
            "http",
            "https",
        }
    ]

    other_items = [
        item
        for item
        in interactions
        if str(
            item.get(
                "protocol",
                "",
            )
        ).lower()
        not in {
            "dns",
            "http",
            "https",
        }
    ]

    width = 76

    print("")
    print(
        box_top(
            width
        )
    )

    title = (
        "  "
        + console.color(
            label,
            BOLD + GREEN,
        )
        + "  "
        + console.color(
            (
                "·  "
                + summary_text(
                    counts
                )
            ),
            DIM,
        )
    )

    print(
        box_line(
            title,
            width,
        )
    )

    print(
        box_separator(
            width
        )
    )

    if dns_items:

        (
            types,
            queries,
            resolvers,
        ) = dns_details(
            dns_items
        )

        dns_title = (
            "  "
            + console.color(
                "DNS",
                BOLD + CYAN,
            )
        )

        if types:

            dns_title += (
                "  "
                + ", ".join(
                    types
                )
            )

        print(
            box_line(
                dns_title,
                width,
            )
        )

        for query in queries:

            for line in wrap_box_text(
                (
                    "Query      "
                    + query
                ),
                width,
                indent="  ",
            ):

                print(
                    box_line(
                        line,
                        width,
                    )
                )

        if resolvers:

            resolver_text = (
                "Resolvers  "
                + ", ".join(
                    resolvers
                )
            )

            for line in wrap_box_text(
                resolver_text,
                width,
                indent="  ",
            ):

                print(
                    box_line(
                        line,
                        width,
                    )
                )

    for (
        index,
        item,
    ) in enumerate(
        http_items
    ):

        if (
            dns_items
            or index > 0
        ):

            print(
                box_line(
                    "",
                    width,
                )
            )

        protocol = str(
            item.get(
                "protocol",
                "http",
            )
        ).upper()

        print(
            box_line(
                "  "
                + console.color(
                    protocol,
                    BOLD + GREEN,
                ),
                width,
            )
        )

        print(
            box_line(
                (
                    "  Time      "
                    + format_time(
                        item.get(
                            "time"
                        )
                    )
                ),
                width,
            )
        )

        print(
            box_line(
                (
                    "  Source    "
                    + interaction_source(
                        item
                    )
                ),
                width,
            )
        )

        data = item.get(
            "data"
        )

        if not isinstance(
            data,
            dict,
        ):
            data = {}

        request = (
            decode_base64_text(
                data.get(
                    "request"
                )
            )
        )

        if request:

            print(
                box_line(
                    "",
                    width,
                )
            )

            for raw_line in (
                request
                .rstrip()
                .splitlines()
            ):

                for line in wrap_box_text(
                    raw_line,
                    width,
                    indent="    ",
                ):

                    print(
                        box_line(
                            line,
                            width,
                        )
                    )

        if console.debug_enabled:

            response = (
                decode_base64_text(
                    data.get(
                        "response"
                    )
                )
            )

            if response:

                print(
                    box_line(
                        "",
                        width,
                    )
                )

                print(
                    box_line(
                        "  "
                        + console.color(
                            "Response",
                            BOLD + DIM,
                        ),
                        width,
                    )
                )

                for raw_line in (
                    response
                    .rstrip()
                    .splitlines()
                ):

                    for line in wrap_box_text(
                        raw_line,
                        width,
                        indent="    ",
                    ):

                        print(
                            box_line(
                                line,
                                width,
                            )
                        )

    for item in other_items:

        print(
            box_line(
                "",
                width,
            )
        )

        protocol = str(
            item.get(
                "protocol",
                "unknown",
            )
        ).upper()

        print(
            box_line(
                "  "
                + console.color(
                    protocol,
                    BOLD + YELLOW,
                ),
                width,
            )
        )

        print(
            box_line(
                (
                    "  Time      "
                    + format_time(
                        item.get(
                            "time"
                        )
                    )
                ),
                width,
            )
        )

        print(
            box_line(
                (
                    "  Source    "
                    + interaction_source(
                        item
                    )
                ),
                width,
            )
        )

        data = item.get(
            "data"
        )

        if not isinstance(
            data,
            dict,
        ):
            data = {}

        decoded = ""

        for key in (
            "conversation",
            "message",
            "request",
        ):

            decoded = (
                decode_base64_text(
                    data.get(
                        key
                    )
                )
            )

            if decoded:
                break

        if decoded:

            print(
                box_line(
                    "",
                    width,
                )
            )

            for raw_line in (
                decoded
                .rstrip()
                .splitlines()
            ):

                for line in wrap_box_text(
                    raw_line,
                    width,
                    indent="    ",
                ):

                    print(
                        box_line(
                            line,
                            width,
                        )
                    )

        elif console.debug_enabled:

            print(
                box_line(
                    "",
                    width,
                )
            )

            raw_json = (
                json.dumps(
                    item,
                    sort_keys=True,
                )
            )

            for line in wrap_box_text(
                raw_json,
                width,
                indent="    ",
            ):

                print(
                    box_line(
                        line,
                        width,
                    )
                )

    print(
        box_bottom(
            width
        )
    )


def print_interaction_batch(
    context: ClientContext,
    interactions: list[
        dict[
            str,
            Any,
        ]
    ],
) -> None:
    counts = (
        protocol_counts(
            interactions
        )
    )

    detail = (
        summary_text(
            counts
        )
    )

    count = len(
        interactions
    )

    console.ok(
        f"{count} interaction"
        f"{'' if count == 1 else 's'} "
        f"received"
        + (
            f" · {detail}"
            if detail
            else ""
        )
    )

    grouped = (
        group_interactions(
            interactions
        )
    )

    for (
        interaction_id,
        items,
    ) in grouped.items():

        render_payload_box(
            context,
            interaction_id,
            items,
        )


# ============================================================
# Polling
# ============================================================

def poll_safely(
    client: CollaboratorClient,
) -> list[
    dict[
        str,
        Any,
    ]
] | None:

    try:

        return (
            client.poll()
        )

    except urllib.error.HTTPError as error:

        console.error(
            "Polling failed: "
            f"HTTP "
            f"{error.code} "
            f"{error.reason}"
        )

    except urllib.error.URLError as error:

        console.error(
            "Polling failed: "
            f"{getattr(error, 'reason', error)}"
        )

    except TimeoutError:

        console.error(
            "Polling timed out"
        )

    except (
        json.JSONDecodeError,
        ValueError,
    ) as error:

        console.error(
            "Invalid Collaborator "
            f"response: {error}"
        )

    except Exception as error:

        console.error(
            "Unexpected polling "
            f"error: {error}"
        )

        console.debug(
            repr(
                error
            )
        )

    return None


# ============================================================
# Menu
# ============================================================

def print_menu(
    context: ClientContext,
    config: Config,
) -> None:
    latest = (
        context.latest_payload(
            config
        )
    )

    title = (
        "  "
        + console.color(
            APP_NAME,
            BOLD,
        )
        + "  "
        + console.color(
            f"v{VERSION}",
            DIM,
        )
    )

    payload_count = len(
        context.payloads
    )

    payloads_line = (
        f"  Payloads  "
        f"{payload_count}"
    )

    if latest is None:

        latest_line = (
            "  Latest    "
            + console.color(
                "none",
                DIM,
            )
        )

    else:

        (
            _,
            hostname,
        ) = latest

        latest_line = (
            "  Latest    "
            + console.color(
                hostname,
                CYAN,
            )
        )

    menu_lines = [
        "  [1] New payload",
        "  [2] Poll now",
        "  [3] Listen",
        "  [0] Exit",
    ]

    candidates = [
        title,
        payloads_line,
        latest_line,
        *menu_lines,
    ]

    width = max(
        60,
        max(
            visible_len(
                line
            )
            for line
            in candidates
        )
        + 2,
    )

    print("")

    print(
        box_top(
            width
        )
    )

    print(
        box_line(
            title,
            width,
        )
    )

    print(
        box_separator(
            width
        )
    )

    print(
        box_line(
            payloads_line,
            width,
        )
    )

    print(
        box_line(
            latest_line,
            width,
        )
    )

    print(
        box_separator(
            width
        )
    )

    for line in menu_lines:

        print(
            box_line(
                line,
                width,
            )
        )

    print(
        box_bottom(
            width
        )
    )

    print("")


# ============================================================
# Menu actions
# ============================================================

def action_generate(
    client: CollaboratorClient,
) -> None:
    (
        number,
        hostname,
    ) = (
        client.generate_payload()
    )

    save_context(
        client.context,
        client.config,
    )

    print("")

    console.ok(
        f"Payload #{number} generated"
    )

    print("")

    print(
        "  "
        + console.color(
            hostname,
            BOLD + CYAN,
        )
    )

    print("")

    pause()


def action_poll(
    client: CollaboratorClient,
) -> None:
    console.info(
        "Polling for interactions"
    )

    interactions = (
        poll_safely(
            client
        )
    )

    if interactions is None:

        print("")
        pause()
        return

    if not interactions:

        console.info(
            "No new interactions"
        )

        print("")
        pause()
        return

    print_interaction_batch(
        client.context,
        interactions,
    )

    print("")

    pause()


def action_listen(
    client: CollaboratorClient,
) -> None:
    console.info(
        "Listening · "
        f"polling every "
        f"{client.config.interval:g}s"
    )

    console.info(
        "Ctrl+C to return"
    )

    seen: set[
        str
    ] = set()

    try:

        while True:

            interactions = (
                poll_safely(
                    client
                )
            )

            if interactions:

                new_interactions: list[
                    dict[
                        str,
                        Any,
                    ]
                ] = []

                for interaction in interactions:

                    fingerprint = (
                        interaction_fingerprint(
                            interaction
                        )
                    )

                    if fingerprint in seen:
                        continue

                    seen.add(
                        fingerprint
                    )

                    new_interactions.append(
                        interaction
                    )

                if new_interactions:

                    print_interaction_batch(
                        client.context,
                        new_interactions,
                    )

            time.sleep(
                client.config.interval
            )

    except KeyboardInterrupt:

        print("")

        console.info(
            "Listener stopped"
        )


# ============================================================
# CLI
# ============================================================

def parse_args(
) -> argparse.Namespace:

    parser = (
        argparse.ArgumentParser(
            description=(
                "Standalone OAST client "
                "compatible with the public "
                "Burp Collaborator infrastructure."
            )
        )
    )

    parser.add_argument(
        "--domain",
        default=DEFAULT_DOMAIN,
        help=(
            "Payload domain. "
            f"Default: {DEFAULT_DOMAIN}"
        ),
    )

    parser.add_argument(
        "--poll-host",
        default=DEFAULT_POLL_HOST,
        help=(
            "Polling host. "
            f"Default: {DEFAULT_POLL_HOST}"
        ),
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=(
            "Listener polling interval "
            "in seconds. "
            f"Default: {DEFAULT_INTERVAL:g}"
        ),
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=(
            "Network timeout "
            "in seconds. "
            f"Default: {DEFAULT_TIMEOUT:g}"
        ),
    )

    parser.add_argument(
        "--new-context",
        action="store_true",
        help=(
            "Create a fresh persistent "
            "client context before starting."
        ),
    )

    parser.add_argument(
        "--no-state",
        action="store_true",
        help=(
            "Use an ephemeral context "
            "and do not read or write state."
        ),
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        help=(
            "Disable ANSI colors."
        ),
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Enable diagnostic logging."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=(
            f"{APP_NAME} "
            f"{VERSION}"
        ),
    )

    return (
        parser.parse_args()
    )


def build_config(
    args: argparse.Namespace,
) -> Config:

    domain = (
        validate_hostname(
            args.domain,
            "domain",
        )
    )

    poll_host = (
        validate_hostname(
            args.poll_host,
            "poll host",
        )
    )

    if args.interval <= 0:

        raise ValueError(
            "--interval must "
            "be greater than 0"
        )

    if args.timeout <= 0:

        raise ValueError(
            "--timeout must "
            "be greater than 0"
        )

    state_file = (
        None
        if args.no_state
        else get_state_path(
            domain,
            poll_host,
        )
    )

    return Config(
        domain=domain,
        poll_host=poll_host,
        interval=args.interval,
        timeout=args.timeout,
        state_file=state_file,
    )


def main(
) -> int:
    global console

    args = (
        parse_args()
    )

    console = Console(
        no_color=args.no_color,
        debug_enabled=args.debug,
    )

    try:

        config = (
            build_config(
                args
            )
        )

    except ValueError as error:

        console.error(
            str(
                error
            )
        )

        return 2

    if (
        args.new_context
        and args.no_state
    ):

        console.warn(
            "--new-context has no effect "
            "with --no-state"
        )

    context = (
        load_context(
            config,
            new_context=(
                args.new_context
                and not args.no_state
            ),
        )
    )

    client = (
        CollaboratorClient(
            config,
            context,
        )
    )

    if config.state_file is not None:

        console.debug(
            f"State file: "
            f"{config.state_file}"
        )

    else:

        console.debug(
            "State persistence disabled"
        )

    console.debug(
        f"Payload domain: "
        f"{config.domain}"
    )

    console.debug(
        f"Polling host: "
        f"{config.poll_host}"
    )

    while True:

        print_menu(
            context,
            config,
        )

        try:

            option = input(
                console.color(
                    "Select",
                    BOLD,
                )
                + " > "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt,
        ):

            print("")
            return 0

        if option == "1":

            action_generate(
                client
            )

        elif option == "2":

            action_poll(
                client
            )

        elif option == "3":

            action_listen(
                client
            )

        elif option == "0":

            return 0

        else:

            console.warn(
                "Invalid option"
            )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
