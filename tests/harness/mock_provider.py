class MockProvider:
    name = "mock"

    def __init__(self):
        self.calls = []

    def health(self):
        return {
            "provider": self.name,
            "configured": True,
            "mode": "local_test",
        }

    def ask(self, prompt: str) -> str:
        if not isinstance(prompt, str):
            raise TypeError("prompt должен быть строкой")

        self.calls.append(prompt)

        return (
            "MOCK_RESPONSE: "
            "AION execution path reached the provider successfully."
        )
