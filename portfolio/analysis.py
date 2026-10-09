"""The Claude steps: research the project online, judge each photo, write the post."""

from __future__ import annotations

from .llm import Claude, ResearchResult, image_block

# ---------------------------------------------------------------- research

RESEARCH_SYSTEM = (
    "You research commercial building projects for Unite Ideas, an architecture and design firm, "
    "so it can publish an accurate portfolio post about one specific building. "
    "Report only what sources say, and give the source URL for every fact."
)

RESEARCH_PROMPT = """Research this specific location:

Business: {business}
City: {city}
{place_line}

Find, for THIS location only (other locations of the same brand matter only as brief brand context):
- address, current status (planned, under construction, open) and opening or ribbon-cutting date
- developer, property owner or landlord, general contractor or builder, architect or designer, engineers
- city or county involvement: planning and zoning cases, council approvals, permits, economic development
- building facts: size in square feet, new build or renovation of an existing building, notable design features
- web pages that show PHOTOS of this building: exterior, interior, construction progress or grand opening

Good places to look: local newspapers, city and county websites and meeting agendas, chamber of commerce,
regional lifestyle and business magazines, developer and builder project pages, commercial real estate listings.
Skip Facebook, Instagram and other social media.

Finish with a plain list of the facts you found, each followed by its source URL, then a list of the pages
that show photos of the building."""

RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "address": {"type": "string"},
        "status": {"type": "string"},
        "opened": {"type": "string", "description": "Opening or ribbon-cutting date, or empty"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}, "source_url": {"type": "string"}},
                "required": ["fact", "source_url"],
                "additionalProperties": False,
            },
        },
        "organizations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "role": {"type": "string"}},
                "required": ["name", "role"],
                "additionalProperties": False,
            },
        },
        "photo_pages": {"type": "array", "items": {"type": "string"}},
        "uncertain": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["address", "status", "opened", "facts", "organizations", "photo_pages", "uncertain"],
    "additionalProperties": False,
}


def research_project(
    claude: Claude, business: str, city: str, place_address: str = "", notes: str = ""
) -> tuple[dict, ResearchResult]:
    place_line = f"Google listing address: {place_address}" if place_address else ""
    if notes:
        place_line += f"\nBackground from the firm (accurate; use it to guide the search, including other names):\n{notes}"
    raw = claude.research(
        RESEARCH_PROMPT.format(business=business, city=city, place_line=place_line),
        system=RESEARCH_SYSTEM,
    )
    sources = "\n".join(f"- {s['title']} {s['url']}" for s in raw.sources)
    structured = claude.json(
        f"Research notes:\n\n{raw.text}\n\nPages seen while searching:\n{sources}\n\n"
        f"Turn these notes about {business} in {city} into the requested fields. "
        "Leave a field empty rather than guessing. photo_pages must be URLs from the notes or the page list.",
        schema=RESEARCH_SCHEMA,
        system="You convert research notes into structured data without adding information.",
    )
    return structured, raw


# ---------------------------------------------------------------- photos

PHOTO_KINDS = [
    "exterior",
    "interior",
    "construction",
    "rendering",
    "food_or_product",
    "marketing_graphic",
    "sign_or_logo_closeup",
    "people_focus",
    "map_or_screenshot",
    "other",
]
BUILDING_KINDS = {"exterior", "interior", "construction"}

PHOTO_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": PHOTO_KINDS},
        "shows_building": {"type": "boolean"},
        "people": {"type": "string", "enum": ["none", "few", "many"]},
        "matches_business": {"type": "string", "enum": ["yes", "unsure", "no"]},
        "quality": {"type": "integer", "description": "1 (poor) to 5 (portfolio ready)"},
        "description": {"type": "string"},
        "alt_text": {"type": "string"},
    },
    "required": ["kind", "shows_building", "people", "matches_business", "quality", "description", "alt_text"],
    "additionalProperties": False,
}

PHOTO_SYSTEM = (
    "You sort photos for an architecture firm's portfolio. The firm only wants real photos of the building "
    "itself: exterior, interior spaces, or construction progress. Food, products, menus, staff portraits, "
    "marketing graphics and close-ups of logos are not wanted."
)


def classify_photo(claude: Claude, jpeg: bytes, business: str, city: str, context: str) -> dict:
    prompt = (
        f"Business: {business}, {city}.\nWhere this image was found: {context}\n\n"
        "Classify the image.\n"
        "- kind: the main subject. Use 'rendering' for 3D renders or drawings, not photos.\n"
        "- shows_building: true only if the building's architecture or interior space is the clear subject.\n"
        "- people: how many people are visible.\n"
        f"- matches_business: could this be the {business} building in {city}? Say 'no' for a different "
        "brand or an obviously different building, 'unsure' if you cannot tell.\n"
        "- quality: 1 to 5 for use in a professional portfolio (sharpness, light, framing, no watermark).\n"
        "- description: one short sentence.\n"
        f"- alt_text: under 15 words, e.g. 'Exterior of {business} in {city} at dusk'. No em dashes."
    )
    result = claude.json([image_block(jpeg), {"type": "text", "text": prompt}], schema=PHOTO_SCHEMA, system=PHOTO_SYSTEM)
    result["quality"] = max(1, min(5, int(result.get("quality", 1))))
    return result


def photo_score(review: dict, allow_renders: bool = False) -> float:
    """Higher is better. Zero means 'not a building photo'. Renders only count when they
    come from a folder picked by hand."""
    kinds = BUILDING_KINDS | ({"rendering"} if allow_renders else set())
    if not review or review.get("kind") not in kinds or not review.get("shows_building"):
        return 0.0
    if review.get("matches_business") == "no":
        return 0.0
    score = review["quality"] * 2.0
    score += {"none": 2, "few": 1, "many": 0}.get(review.get("people", "many"), 0)
    score += 1 if review.get("matches_business") == "yes" else 0
    score += 0.5 if review.get("kind") == "exterior" else 0
    return score


# ---------------------------------------------------------------- write-up

WRITEUP_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "project_name": {"type": "string"},
        "location": {"type": "string"},
        "year": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}},
        "excerpt": {"type": "string"},
        "building_type": {"type": "string", "enum": ["ministry", "food_service", "hospitality", "commercial"]},
        "review_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "project_name", "location", "year", "paragraphs", "excerpt", "building_type", "review_notes"],
    "additionalProperties": False,
}

WRITEUP_SYSTEM = """You write portfolio entries for Unite Ideas (uniteideas.com), an architecture and design firm.

Style:
- Plain, confident and specific. Short sentences. No hype words such as "stunning", "state of the art" or "nestled".
- Never use em dashes.
- Usually one or two short paragraphs. If little is known, one or two sentences is fine.
- Describe the project: what was built or renovated, where, for which brand, and what makes it notable.
- Mention the firm's role only when the project documents show what it was (for example architecture,
  design, or visualization). Call the firm "we" or "Unite", never "Unite Ideas".
- Credit developers, builders and city partners by name when sources support it.
- Never name the owners, franchisees or operators, or the companies they own the business through.
  Refer to them as "the owners" or "the franchisee" if needed.
- Use only facts from the material provided. Never include prices, fees, budgets, contract terms,
  or anyone's phone number or email address."""

WRITEUP_PROMPT = """Write the portfolio entry for {business} in {city}.

Fields:
- title: the business name, a hyphen and the city, like "{business} - {city_name}".
- project_name: for a restaurant, the brand followed by "QSR" (e.g. "Pancheros QSR"); otherwise a short project name.
- location: "City, ST".
- year: {year_hint}
- paragraphs: the write-up.
- excerpt: one sentence summary for search results, under 160 characters.
- building_type: the portfolio category. "ministry" for churches, ministries, camps, Christian schools and other
  nonprofits; "food_service" for restaurants, QSR, bakeries and other food service that is not a ministry;
  "hospitality" for hotels and lodging; "commercial" for everything else.
- review_notes: anything uncertain or contradictory the owner should check before publishing.

NOTES FROM THE FIRM (accurate; follow any naming or wording instructions in them):
{notes}

PROJECT DOCUMENTS FROM DROPBOX:
{documents}

WEB RESEARCH:
{research}"""


def write_post(
    claude: Claude,
    business: str,
    city: str,
    year_hint: str,
    documents: list[tuple[str, str]],
    research: dict,
    notes: str = "",
) -> dict:
    docs_text = "\n\n".join(f"--- {name} ---\n{text}" for name, text in documents) or "(none found)"
    facts = "\n".join(f"- {f['fact']} ({f['source_url']})" for f in research.get("facts", []))
    orgs = "\n".join(f"- {o['name']}: {o['role']}" for o in research.get("organizations", []))
    research_text = (
        f"Address: {research.get('address', '')}\nStatus: {research.get('status', '')}\n"
        f"Opened: {research.get('opened', '')}\nFacts:\n{facts}\nOrganizations:\n{orgs}"
    )
    city_name = city.split(",")[0].strip()
    return claude.json(
        WRITEUP_PROMPT.format(
            business=business,
            city=city,
            city_name=city_name,
            year_hint=f"use {year_hint}" if year_hint else "the year the project was done, from the documents",
            notes=notes or "(none)",
            documents=docs_text,
            research=research_text,
        ),
        schema=WRITEUP_SCHEMA,
        system=WRITEUP_SYSTEM,
        effort="medium",
    )
