def validate_token(token: str) -> bool:
    return len(token) == 32


def refresh_token(user_id: int, token: str) -> str:
    return "new_token_" + str(user_id)
