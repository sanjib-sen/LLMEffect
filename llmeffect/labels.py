from enum import IntEnum


class Label(IntEnum):
    TRUSTED = 0
    PUBLIC = 1
    INTERNAL = 2
    TAINTED = 3
    PII = 4
    SECRET = 5

    def join(self, other: "Label") -> "Label":
        return Label(max(int(self), int(other)))

    @classmethod
    def bottom(cls) -> "Label":
        return cls.TRUSTED

    def __str__(self) -> str:
        return self.name


WRAPPER_LABELS = {
    "Trusted": Label.TRUSTED,
    "Public": Label.PUBLIC,
    "Internal": Label.INTERNAL,
    "Tainted": Label.TAINTED,
    "PII": Label.PII,
    "Secret": Label.SECRET,
}

# Heuristic name patterns -> implicit labels. Order matters: first match wins.
NAME_HEURISTICS = [
    (("password", "passwd", "api_key", "apikey", "api_token", "private_key"), Label.SECRET),
    (("ssn", "social_security", "credit_card", "creditcard"), Label.PII),
    (("email", "phone_number", "dob", "date_of_birth"), Label.PII),
    # Function-parameter-style names suggesting user-controlled input.
    (("user_question", "user_input", "user_message", "user_prompt", "user_query"), Label.TAINTED),
]


def heuristic_label_for_name(name: str) -> Label | None:
    lower = name.lower()
    for keys, label in NAME_HEURISTICS:
        if any(k in lower for k in keys):
            return label
    return None
