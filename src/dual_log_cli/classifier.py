# INFRASTRUCTURE

# The classifier vocabulary. ROLES are the API message roles. TYPES are BLOCK types (2026-08-29
# revision): the four real content blocks plus image, and the pseudo-types a str-content message
# contributes as its single synthetic block (system, system-reminder, task-notification,
# command-message). A message is selected when its role matches and ANY of its blocks matches the
# type — matching moved from the aggregated message type to the blocks it is aggregated from.
ROLES = ("user", "assistant", "system")
TYPES = ("text", "thinking", "tool_use", "tool_result", "image",
         "system", "system-reminder", "task-notification", "command-message")

ONLY_FORMS = (f"a role ({'/'.join(ROLES)}), a type ({', '.join(TYPES)}), "
              f"or a role/type pair (e.g. user/text)")


class BadClassifierError(Exception):
    pass


# FUNCTIONS


# Parse an --only spec into a (role, type) pair, either side "" when unconstrained.
# Accepts "user", "tool_result", "user/text" — case-insensitive. Raises BadClassifierError with
# the accepted forms for anything else, rather than silently matching nothing.
def parse_only(spec: str) -> tuple:
    if not spec:
        return "", ""
    token = spec.strip().lower()
    if "/" in token:
        role, _, type_ = token.partition("/")
        if role not in ROLES or type_ not in TYPES:
            raise BadClassifierError(f"--only {spec!r} is not a known classifier — accepted: {ONLY_FORMS}")
        return role, type_
    if token in ROLES:
        return token, ""
    if token in TYPES:
        return "", token
    raise BadClassifierError(f"--only {spec!r} is not a known classifier — accepted: {ONLY_FORMS}")


# True when a message satisfies a parsed --only pair. block_types is every block type the message
# carries; the type side matches when ANY of them matches. An unconstrained side always matches.
def matches_only(role: str, block_types, wanted: tuple) -> bool:
    want_role, want_type = wanted
    if want_role and role.lower() != want_role:
        return False
    if want_type and want_type not in {str(t).lower() for t in block_types}:
        return False
    return True
