# tests/fixtures/sample.py
def greet(name: str) -> str:
    return f"Hello, {name}"


class AuthService:
    def login(self, user_id: int, password: str) -> bool:
        return password == "secret"

    def logout(self, user_id: int) -> None:
        pass


def _private_helper() -> None:
    pass
