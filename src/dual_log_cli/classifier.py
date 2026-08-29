# INFRASTRUCTURE

# The classifier vocabulary a turn can carry. ROLES are the API message roles; TYPES are the
# message-level types produced by proxy.message_summary._classify_content — NOT block types, so a
# turn whose type is tool_use is not selected by "thinking" even though it carries thinking blocks.
ROLES = ("user", "assistant", "system")
TYPES = ("text", "thinking", "tool_use", "tool_result",
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


# True when a turn's role/type satisfies a parsed --only pair; an unconstrained side always matches
def matches_only(role: str, type_: str, wanted: tuple) -> bool:
    want_role, want_type = wanted
    if want_role and role.lower() != want_role:
        return False
    if want_type and type_.lower() != want_type:
        return False
    return True
