import re

import pytest

from app.vk.auth import PlaywrightTokenProvider


class Candidate:
    def __init__(self, text: str):
        self.text = text
        self.clicks = 0

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self, **_kwargs):
        self.clicks += 1


class Locator:
    def __init__(self, candidates):
        self.candidates = candidates

    async def count(self):
        return len(self.candidates)

    def nth(self, index):
        return self.candidates[index]

    @property
    def first(self):
        return self.candidates[0]


class Page:
    def __init__(self, labels):
        self.labels = labels

    def _matching(self, name):
        matched = []
        for label in self.labels:
            if hasattr(name, "search"):
                if name.search(label):
                    matched.append(Candidate(label))
            elif name == label:
                matched.append(Candidate(label))
        return Locator(matched)

    def get_by_role(self, _role, name=None, **_kwargs):
        return self._matching(name)

    def get_by_text(self, name, **_kwargs):
        return self._matching(name)


@pytest.mark.asyncio
async def test_plain_continue_is_not_treated_as_continue_as_oauth_action():
    provider = PlaywrightTokenProvider()
    action = await provider._find_visible_vk_auth_action(Page(["Продолжить"]))
    assert action is None


@pytest.mark.asyncio
async def test_plain_continue_gate_matches_only_exact_continue_not_continue_as():
    provider = PlaywrightTokenProvider()
    plain = await provider._find_visible_plain_continue(Page(["Продолжить", "Продолжить как Сергей"]))
    assert plain is not None
    assert plain.text == "Продолжить"


@pytest.mark.asyncio
async def test_continue_as_remains_a_terminal_oauth_action():
    provider = PlaywrightTokenProvider()
    action = await provider._find_visible_vk_auth_action(Page(["Продолжить как Сергей"]))
    assert action is not None
    assert action.text == "Продолжить как Сергей"
