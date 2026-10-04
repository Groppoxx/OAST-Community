from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import hashlib
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
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
VERSION = "1.4.0"

ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

DEFAULT_DOMAIN = "oastify.com"
DEFAULT_POLL_HOST = "polling.oastify.com"
DEFAULT_INTERVAL = 5.0
DEFAULT_TIMEOUT = 15.0

STATE_VERSION = 2
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
        stream: Any = None,
    ) -> None:
        self.stream = stream or sys.stdout
        self.no_color = (
            no_color
            or not self.stream.isatty()
        )
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
            file=self.stream,
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

def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


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
class PayloadRecord:
    number: int
    interaction_id: str
    created: str
    note: str = ""
    label: str = ""
    prefixes: list[str] = field(
        default_factory=list
    )
    interactions: list[dict[str, Any]] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        self._fingerprints: set[str] = {
            interaction_fingerprint(item)
            for item in self.interactions
        }

    def add(
        self,
        interaction: dict[str, Any],
    ) -> bool:
        fingerprint = interaction_fingerprint(
            interaction
        )

        if fingerprint in self._fingerprints:
            return False

        self._fingerprints.add(fingerprint)
        self.interactions.append(interaction)

        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "interaction_id": self.interaction_id,
            "created": self.created,
            "note": self.note,
            "label": self.label,
            "prefixes": self.prefixes,
            "interactions": self.interactions,
        }


@dataclass
class ClientContext:
    biid: str

    counter: int = 0

    records: dict[
        str,
        PayloadRecord,
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

        record = self.records.get(
            interaction_id
        )

        if record is None or record.number <= 0:
            return None

        return record.number

    def hostname_for(
        self,
        record: PayloadRecord,
        config: Config,
    ) -> str:
        return (
            f"{record.interaction_id}."
            f"{config.domain}"
        )

    def sorted_records(
        self,
    ) -> list[PayloadRecord]:
        return sorted(
            self.records.values(),
            key=lambda record: (
                record.number
                if record.number > 0
                else 10**9
            ),
        )

    def ingest(
        self,
        interactions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        new_items: list[dict[str, Any]] = []

        for interaction in interactions:

            interaction_id = str(
                interaction.get(
                    "interactionString",
                    "unknown",
                )
            )

            record = self.records.get(
                interaction_id
            )

            if record is None:
                record = PayloadRecord(
                    number=0,
                    interaction_id=interaction_id,
                    created=now_iso(),
                    label="orphan",
                )
                self.records[interaction_id] = record

            if record.add(interaction):
                new_items.append(interaction)

        return new_items

    def latest_payload(
        self,
        config: Config,
    ) -> tuple[
        int,
        str,
    ] | None:
        generated = [
            record
            for record in self.records.values()
            if record.number > 0
        ]

        if not generated:
            return None

        record = max(
            generated,
            key=lambda item: item.number,
        )

        return (
            record.number,
            self.hostname_for(
                record,
                config,
            ),
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

            "records": {
                interaction_id: record.to_dict()
                for interaction_id, record
                in self.records.items()
            },
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
        version = data.get(
            "version"
        )

        if version not in (1, STATE_VERSION):
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

        records: dict[str, PayloadRecord] = {}

        if version == 1:
            records = cls._migrate_v1_payloads(
                data.get("payloads")
            )

        else:
            records = cls._load_records(
                data.get("records")
            )

        highest = max(
            (
                record.number
                for record in records.values()
                if record.number > 0
            ),
            default=0,
        )

        counter = max(counter, highest)

        return cls(
            biid=biid,
            counter=counter,
            records=records,
        )

    @staticmethod
    def _migrate_v1_payloads(
        payloads: Any,
    ) -> dict[str, PayloadRecord]:
        if not isinstance(
            payloads,
            dict,
        ):
            raise ValueError(
                "Invalid payload registry"
            )

        records: dict[str, PayloadRecord] = {}

        for (
            interaction_id,
            number,
        ) in payloads.items():

            if (
                isinstance(interaction_id, str)
                and interaction_id
                and isinstance(number, int)
                and number > 0
            ):
                records[interaction_id] = PayloadRecord(
                    number=number,
                    interaction_id=interaction_id,
                    created="unknown",
                )

        return records

    @staticmethod
    def _load_records(
        raw: Any,
    ) -> dict[str, PayloadRecord]:
        if not isinstance(
            raw,
            dict,
        ):
            raise ValueError(
                "Invalid payload registry"
            )

        records: dict[str, PayloadRecord] = {}

        for interaction_id, entry in raw.items():

            if (
                not isinstance(interaction_id, str)
                or not interaction_id
                or not isinstance(entry, dict)
            ):
                continue

            number = entry.get("number", 0)

            if not isinstance(number, int) or number < 0:
                number = 0

            interactions = entry.get("interactions")

            if not isinstance(interactions, list):
                interactions = []

            interactions = [
                item
                for item in interactions
                if isinstance(item, dict)
            ]

            prefixes = entry.get("prefixes")

            if not isinstance(prefixes, list):
                prefixes = []

            prefixes = [
                item
                for item in prefixes
                if isinstance(item, str) and item
            ]

            records[interaction_id] = PayloadRecord(
                number=number,
                interaction_id=interaction_id,
                created=str(
                    entry.get("created", "unknown")
                ),
                note=str(entry.get("note", "")),
                label=str(entry.get("label", "")),
                prefixes=prefixes,
                interactions=interactions,
            )

        return records


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

        self.context.records[
            interaction_id
        ] = PayloadRecord(
            number=number,
            interaction_id=interaction_id,
            created=now_iso(),
        )

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


def validate_prefix(
    value: str,
) -> str:
    value = (
        value
        .strip()
        .strip(".")
        .lower()
    )

    if not value:
        raise ValueError(
            "Prefix must not be empty"
        )

    if "://" in value or "/" in value:
        raise ValueError(
            "Prefix must be a DNS label chain"
        )

    for label in value.split("."):

        if (
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not label.isascii()
            or not all(
                character.isalnum()
                or character == "-"
                for character in label
            )
        ):
            raise ValueError(
                "Invalid prefix "
                "(use a-z, 0-9, - and .)"
            )

    return value


def build_prefixed_host(
    prefix: str,
    interaction_id: str,
    domain: str,
) -> str:
    hostname = (
        f"{prefix}."
        f"{interaction_id}."
        f"{domain}"
    )

    if len(hostname) > 253:
        raise ValueError(
            "Resulting hostname exceeds "
            "253 characters"
        )

    return hostname


def extract_prefix(
    queried: Any,
    interaction_id: str,
) -> str:
    if not isinstance(queried, str) or not queried:
        return ""

    name = queried.strip().strip(".").lower()

    marker = interaction_id.lower()

    position = name.find(marker)

    if position <= 0:
        return ""

    prefix = name[:position].rstrip(".")

    return prefix


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


def harden_permissions(
    path: Path,
    directory: bool = False,
) -> None:
    """Restrict a state path to the current user only.

    On POSIX this is chmod 0700/0600. On Windows, where chmod is
    effectively a no-op, reset ACL inheritance and grant full access
    only to the current user via icacls.
    """
    if os.name == "nt":

        try:
            user = getpass.getuser()

        except Exception:
            return

        command = [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{user}:(OI)(CI)F" if directory else f"{user}:F",
        ]

        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )

        except (OSError, subprocess.SubprocessError):
            pass

        return

    try:
        os.chmod(
            path,
            0o700 if directory else 0o600,
        )

    except OSError:
        pass


def save_context(
    context: ClientContext,
    config: Config,
) -> None:
    if config.state_file is None:
        return

    created_dir = not config.state_file.parent.exists()

    config.state_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if created_dir:
        harden_permissions(
            config.state_file.parent,
            directory=True,
        )

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

    harden_permissions(temporary)

    temporary.replace(
        config.state_file
    )

    harden_permissions(config.state_file)


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


def interaction_queried_name(
    interaction: dict[
        str,
        Any,
    ],
) -> str:
    data = interaction.get("data")

    if not isinstance(data, dict):
        data = {}

    protocol = str(
        interaction.get("protocol", "")
    ).lower()

    if protocol == "dns":
        sub = data.get("subDomain")

        return sub if isinstance(sub, str) else ""

    request = decode_base64_text(
        data.get("request")
    )

    for raw_line in request.splitlines():

        if raw_line.lower().startswith("host:"):
            return raw_line.split(":", 1)[1].strip()

    return ""


def interaction_contexts(
    interactions: list[
        dict[
            str,
            Any,
        ]
    ],
    interaction_id: str,
) -> list[str]:
    found: set[str] = set()

    for item in interactions:

        prefix = extract_prefix(
            interaction_queried_name(item),
            interaction_id,
        )

        if prefix:
            found.add(prefix)

    return sorted(found)


def smtp_conversation(
    data: dict[
        str,
        Any,
    ],
) -> str:
    for key in (
        "conversation",
        "message",
        "request",
    ):
        text = decode_base64_text(
            data.get(key)
        )

        if text:
            return text

    return ""


def parse_smtp(
    conversation: str,
) -> tuple[
    str,
    list[str],
    str,
]:
    sender = ""
    recipients: list[str] = []

    lines = conversation.splitlines()

    in_data = False
    body_lines: list[str] = []

    for raw_line in lines:

        stripped = raw_line.strip()
        lowered = stripped.lower()

        if in_data:

            if stripped == ".":
                in_data = False
                continue

            if (
                not body_lines
                and re.match(r"^\d{3}[ -]", stripped)
            ):
                # Skip the server's 354 "start mail input" reply.
                continue

            body_lines.append(raw_line)
            continue

        if lowered.startswith("mail from:"):
            sender = stripped.split(":", 1)[1].strip()

        elif lowered.startswith("rcpt to:"):
            recipient = stripped.split(":", 1)[1].strip()

            if recipient:
                recipients.append(recipient)

        elif lowered == "data":
            in_data = True

    body = "\n".join(body_lines).strip()

    return (
        sender,
        recipients,
        body,
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

    smtp_items = [
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
            "smtp",
            "smtps",
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
            "smtp",
            "smtps",
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

    contexts = interaction_contexts(
        interactions,
        interaction_id,
    )

    if contexts:

        context_text = (
            "Context    "
            + ", ".join(contexts)
        )

        for line in wrap_box_text(
            context_text,
            width,
            indent="  ",
        ):

            print(
                box_line(
                    console.color(
                        line,
                        YELLOW,
                    ),
                    width,
                )
            )

        print(
            box_line(
                "",
                width,
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

    for (
        index,
        item,
    ) in enumerate(
        smtp_items
    ):

        if (
            dns_items
            or http_items
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
                "smtp",
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

        conversation = smtp_conversation(
            data
        )

        (
            sender,
            recipients,
            body,
        ) = parse_smtp(
            conversation
        )

        if sender:
            print(
                box_line(
                    "  From      " + sender,
                    width,
                )
            )

        if recipients:
            for line in wrap_box_text(
                "To        "
                + ", ".join(recipients),
                width,
                indent="  ",
            ):
                print(
                    box_line(
                        line,
                        width,
                    )
                )

        shown = body or conversation

        if shown:

            print(
                box_line(
                    "",
                    width,
                )
            )

            for raw_line in (
                shown
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

    payload_count = sum(
        1
        for record in context.records.values()
        if record.number > 0
    )

    stored = sum(
        len(record.interactions)
        for record in context.records.values()
    )

    payloads_line = (
        f"  Payloads  "
        f"{payload_count}"
        + console.color(
            f"   Interactions  {stored}",
            DIM,
        )
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
        "  [4] Payloads",
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

    stored = client.context.ingest(
        interactions
    )

    save_context(
        client.context,
        client.config,
    )

    if not stored:

        console.info(
            "No new interactions"
        )

        print("")
        pause()
        return

    print_interaction_batch(
        client.context,
        stored,
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

    try:

        while True:

            interactions = (
                poll_safely(
                    client
                )
            )

            if interactions:

                new_interactions = (
                    client.context.ingest(
                        interactions
                    )
                )

                if new_interactions:

                    save_context(
                        client.context,
                        client.config,
                    )

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
# Payload browser
# ============================================================

_RDNS_CACHE: dict[str, str] = {}


def short_host(
    interaction_id: str,
    config: Config,
    keep: int = 10,
) -> str:
    if len(interaction_id) > keep:
        ident = interaction_id[:keep] + "…"
    else:
        ident = interaction_id

    return f"{ident}.{config.domain}"


def reverse_dns(
    ip: str,
    timeout: float,
) -> str:
    if ip in _RDNS_CACHE:
        return _RDNS_CACHE[ip]

    result = ""

    previous = socket.getdefaulttimeout()

    try:
        socket.setdefaulttimeout(timeout)
        result = socket.gethostbyaddr(ip)[0]

    except (OSError, socket.herror, socket.gaierror):
        result = ""

    finally:
        socket.setdefaulttimeout(previous)

    _RDNS_CACHE[ip] = result

    return result


def interaction_sources(
    record: PayloadRecord,
) -> list[str]:
    seen: list[str] = []

    for item in record.interactions:

        client = item.get("client")

        if not isinstance(client, str) or not client:
            continue

        if client not in seen:
            seen.append(client)

    return seen


def raw_report(
    context: ClientContext,
    record: PayloadRecord,
    config: Config,
) -> str:
    hostname = context.hostname_for(
        record,
        config,
    )

    lines: list[str] = []

    header = (
        f"Payload #{record.number}"
        if record.number > 0
        else "Orphan payload"
    )

    lines.append(f"{header}  {hostname}")
    lines.append(f"Created: {record.created}")

    if record.label:
        lines.append(f"Label: {record.label}")

    if record.note:
        lines.append(f"Note: {record.note}")

    if record.prefixes:
        lines.append(
            "Prefixes: " + ", ".join(record.prefixes)
        )

    lines.append(
        f"Interactions: {len(record.interactions)}"
    )

    lines.append("")

    for index, item in enumerate(
        record.interactions,
        start=1,
    ):

        protocol = str(
            item.get("protocol", "unknown")
        ).upper()

        lines.append(
            f"[{index}] {protocol}  "
            f"{format_time(item.get('time'))}  "
            f"{interaction_source(item)}"
        )

        data = item.get("data")

        if not isinstance(data, dict):
            data = {}

        if protocol == "DNS":
            lines.append(
                "    Type:  "
                + dns_type_name(data.get("type"))
            )

            query = data.get("subDomain")

            if isinstance(query, str) and query:
                lines.append("    Query: " + query)

        elif protocol in ("SMTP", "SMTPS"):
            conversation = smtp_conversation(data)

            if conversation:
                lines.append("    --- conversation ---")
                lines.extend(
                    "    " + line
                    for line in conversation
                    .rstrip()
                    .splitlines()
                )

        else:
            request = decode_base64_text(
                data.get("request")
            )

            response = decode_base64_text(
                data.get("response")
            )

            if request:
                lines.append("    --- request ---")
                lines.extend(
                    "    " + line
                    for line in request
                    .rstrip()
                    .splitlines()
                )

            if response:
                lines.append("    --- response ---")
                lines.extend(
                    "    " + line
                    for line in response
                    .rstrip()
                    .splitlines()
                )

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_payload_list(
    context: ClientContext,
    config: Config,
) -> None:
    records = context.sorted_records()

    width = 76

    print("")
    print(box_top(width))

    print(
        box_line(
            "  "
            + console.color(
                "Payloads",
                BOLD,
            ),
            width,
        )
    )

    print(box_separator(width))

    for record in records:

        if record.number > 0:
            tag = console.color(
                f"#{record.number}",
                BOLD + GREEN,
            )
        else:
            tag = console.color(
                "orphan",
                YELLOW,
            )

        counts = protocol_counts(
            record.interactions
        )

        summary = (
            summary_text(counts)
            or "no hits"
        )

        meta = record.label or record.note

        line = (
            "  "
            + tag
            + "  "
            + short_host(
                record.interaction_id,
                config,
            )
            + "  "
            + console.color(
                "· " + summary,
                DIM,
            )
        )

        if meta:
            line += "  " + console.color(
                "[" + meta + "]",
                CYAN,
            )

        print(
            box_line(
                line,
                width,
            )
        )

    print(box_bottom(width))
    print("")


def payload_detail(
    client: CollaboratorClient,
    record: PayloadRecord,
) -> None:
    context = client.context
    config = client.config

    while True:

        hostname = context.hostname_for(
            record,
            config,
        )

        print("")

        label = (
            f"Payload #{record.number}"
            if record.number > 0
            else "Orphan payload"
        )

        console.info(label)

        print(
            "  "
            + console.color(
                hostname,
                BOLD + CYAN,
            )
        )

        print(
            "  "
            + console.color(
                "http://" + hostname + "/",
                DIM,
            )
        )

        print(
            "  "
            + console.color(
                "https://" + hostname + "/",
                DIM,
            )
        )

        print(
            "  Created  "
            + console.color(
                record.created,
                DIM,
            )
        )

        if record.label:
            print("  Label    " + record.label)

        if record.note:
            print("  Note     " + record.note)

        if record.prefixes:
            print(
                "  Prefixes "
                + console.color(
                    ", ".join(record.prefixes),
                    YELLOW,
                )
            )

        if record.interactions:
            render_payload_box(
                context,
                record.interaction_id,
                record.interactions,
            )
        else:
            print("")
            console.info(
                "No interactions stored yet"
            )

        print("")
        print(
            console.color(
                "  [p] prefixed   "
                "[r] raw   "
                "[s] save   "
                "[d] resolve   "
                "[n] note   "
                "[l] label   "
                "[b] back",
                DIM,
            )
        )

        try:
            choice = input(
                console.color("Select", BOLD)
                + " > "
            ).strip().lower()

        except (EOFError, KeyboardInterrupt):
            print("")
            return

        if choice in ("b", "0", ""):
            return

        if choice == "p":
            build_prefixed_payload(
                client,
                record,
            )

        elif choice == "r":
            show_raw_report(
                client,
                record,
            )

        elif choice == "s":
            save_raw_report(
                client,
                record,
            )

        elif choice == "d":
            resolve_sources(
                client,
                record,
            )

        elif choice == "n":
            record.note = _prompt_text(
                "Note (blank to clear)"
            )
            save_context(context, config)
            console.ok("Note updated")

        elif choice == "l":
            record.label = _prompt_text(
                "Label (blank to clear)"
            )
            save_context(context, config)
            console.ok("Label updated")

        else:
            console.warn("Invalid option")


def build_prefixed_payload(
    client: CollaboratorClient,
    record: PayloadRecord,
) -> None:
    context = client.context
    config = client.config

    raw = _prompt_text(
        "Prefix (e.g. login-ssrf)"
    )

    if not raw:
        console.warn("Cancelled")
        return

    try:
        prefix = validate_prefix(raw)

        prefixed = build_prefixed_host(
            prefix,
            record.interaction_id,
            config.domain,
        )

    except ValueError as error:
        console.error(str(error))
        return

    if prefix not in record.prefixes:
        record.prefixes.append(prefix)
        save_context(context, config)

    print("")
    console.ok(
        "Prefixed payload (reuses this id)"
    )

    print("")

    print(
        "  "
        + console.color(
            prefixed,
            BOLD + CYAN,
        )
    )

    print(
        "  "
        + console.color(
            "http://" + prefixed + "/",
            DIM,
        )
    )

    print(
        "  "
        + console.color(
            "https://" + prefixed + "/",
            DIM,
        )
    )

    print("")

    pause()


def show_raw_report(
    client: CollaboratorClient,
    record: PayloadRecord,
) -> None:
    if not record.interactions:
        console.info("No interactions stored yet")
        print("")
        pause()
        return

    report = raw_report(
        client.context,
        record,
        client.config,
    )

    print("")
    print(report)

    pause()


def save_raw_report(
    client: CollaboratorClient,
    record: PayloadRecord,
) -> None:
    if not record.interactions:
        console.info("No interactions stored yet")
        print("")
        pause()
        return

    report = raw_report(
        client.context,
        record,
        client.config,
    )

    timestamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )

    tag = (
        f"{record.number}"
        if record.number > 0
        else record.interaction_id[:10]
    )

    filename = Path(
        f"oast-payload-{tag}-{timestamp}.txt"
    )

    try:
        filename.write_text(
            report,
            encoding="utf-8",
        )

    except OSError as error:
        console.error(
            f"Could not write report: {error}"
        )
        print("")
        pause()
        return

    console.ok(
        f"Saved report to {filename}"
    )

    print("")

    pause()


def resolve_sources(
    client: CollaboratorClient,
    record: PayloadRecord,
) -> None:
    sources = interaction_sources(record)

    if not sources:
        console.info("No source addresses stored")
        print("")
        pause()
        return

    console.info(
        f"Resolving {len(sources)} source "
        f"address{'' if len(sources) == 1 else 'es'}"
    )

    print("")

    for ip in sources:

        name = reverse_dns(
            ip,
            client.config.timeout,
        )

        print(
            "  "
            + console.color(
                ip.ljust(18),
                CYAN,
            )
            + (
                name
                if name
                else console.color(
                    "no PTR record",
                    DIM,
                )
            )
        )

    print("")

    pause()


def _prompt_text(
    prompt: str,
) -> str:
    try:
        return input(
            console.color(prompt, BOLD)
            + " > "
        ).strip()

    except (EOFError, KeyboardInterrupt):
        print("")
        return ""


def action_payloads(
    client: CollaboratorClient,
) -> None:
    context = client.context
    config = client.config

    while True:

        records = context.sorted_records()

        if not records:
            console.info("No payloads yet")
            print("")
            pause()
            return

        render_payload_list(context, config)

        try:
            choice = input(
                console.color(
                    "Payload # (b to back)",
                    BOLD,
                )
                + " > "
            ).strip().lower()

        except (EOFError, KeyboardInterrupt):
            print("")
            return

        if choice in ("b", "0", ""):
            return

        if not choice.isdigit():
            console.warn("Invalid option")
            continue

        number = int(choice)

        match = next(
            (
                record
                for record in records
                if record.number == number
            ),
            None,
        )

        if match is None:
            console.warn(
                f"No payload #{number}"
            )
            continue

        payload_detail(client, match)


# ============================================================
# Non-interactive commands
# ============================================================

def filter_by_protocol(
    interactions: list[
        dict[
            str,
            Any,
        ]
    ],
    protocols: set[str] | None,
) -> list[
    dict[
        str,
        Any,
    ]
]:
    if not protocols:
        return interactions

    return [
        item
        for item in interactions
        if str(
            item.get("protocol", "")
        ).lower()
        in protocols
    ]


def interaction_json(
    context: ClientContext,
    interaction: dict[
        str,
        Any,
    ],
) -> dict[str, Any]:
    interaction_id = str(
        interaction.get(
            "interactionString",
            "",
        )
    )

    return {
        "payload_number":
            context.payload_number(interaction_id),
        "interaction_id":
            interaction_id,
        "protocol":
            str(interaction.get("protocol", "")),
        "time":
            format_time(interaction.get("time")),
        "source":
            interaction_source(interaction),
        "queried_name":
            interaction_queried_name(interaction),
        "prefix":
            extract_prefix(
                interaction_queried_name(interaction),
                interaction_id,
            ),
        "raw":
            interaction,
    }


def cmd_new(
    client: CollaboratorClient,
    as_json: bool,
) -> int:
    number, hostname = client.generate_payload()

    save_context(
        client.context,
        client.config,
    )

    if as_json:
        print(
            json.dumps(
                {
                    "number": number,
                    "host": hostname,
                    "dns": hostname,
                    "http": f"http://{hostname}/",
                    "https": f"https://{hostname}/",
                }
            )
        )

    else:
        print(hostname)

    return 0


def cmd_poll(
    client: CollaboratorClient,
    as_json: bool,
    protocols: set[str] | None,
) -> int:
    interactions = poll_safely(client)

    if interactions is None:

        if as_json:
            print("[]")

        return 1

    stored = client.context.ingest(interactions)

    save_context(
        client.context,
        client.config,
    )

    stored = filter_by_protocol(
        stored,
        protocols,
    )

    if as_json:
        print(
            json.dumps(
                [
                    interaction_json(
                        client.context,
                        item,
                    )
                    for item in stored
                ],
                indent=2,
            )
        )

        return 0

    if not stored:
        console.info("No new interactions")
        return 0

    print_interaction_batch(
        client.context,
        stored,
    )

    return 0


def cmd_list(
    client: CollaboratorClient,
    as_json: bool,
) -> int:
    records = client.context.sorted_records()

    if as_json:

        payload = [
            {
                "number":
                    record.number
                    if record.number > 0
                    else None,
                "interaction_id":
                    record.interaction_id,
                "host":
                    client.context.hostname_for(
                        record,
                        client.config,
                    ),
                "created":
                    record.created,
                "label":
                    record.label,
                "note":
                    record.note,
                "prefixes":
                    record.prefixes,
                "protocols":
                    protocol_counts(
                        record.interactions
                    ),
                "interactions":
                    len(record.interactions),
            }
            for record in records
        ]

        print(
            json.dumps(
                payload,
                indent=2,
            )
        )

        return 0

    if not records:
        console.info("No payloads yet")
        return 0

    render_payload_list(
        client.context,
        client.config,
    )

    return 0


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
        "command",
        nargs="?",
        choices=[
            "new",
            "poll",
            "list",
        ],
        help=(
            "Optional one-shot action: "
            "new (generate a payload), "
            "poll (fetch interactions), "
            "list (show payloads). "
            "Omit for the interactive menu."
        ),
    )

    parser.add_argument(
        "--server",
        default=None,
        help=(
            "Private Collaborator server host. "
            "Sets both the payload domain and the "
            "polling host unless overridden."
        ),
    )

    parser.add_argument(
        "--domain",
        default=None,
        help=(
            "Payload domain. "
            f"Default: {DEFAULT_DOMAIN}"
        ),
    )

    parser.add_argument(
        "--poll-host",
        default=None,
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
        "--context",
        choices=[
            "persist",
            "new",
            "ephemeral",
        ],
        default="persist",
        help=(
            "Context lifecycle: persist (default, "
            "reuse saved state), new (start a fresh "
            "context), ephemeral (do not read or "
            "write any state)."
        ),
    )

    parser.add_argument(
        "--protocol",
        default=None,
        help=(
            "Comma-separated protocol filter for "
            "poll output (e.g. dns,http,smtp)."
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Machine-readable JSON output for the "
            "new, poll and list actions."
        ),
    )

    # Deprecated aliases, kept for compatibility.
    parser.add_argument(
        "--new-context",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--no-state",
        action="store_true",
        help=argparse.SUPPRESS,
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

    server = (
        validate_hostname(
            args.server,
            "server",
        )
        if args.server
        else None
    )

    domain = (
        validate_hostname(
            args.domain
            or server
            or DEFAULT_DOMAIN,
            "domain",
        )
    )

    poll_host = (
        validate_hostname(
            args.poll_host
            or server
            or DEFAULT_POLL_HOST,
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

    ephemeral = (
        args.no_state
        or args.context == "ephemeral"
    )

    state_file = (
        None
        if ephemeral
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

    for stream in (
        sys.stdout,
        sys.stderr,
    ):
        try:
            stream.reconfigure(
                encoding="utf-8",
            )

        except (AttributeError, ValueError):
            pass

    args = (
        parse_args()
    )

    as_json = args.json
    command = args.command

    if as_json and command:
        # Keep stdout clean for JSON; logs go to stderr.
        console = Console(
            no_color=True,
            debug_enabled=args.debug,
            stream=sys.stderr,
        )

    else:
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

    ephemeral = (
        args.no_state
        or args.context == "ephemeral"
    )

    new_requested = (
        args.new_context
        or args.context == "new"
    )

    if new_requested and ephemeral:

        console.warn(
            "A new context has no effect "
            "with an ephemeral context"
        )

    protocols = (
        {
            part.strip().lower()
            for part in args.protocol.split(",")
            if part.strip()
        }
        if args.protocol
        else None
    )

    context = (
        load_context(
            config,
            new_context=(
                new_requested
                and not ephemeral
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

    if command == "new":
        return cmd_new(client, as_json)

    if command == "poll":
        return cmd_poll(
            client,
            as_json,
            protocols,
        )

    if command == "list":
        return cmd_list(client, as_json)

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

        elif option == "4":

            action_payloads(
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
