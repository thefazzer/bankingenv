"""Durable, curated organisation marks for the Ficta synthetic world.

The mark is deliberately an SVG rather than a diffusion output.  Logos are
identity-bearing UI assets: a stable vector generated from the institution
UUID is easier to review, cache, and reproduce than a newly sampled bitmap.
The registry still uses the same content-addressed contract as the Cast
headshots, so a curated replacement can be installed without changing graph
identities or regenerating the world.
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import re
from pathlib import Path

from .registry import StoreRegistry

SCHEMA = "ficta.organisation-logo-registry/v4"
STYLE_REVISION = "ficta-organisation-brand-atelier-cool-wash/v7"
RELEASE_BUILD = "bankingenv-v1"
ORGANISATION_KINDS = frozenset(
    {"institution", "client", "organization", "organisation", "company"}
)

# Curated synthetic trading names. The clean-room source deliberately uses
# anonymous client codes; those codes remain aliases in the registry and must
# never become the customer-facing brand. Ordering is stable by FC number.
CLIENT_BRANDS = (
    "Alder & Rowe", "Northbridge", "Kestrel", "Solent", "Harcourt",
    "Marlin", "Redwood", "Calder", "Ashbourne", "Vesper", "Sterling Quay",
    "Cedar Vale", "Larkspur", "Ironwood", "Westmere", "Peregrine",
    "Stonehaven", "Evermont", "Bluehaven", "Crownfield", "Halcyon",
    "Foxglove", "Argent", "Oakline", "Wrenford", "Kingswell",
    "Harbourlight", "Clearwater", "Emberline", "Granite Peak", "Sable",
    "Bellwether", "Rivermark", "Juniper", "Atlas Grove", "Silvermere",
    "Norland", "Fairwind", "Beacon Ridge", "Elmstead", "Cobalt",
    "Orchard Lane", "Whitecliff", "Cairn", "Horizon Vale", "Sandpiper",
    "Longford", "Trident", "Willowmere", "Braemar", "Cardinal", "Moorland",
    "Aurora Point", "Eastgate", "Brookvale", "Cinder", "Glenhaven",
    "Summit Row", "Nightingale", "Copperleaf", "Seabrook", "Dunmere",
    "Aster", "Falconer", "Greyhaven", "Wintermere", "Vantage", "Linden",
    "Crescent Vale", "Blackthorn", "Thornfield", "Northstar", "Praxis",
    "Quarry Hill", "Rosemont",
)

SEGMENT_DESCRIPTORS = {
    "fund": ("Capital", "Partners", "Ventures", "Funds"),
    "asset-manager": ("Asset Management", "Investments", "Capital Management"),
    "corporate": ("Industries", "Group", "Holdings", "Systems"),
}


def _safe_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def _hsl_hex(hue: int, saturation: int, lightness: int) -> str:
    red, green, blue = colorsys.hls_to_rgb(
        (hue % 360) / 360.0, lightness / 100.0, saturation / 100.0
    )
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _acronym(label: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", label)
    if not words:
        return "ORG"
    if len(words) == 1:
        return (words[0][:2] or "ORG").upper()
    initials = "".join(word[0] for word in words if word[0].isalpha()).upper()
    return (initials or "ORG")[:3]


def _client_number(aliases: list[str]) -> int | None:
    for alias in aliases:
        token = re.sub(r"[^A-Za-z0-9]", "", alias).upper()
        match = re.fullmatch(r"FC(\d{1,4})", token)
        if match:
            return int(match.group(1))
    return None


def _brand_identity(label: str, aliases: list[str], kind: str, segment: str) -> tuple[str, str, str]:
    """Return customer-facing brand, initials and descriptor; never an ID code."""
    if kind == "institution":
        return "Ficta Meridian", "FM", "Bank"
    number = _client_number(aliases)
    if number is None or not 1 <= number <= len(CLIENT_BRANDS):
        # A readable fallback for future curated organisations. Numeric/code
        # tokens are stripped so an internal ID can never leak into the mark.
        words = [word for word in re.findall(r"[A-Za-z]+", label) if word.casefold() not in {"ficta", "client"}]
        brand = " ".join(words[:3]) or "Independent"
    else:
        brand = CLIENT_BRANDS[number - 1]
    descriptors = SEGMENT_DESCRIPTORS.get(segment, ("Group",))
    descriptor = descriptors[((number or 1) - 1) % len(descriptors)]
    return brand, _acronym(brand), descriptor


def _motif_name(brand: str, signature: str) -> str:
    lowered = brand.casefold()
    semantics = (
        (("bridge",), "bridge"),
        (("kestrel", "peregrine", "falconer", "nightingale", "sandpiper", "cardinal", "wren"), "wing"),
        (("redwood", "ironwood", "cedar", "juniper", "willow", "linden", "blackthorn", "thornfield", "copperleaf", "orchard"), "tree"),
        (("solent", "marlin", "bluehaven", "harbour", "clearwater", "silvermere", "seabrook", "dunmere", "wintermere", "moorland"), "wave"),
        (("ridge", "peak", "summit", "quarry", "cairn"), "mountain"),
        (("northstar", "aster", "aurora"), "star"),
        (("crown", "kingswell", "royal"), "crown"),
        (("beacon",), "beacon"),
        (("trident",), "trident"),
        (("meridian", "horizon"), "compass"),
        (("crescent",), "crescent"),
    )
    for needles, motif in semantics:
        if any(needle in lowered for needle in needles):
            return motif
    fallbacks = (
        "aperture", "saltire", "ribbon", "rosette", "keys", "columns",
        "arch", "chevron", "prism", "links", "orbit", "monolith",
        "lattice", "sails", "shield", "flame", "vault", "bars", "knot",
        "leaf", "horse", "flower", "arrowhead", "diamond", "gate", "weave",
    )
    return fallbacks[int(signature[8:12], 16) % len(fallbacks)]


def _motif_svg(name: str, primary: str, accent: str) -> str:
    line = f'fill="none" stroke="{primary}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"'
    motifs = {
        "aperture": f'<path d="M17 18h48L50 35H34v16L17 67Zm102 0v48l-17-15V35H86l-15-17Zm0 94H71l15-17h16V79l17-15ZM17 112V64l17 15v16h16l15 17Z" fill="{primary}"/><path d="m68 45 23 23-23 23-23-23Z" fill="{accent}"/>',
        "saltire": f'<path d="m68 12 23 30-23 22-23-22Zm0 112-23-30 23-22 23 22ZM12 68l30-23 22 23-22 23Zm112 0L94 91 72 68l22-23Z" fill="{primary}"/><circle cx="68" cy="68" r="12" fill="{accent}"/>',
        "bridge": f'<path d="M15 99h106v16H15Zm11-8V72Q68 23 110 72v19H94V75Q68 47 42 75v16Z" fill="{primary}"/><path d="M49 78h11v27H49Zm27 0h11v27H76Z" fill="{accent}"/>',
        "wing": f'<path d="M10 70q30-47 58-16 28-31 58 16-31-13-58 39Q41 57 10 70Z" fill="{primary}"/><path d="m68 54 11 13-11 31-11-31Z" fill="{accent}"/>',
        "tree": f'<path d="M68 12 39 50h14L26 84h31v30h22V84h31L83 50h14Z" fill="{primary}"/><path d="M68 30v63M49 68l19 17 20-17" stroke="{accent}" stroke-width="8" stroke-linecap="round"/>',
        "wave": f'<path d="M11 56q26-34 52 0t52 0v25q-26 34-52 0t-52 0Z" fill="{primary}"/><path d="M13 93q25-27 50 0t50 0" fill="none" stroke="{accent}" stroke-width="11" stroke-linecap="round"/>',
        "mountain": f'<path d="m10 109 40-66 15 22 21-38 40 82Z" fill="{primary}"/><path d="m43 88 22-23 14 19 13-13 19 38H22Z" fill="{accent}"/>',
        "star": f'<path d="m68 8 15 39 42 3-32 27 10 42-35-23-35 23 10-42-32-27 42-3Z" fill="{primary}"/><circle cx="68" cy="67" r="15" fill="{accent}"/>',
        "crown": f'<path d="m12 35 29 27 27-42 27 42 29-27-14 76H26Z" fill="{primary}"/><path d="M29 86h78v12H29Z" fill="{accent}"/>',
        "beacon": f'<path d="M47 112h42L78 45H58Z" fill="{primary}"/><path d="M22 38h92M12 17l38 14m74-14L86 31M12 60l38-10m74 10L86 50" stroke="{accent}" stroke-width="9" stroke-linecap="round"/>',
        "trident": f'<path d="M57 117V51L34 32v31H19V13l38 29V13h22v29l38-29v50h-15V32L79 51v66Z" fill="{primary}"/><path d="M30 94h76v14H30Z" fill="{accent}"/>',
        "compass": f'<circle cx="68" cy="68" r="57" fill="{primary}"/><path d="m68 18 15 50-15 50-15-50Z" fill="{accent}"/><path d="m18 68 50-15 50 15-50 15Z" fill="none" stroke="white" stroke-opacity=".72" stroke-width="8"/>',
        "crescent": f'<path d="M92 10a57 57 0 1 0 0 116A47 47 0 0 1 92 10Z" fill="{primary}"/><circle cx="91" cy="44" r="9" fill="{accent}"/>',
        "arch": f'<path d="M18 116V65a50 50 0 0 1 100 0v51H92V68a24 24 0 0 0-48 0v48Z" fill="{primary}"/><path d="M57 69a11 11 0 0 1 22 0v47H57Z" fill="{accent}"/>',
        "columns": f'<path d="m9 39 59-29 59 29v14H9Zm9 65h100v17H18Zm11-44h15v38H29Zm32 0h15v38H61Zm32 0h15v38H93Z" fill="{primary}"/><path d="M20 45h96v9H20Z" fill="{accent}"/>',
        "diamond": f'<path d="M68 8 128 68 68 128 8 68Z" fill="{primary}"/><path d="m68 31 37 37-37 37-37-37Z" fill="{accent}"/><path d="m68 50 18 18-18 18-18-18Z" fill="white" fill-opacity=".9"/>',
        "orbit": f'<ellipse cx="68" cy="68" rx="55" ry="24" {line}/><ellipse cx="68" cy="68" rx="24" ry="55" {line}/><circle cx="68" cy="68" r="14" fill="{accent}"/>',
        "weave": f'<path d="M15 23h106v24H15Zm0 66h106v24H15Z" fill="{primary}"/><path d="M25 13h24v110H25Zm62 0h24v110H87Z" fill="{accent}"/><path d="M49 47h38v42H49Z" fill="white" fill-opacity=".88"/>',
        "chevron": f'<path d="m9 31 59 47 59-47v28L68 106 9 59Z" fill="{primary}"/><path d="m25 74 43 34 43-34v26l-43 34-43-34Z" fill="{accent}"/>',
        "monolith": f'<path d="M39 10h58l18 116H21Z" fill="{primary}"/><path d="m68 27 17 83H51Z" fill="{accent}"/>',
        "ribbon": f'<path d="m12 30 39-18 31 43-14 21Z" fill="{primary}"/><path d="m51 12 40 4 31 43-40-4Z" fill="{accent}"/><path d="m68 76 14-21 40 4-39 65H43Z" fill="{primary}"/>',
        "rosette": f'<path d="M68 7c14 16 20 31 15 45 14-5 29 1 45 16-16 14-31 20-45 15 5 14-1 29-15 45-15-16-21-31-16-45-14 5-29-1-45-15 16-15 31-21 45-16-5-14 1-29 16-45Z" fill="{primary}"/><circle cx="68" cy="68" r="22" fill="{accent}"/>',
        "keys": f'<circle cx="38" cy="38" r="20" {line}/><circle cx="98" cy="38" r="20" {line}/><path d="m52 52 66 66m-6-6v-20m0 20H92M84 52l-66 66m6-6V92m0 20h20" {line}/><circle cx="68" cy="68" r="10" fill="{accent}"/>',
        "gate": f'<path d="M13 119V31h110v88H93V59H43v60Z" fill="{primary}"/><path d="M56 72h24v47H56ZM13 31h110v14H13Z" fill="{accent}"/>',
        "prism": f'<path d="M68 7 130 121H6Z" fill="{primary}"/><path d="m68 38 38 70H68Z" fill="{accent}"/><path d="M68 38v70H30Z" fill="white" fill-opacity=".72"/>',
        "links": f'<circle cx="48" cy="68" r="36" {line}/><circle cx="88" cy="68" r="36" {line}/><path d="M62 42a36 36 0 0 1 0 52M74 42a36 36 0 0 0 0 52" stroke="{accent}" stroke-width="9" fill="none"/>',
        "lattice": f'<path d="m68 6 22 22-22 22-22-22Zm0 80 22 22-22 22-22-22ZM6 68l22-22 22 22-22 22Zm80 0 22-22 22 22-22 22Z" fill="{primary}"/><path d="m68 43 25 25-25 25-25-25Z" fill="{accent}"/>',
        "sails": f'<path d="M63 13 21 91h42Zm10 14 40 64H73Z" fill="{primary}"/><path d="M13 103q28-16 55 0t55 0v16H13Z" fill="{accent}"/>',
        "shield": f'<path d="M13 13h110v65q0 34-55 54Q13 112 13 78Z" fill="{primary}"/><path d="M13 73 103 13h20v27l-98 66q-12-15-12-33Z" fill="{accent}"/>',
        "flame": f'<path d="M71 5q7 31-11 43 3-23-16-33 2 27-19 47-21 42 43 68 64-25 42-72-8 30-28 36 17-39-11-89Z" fill="{primary}"/><path d="M68 59q30 35 0 59-30-20 0-59Z" fill="{accent}"/>',
        "vault": f'<path d="M8 68a60 60 0 0 1 120 0v56H98V72a30 30 0 0 0-60 0v52H8Z" fill="{primary}"/><circle cx="68" cy="72" r="17" fill="{accent}"/>',
        "bars": f'<path d="M13 78h25v45H13Zm42-31h26v76H55Zm43-34h25v110H98Z" fill="{primary}"/><path d="M8 108 51 65l18 18 57-57v29L69 112 51 94l-43 43Z" fill="{accent}"/>',
        "knot": f'<path d="M21 32h49q35 0 35 31T70 94H21M115 32H66Q31 32 31 63t35 31h49" {line}/><path d="M60 51h16v34H60Z" fill="{accent}"/>',
        "leaf": f'<path d="M119 13Q35 9 17 78q31 57 82 18 28-23 20-83Z" fill="{primary}"/><path d="M30 105Q60 65 108 29M61 67l-1 39M73 55l35 3" stroke="{accent}" stroke-width="9" fill="none" stroke-linecap="round"/>',
        "horse": f'<path d="M29 121q-5-46 22-62L44 17l31 18 18-21 10 39q25 17 18 48l-28-12-14 32Z" fill="{primary}"/><path d="m50 59 27-24 16 18-14 25Z" fill="{accent}"/><circle cx="94" cy="63" r="6" fill="white"/>',
        "flower": f'<circle cx="68" cy="35" r="27" fill="{primary}"/><circle cx="101" cy="68" r="27" fill="{accent}"/><circle cx="68" cy="101" r="27" fill="{primary}"/><circle cx="35" cy="68" r="27" fill="{accent}"/><circle cx="68" cy="68" r="22" fill="white" fill-opacity=".9"/>',
        "arrowhead": f'<path d="M68 7 127 67 86 62l24 59-42-34-42 34 24-59-41 5Z" fill="{primary}"/><path d="m68 29 13 41-13 17-13-17Z" fill="{accent}"/>',
    }
    return motifs[name]


def _brand_field_svg(variant: int, primary: str, accent: str, paper: str) -> tuple[str, str, str, str]:
    """Return a reference-set-like field, mark colours and central transform."""
    white = "#ffffff"
    fields = (
        (f'<rect width="192" height="192" fill="{paper}"/>', primary, accent, "translate(28 28)"),
        (f'<rect width="192" height="192" fill="{primary}"/><path d="M0 154 192 91v101H0Z" fill="{accent}"/>', white, paper, "translate(28 28)"),
        (f'<rect width="192" height="192" fill="{paper}"/><circle cx="96" cy="96" r="82" fill="{primary}"/>', white, accent, "translate(28 28)"),
        (f'<rect width="192" height="192" fill="{paper}"/><path d="M19 18h154v91q0 48-77 70-77-22-77-70Z" fill="{primary}"/>', white, accent, "translate(32 28) scale(.94)"),
        (f'<rect width="192" height="192" fill="{primary}"/><path d="M0 0h192L0 192Z" fill="{accent}"/>', white, paper, "translate(28 28)"),
        (f'<rect width="192" height="192" fill="{paper}"/><path d="m96 8 84 48v80l-84 48-84-48V56Z" fill="{primary}"/>', white, accent, "translate(32 32) scale(.94)"),
        (f'<rect width="192" height="192" fill="{paper}"/><path d="M18 31h156v130H18Z" fill="{primary}"/><path d="M18 31h156v19H18Z" fill="{accent}"/>', white, accent, "translate(31 37) scale(.96)"),
        (f'<rect width="192" height="192" fill="{paper}"/><path d="m96 9 87 87-87 87L9 96Z" fill="{primary}"/>', white, accent, "translate(38 38) scale(.85)"),
        (f'<rect width="192" height="192" fill="{primary}"/><circle cx="192" cy="0" r="126" fill="{accent}"/>', white, paper, "translate(28 28)"),
        (f'<rect width="192" height="192" fill="{paper}"/><path d="M20 177V86a76 76 0 0 1 152 0v91Z" fill="{primary}"/>', white, accent, "translate(35 43) scale(.9)"),
    )
    return fields[variant % len(fields)]


def _emblem_svg(
    variant: int,
    initials: str,
    motif: str,
    primary: str,
    accent: str,
    *,
    include_initials: bool = True,
) -> str:
    escaped = _escape(initials)
    frames = (
        "",
        f'<circle cx="68" cy="64" r="55" fill="none" stroke="{primary}" stroke-width="6"/>',
        f'<rect x="14" y="10" width="108" height="108" rx="7" fill="none" stroke="{primary}" stroke-width="6"/>',
        f'<path d="M68 8 122 64 68 120 14 64Z" fill="none" stroke="{primary}" stroke-width="6"/>',
        f'<path d="M19 10h98v64q0 29-49 47Q19 103 19 74Z" fill="none" stroke="{primary}" stroke-width="6"/>',
        f'<path d="M18 20h100M18 108h100" stroke="{primary}" stroke-width="7"/>',
    )
    families = (
        "Arial,Helvetica,sans-serif", "Georgia,serif", "Verdana,sans-serif",
        "'Times New Roman',serif", "'Trebuchet MS',sans-serif", "Garamond,serif",
    )
    if not include_initials:
        return (
            f'<g transform="translate(24 28) scale(1.06)">'
            f'{frames[variant % len(frames)]}{motif}</g>'
        )
    return (
        f'<g transform="translate(12 2) scale(.82)">{frames[variant % len(frames)]}{motif}</g>'
        f'<text x="68" y="130" text-anchor="middle" fill="{primary}" font-family="{families[variant % len(families)]}" font-size="18" font-weight="800" letter-spacing="1.5">{escaped}</text>'
    )


def load_institutions(world_path: Path) -> list[dict]:
    world = json.loads(world_path.read_text(encoding="utf-8"))
    entities = world.get("entities", world if isinstance(world, list) else [])
    rows: list[dict] = []
    for entity in entities:
        if not isinstance(entity, dict) or not entity.get("synthetic"):
            continue
        kind = _safe_text(entity.get("kind")).casefold()
        if kind not in ORGANISATION_KINDS:
            continue
        attrs = entity.get("attributes") if isinstance(entity.get("attributes"), dict) else {}
        entity_id = _safe_text(entity.get("entity_id") or entity.get("id"))
        label = _safe_text(entity.get("canonical_label") or entity.get("label"))
        if not entity_id or not label:
            raise ValueError("synthetic organisation is missing entity_id or canonical_label")
        aliases = [str(v) for v in entity.get("aliases", []) if str(v).strip()]
        segment = _safe_text(attrs.get("client_segment"))
        brand_name, initials, descriptor = _brand_identity(label, aliases, kind, segment)
        rows.append({
            "institution_id": entity_id,
            "canonical_label": label,
            "aliases": aliases,
            "entity_kind": kind,
            "jurisdiction": _safe_text(attrs.get("jurisdiction")),
            "operating_model": _safe_text(attrs.get("operating_model")),
            "client_segment": segment,
            "risk_tier": attrs.get("risk_tier"),
            "brand_name": brand_name,
            "initials": initials,
            "descriptor": descriptor,
            "style_revision": STYLE_REVISION,
            "signature": hashlib.sha256(
                f"{entity_id}|{label}|{brand_name}|{descriptor}|{STYLE_REVISION}".encode()
            ).hexdigest(),
        })
    rows.sort(key=lambda row: row["institution_id"])
    brands = [row["brand_name"].casefold() for row in rows]
    if len(brands) != len(set(brands)):
        raise ValueError("organisation brand names are not unique")
    return rows


def load_cast_graph_organisations(graph_path: Path) -> list[dict]:
    """Load every cast-plane organisation as a stable logo identity."""
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    seen: set[str] = set()
    for node in graph.get("nodes") or []:
        kind = _safe_text(node.get("kind") or node.get("group")).casefold()
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        if kind not in ORGANISATION_KINDS or str(properties.get("plane") or "record") != "cast":
            continue
        entity_id = _safe_text(node.get("id"))
        label = _safe_text(node.get("label") or properties.get("canonical_name"))
        if not entity_id or not label or entity_id in seen:
            raise ValueError("cast organisation requires a unique ID and label")
        seen.add(entity_id)
        aliases = sorted(set(map(str, [*(node.get("aliases") or []), *(properties.get("aliases") or [])])))
        signature = hashlib.sha256(
            f"{entity_id}|{label}|{STYLE_REVISION}".encode()
        ).hexdigest()
        rows.append({
            "institution_id": entity_id,
            "canonical_label": label,
            "aliases": aliases,
            "entity_kind": kind,
            "jurisdiction": _safe_text(properties.get("jurisdiction")),
            "operating_model": _safe_text(properties.get("operating_model")),
            "client_segment": _safe_text(properties.get("client_segment")),
            "risk_tier": properties.get("risk_tier"),
            "brand_name": label,
            "initials": _acronym(label),
            "descriptor": "",
            "style_revision": STYLE_REVISION,
            "signature": signature,
        })
    rows.sort(key=lambda row: row["institution_id"])
    return rows


def bind_cast_graph_logos(graph: dict, rows: list[dict]) -> int:
    """Attach generated logo keys to exactly the cast organisations in ``rows``."""
    keys = {row["institution_id"] for row in rows}
    applied = 0
    for node in graph.get("nodes") or []:
        if str(node.get("id") or "") not in keys:
            continue
        properties = node.setdefault("properties", {})
        properties.update({
            "logo_url": f"/synthetic/logos/{node['id']}",
            "logo_asset_id": str(node["id"]),
            "logo_source": STYLE_REVISION,
            "logo_status": "generated_unique",
        })
        applied += 1
    if applied != len(keys):
        raise ValueError("not every generated organisation logo was bound to the graph")
    return applied


def render_logo(row: dict) -> str:
    """Render a square corporate mark with brand-specific visual grammar."""
    label = _escape(row["canonical_label"])
    brand = _escape(row["brand_name"])
    initials = _escape(row["initials"])
    descriptor = _escape(row["descriptor"])
    signature = row["signature"]
    # Use the same cool steel wash as Cast employee profiles.  The narrow
    # tonal family makes people and organisations read as one identity system,
    # while field construction and motif still carry organisation identity.
    palettes = (
        ("#1d2d3d", "#749dc4", "#f2f2f3"),
        ("#2c455d", "#94bce3", "#eef2f6"),
        ("#416180", "#b5d9fd", "#f2f2f3"),
        ("#24364a", "#839eb8", "#ebedf0"),
        ("#344f67", "#6f8faa", "#f3f4f5"),
        ("#273c50", "#9badbf", "#e7e9ed"),
        ("#1d2d3d", "#5980a6", "#eef6ff"),
        ("#2c455d", "#749dc4", "#e9edf1"),
        ("#416180", "#94bce3", "#f2f2f3"),
        ("#263b4f", "#879fb5", "#edf0f3"),
        ("#334b61", "#6f8dab", "#f4f4f5"),
        ("#203345", "#a8b8c7", "#e8eaee"),
    )
    primary, accent, paper = palettes[int(signature[:6], 16) % len(palettes)]
    field, ink, highlight, transform = _brand_field_svg(
        int(signature[6:10], 16), primary, accent, paper
    )
    motif_name = _motif_name(row["brand_name"], signature)
    motif = _motif_svg(motif_name, ink, highlight)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="192" height="192" viewBox="0 0 192 192" role="img" aria-labelledby="title desc">
  <title id="title">{brand} {descriptor}</title><desc id="desc">Synthetic organisation brand for {label}</desc>
  <metadata data-style="{STYLE_REVISION}" data-family="{motif_name}" data-signature="{signature[:16]}"/>
  {field}
  <g transform="{transform}">{motif}</g>
</svg>\n'''


def generate(rows: list[dict], output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    signatures = {}
    for row in rows:
        path = output / f"{row['institution_id']}.svg"
        path.write_text(render_logo(row), encoding="utf-8")
        signatures[row["institution_id"]] = row["signature"]
    (output / ".logo-signatures.json").write_text(json.dumps(signatures, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"schema": SCHEMA, "style_revision": STYLE_REVISION, "organisations": len(rows)}


def publish(rows: list[dict], images: Path, registry: StoreRegistry) -> dict:
    """Publish generated marks through the canonical StoreRegistry asset contract."""

    signatures = json.loads(
        (images / ".logo-signatures.json").read_text(encoding="utf-8")
    )
    bindings: dict[str, dict] = {}
    for row in rows:
        key = row["institution_id"]
        path = images / f"{key}.svg"
        if not path.is_file() or signatures.get(key) != row["signature"]:
            raise ValueError(f"missing or stale logo for {key}")
        body = path.read_bytes()
        asset_id = registry.bind_institution_logo(
            key,
            body,
            aliases=tuple(row["aliases"]),
            provider="cleanroom:cast_logos",
            provider_revision=STYLE_REVISION,
            attributes={
                "canonical_label": row["canonical_label"],
                "entity_kind": row["entity_kind"],
                "brand_name": row["brand_name"],
                "signature": row["signature"],
            },
        )
        digest = asset_id.removeprefix("sha256:")
        bindings[key] = {
            "institution_id": key,
            "entity_kind": row["entity_kind"],
            "canonical_label": row["canonical_label"],
            "aliases": row["aliases"],
            "brand_name": row["brand_name"],
            "initials": row["initials"],
            "descriptor": row["descriptor"],
            "style_revision": STYLE_REVISION,
            "asset_id": asset_id,
            "sha256": digest,
        }
    registry.verify()
    return {
        "schema": SCHEMA,
        "release_build": RELEASE_BUILD,
        "style_revision": STYLE_REVISION,
        "organisations": len(bindings),
        "institutions": sum(
            1 for row in bindings.values() if row["entity_kind"] == "institution"
        ),
        "clients": sum(
            1 for row in bindings.values() if row["entity_kind"] == "client"
        ),
        "bindings": bindings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()
    rows = load_institutions(args.world)
    generate(rows, args.output)
    if args.store:
        publish(rows, args.output, StoreRegistry(args.store))
    print(json.dumps({"organisations": len(rows), "output": str(args.output), "store": str(args.store) if args.store else None}))


if __name__ == "__main__":
    main()
