from fixtures.callee import validate_token, refresh_token


def login(user_id: int, token: str) -> bool:
    if validate_token(token):
        return True
    new_tok = refresh_token(user_id, token)
    return new_tok is not None
