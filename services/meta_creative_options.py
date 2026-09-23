"""Meta creative option enums used by template validation and payload building."""

from __future__ import annotations


# Values are Meta AdCreative.CallToActionType values.  NO_BUTTON is represented
# by omitting call_to_action from object_story_spec; it is not sent as a
# clickable button payload.
META_CTA_VALUES = frozenset({
    "NO_BUTTON",
    "LEARN_MORE",
    "GET_DETAILS",
    "SEE_MORE",
    "WATCH_MORE",
    "GET_OFFER",
    "APPLY_NOW",
    "BOOK_NOW",
    "CONTACT_US",
    "DONATE_NOW",
    "DOWNLOAD",
    "GET_QUOTE",
    "SHOP_NOW",
    "BUY_NOW",
    "SIGN_UP",
    "SUBSCRIBE",
    "MESSAGE_PAGE",
    "CHAT_NOW",
    "WHATSAPP_MESSAGE",
    "ORDER_NOW",
    "CALL_NOW",
    "EVENT_RSVP",
    "FIND_OUT_MORE",
    # Video / interactive ad CTA values exposed by Ads Manager.  Availability
    # is still decided by Meta according to objective, destination and placement.
    "PAY_TO_ACCESS",
    "REQUEST_TIME",
    "SEE_MENU",
    "SEND_UPDATES",
    "BROWSE_SHOP",
    "WATCH_VIDEO",
    "WATCH_LIVE_VIDEO",
    "JOIN_LIVE_VIDEO",
    "LISTEN_NOW",
    "GET_SHOWTIMES",
    "VISIT_WEBSITE",
    "MAKE_AN_APPOINTMENT",
})


def normalize_cta(value: object) -> str | None:
    """Normalize a CTA value while allowing an omitted CTA for legacy data."""

    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().upper()
    if normalized not in META_CTA_VALUES:
        raise ValueError(f"行动号召不受 Meta 支持: {normalized}")
    return normalized
