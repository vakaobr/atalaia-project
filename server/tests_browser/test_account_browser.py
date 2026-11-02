# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The staff account page in a real browser (decisions ACC-*; headless Chromium, Playwright).

    python3 tools/docker_server.py browser tests_browser.test_account_browser

The same setup as ``test_login_browser`` (the real application under uvicorn over HTTPS, Google configured and a
fake provider in its place):

- passkeys: made on the page with a CDP virtual authenticator (user verification on, a resident key), renamed,
  removed; a wrong or missing password and the refusals in words (the last way to log in; a role that needs a second
  factor);
- Google: linked through the provider's redirect (the same fake as the login tests), the row, unlinking it;
- the password and TOTP: turned on with a code made from the secret the page shows, off again;
- an account with no password (made by a Google login): the confirmation after ten minutes, with the provider again;
- German at 375 px, and the page in all four languages.
"""

from __future__ import annotations

from playwright.async_api import Page, expect

from tests.base import PASSWORD
from tests_browser.test_login_browser import LoginBrowserCase

PAGE = "/staff/account"


class AccountCase(LoginBrowserCase):
    async def open_account(self, page: Page, name: str, secret: str | None = None) -> None:
        await self.login(page, name, secret, path=PAGE)
        await expect(page.locator("#confirm")).to_be_visible()

    async def add_passkey(self, page: Page, name: str, password: str | None = PASSWORD) -> None:
        if password is not None:
            await page.fill("#confirm-password", password)
        await page.fill("#passkey-name", name)
        await page.click("#passkey-add")

    async def step_up(self, page: Page, words: str = "Confirmed. Repeat the action.") -> None:
        """An account with a passkey changes its login methods only after a second factor (SR-1): the page says so
        and offers the passkey (the virtual authenticator answers it)."""
        await expect(page.locator("#confirm-stepup")).to_be_visible()
        await expect(page.locator("#confirm-recent-box")).to_be_visible()
        await expect(page.locator("#confirm-providers button")).to_have_count(0)  # a provider is no second factor
        await page.click("#confirm-passkey")
        await expect(page.locator("#status")).to_have_text(words)
        await expect(page.locator("#confirm-stepup")).to_be_hidden()


class PasskeyAccountTests(AccountCase):
    async def test_add_rename_and_remove_a_passkey(self) -> None:
        _, name, _ = await self.make_user()
        page = await self.new_page(lang="en-GB")
        await self.virtual_authenticator(page)
        await self.open_account(page, name)
        await expect(page.locator("#account-link")).to_have_attribute("aria-current", "page")
        await expect(page.locator("#passkeys-none")).to_be_visible()
        await expect(page.locator("#password-state")).to_have_text("This account has a password.")
        # No password typed: asked for, nothing sent.
        await page.fill("#passkey-name", "Laptop")
        await page.click("#passkey-add")
        await expect(page.locator("#status")).to_contain_text("ask for the current password")
        self.assertEqual((await self.fetch("SELECT count(*) FROM passkeys"))[0][0], 0)
        # A wrong one is the server's refusal.
        await self.add_passkey(page, "Laptop", "not-the-password")
        await expect(page.locator("#status")).to_have_text("Wrong password.")
        # The right one: the virtual authenticator makes the key.
        await self.add_passkey(page, "Laptop")
        await expect(page.locator("#status")).to_have_text("Passkey added.")
        row = page.locator("#passkeys li")
        await expect(row).to_have_count(1)
        await expect(row).to_contain_text("Laptop")
        await expect(row).to_contain_text("never used")
        self.assertEqual((await self.fetch("SELECT name FROM passkeys"))[0][0], "Laptop")
        # The account has a passkey now: renaming it asks for a second factor, in words, and the page offers it.
        await row.locator("button[data-act=rename]").click()
        await page.fill("#passkeys li input", "Phone")
        await page.click("#passkeys li button[type=submit]")
        await expect(page.locator("#status")).to_contain_text("asks for a second factor")
        await self.step_up(page)
        await page.locator("#passkeys li button[data-act=rename]").click()
        await page.fill("#passkeys li input", "Phone")
        await page.click("#passkeys li button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Name saved.")
        await expect(page.locator("#passkeys li")).to_contain_text("Phone")
        # Remove: the password is sent along.
        await page.fill("#confirm-password", PASSWORD)
        await page.locator("#passkeys li button[data-act=remove]").click()
        await expect(page.locator("#status")).to_have_text("Passkey removed.")
        await expect(page.locator("#passkeys-none")).to_be_visible()
        self.assertEqual((await self.fetch("SELECT count(*) FROM passkeys"))[0][0], 0)
        self.assertIn("Remove the passkey Phone?", self.dialogs)
        actions = [r["action"] for r in await self.fetch("SELECT action FROM audit_log ORDER BY id")]
        for wanted in ("passkey_add", "passkey_rename", "passkey_remove"):
            self.assertIn(wanted, actions)

    async def test_the_last_way_in_and_a_role_that_needs_a_second_factor(self) -> None:
        name, _ = await self.staff("gm", with_totp=False)
        page = await self.new_page(lang="en-GB")
        await self.virtual_authenticator(page)
        await self.open_account(page, name)
        # The password is the only way in: removing it is refused, in words.
        await page.fill("#confirm-password", PASSWORD)
        await page.click("#password-remove")
        await expect(page.locator("#status")).to_have_text(
            "That is the account's last way to log in: add another one first.")
        self.assertIsNotNone((await self.fetch("SELECT password_hash FROM users WHERE username = $1", name))[0][0])
        # A gm with no TOTP: the only passkey is the second factor, so it stays (the password is a way in, the
        # passkey the second factor the role needs).
        await self.add_passkey(page, "Key")
        await expect(page.locator("#passkeys li")).to_have_count(1)
        await self.step_up(page)
        await page.fill("#confirm-password", PASSWORD)
        await page.locator("#passkeys li button[data-act=remove]").click()
        await expect(page.locator("#status")).to_have_text(
            "A role on this account needs a second factor (TOTP or a passkey): keep at least one.")
        self.assertEqual((await self.fetch("SELECT count(*) FROM passkeys"))[0][0], 1)


class GoogleAccountTests(AccountCase):
    async def test_link_and_unlink_google(self) -> None:
        _, name, _ = await self.make_user()
        page = await self.new_page(lang="en-GB")
        await self.provider(page)
        await self.open_account(page, name)
        await expect(page.locator("#providers-none")).to_be_visible()
        link = page.locator("#link-buttons button[data-provider=google]")
        await expect(link).to_have_text("Link Google")
        await link.click()  # no password typed
        await expect(page.locator("#status")).to_contain_text("ask for the current password")
        await page.fill("#confirm-password", "wrong-password")
        await link.click()
        await expect(page.locator("#status")).to_have_text("Wrong password.")
        await page.fill("#confirm-password", PASSWORD)
        await link.click()
        await page.wait_for_url(f"{self.base}{PAGE}")  # back from the provider, the address cleaned
        await expect(page.locator("#status")).to_have_text("Login linked to the account.")
        await expect(page.locator("#providers li[data-provider=google]")).to_contain_text("Google")
        await expect(page.locator("#link-buttons button")).to_have_count(0)
        rows = await self.fetch("SELECT provider, subject FROM user_identities")
        self.assertEqual([(r["provider"], r["subject"]) for r in rows], [("google", self.subject)])
        _, other, _ = await self.make_user()
        second = await self.new_page(lang="en-GB")
        await self.provider(second)
        await self.open_account(second, other)
        await second.fill("#confirm-password", PASSWORD)
        await second.locator("#link-buttons button[data-provider=google]").click()
        await second.wait_for_url(f"{self.base}{PAGE}")
        # The same Google account for another account offers to merge (LG-11), and cancelling changes nothing.
        await expect(second.locator("#merge")).to_be_visible()
        await expect(second.locator("#merge-text")).to_contain_text("belongs to another account")
        await second.click("#merge-cancel")
        await expect(second.locator("#merge")).to_be_hidden()
        self.assertEqual((await self.fetch("SELECT count(*) FROM user_identities"))[0][0], 1)
        # Unlink it again.
        await page.fill("#confirm-password", PASSWORD)
        await page.locator("#providers li[data-provider=google] button[data-act=unlink]").click()
        await expect(page.locator("#status")).to_have_text("Login unlinked.")
        await expect(page.locator("#providers-none")).to_be_visible()
        self.assertEqual((await self.fetch("SELECT count(*) FROM user_identities"))[0][0], 0)

    async def test_a_social_account_chooses_and_changes_its_username(self) -> None:
        page = await self.new_page(lang="en-GB")
        await self.provider(page)
        await page.goto(self.base + "/staff/login?next=%2Fstaff%2Faccount")
        await page.check("#notice-seen")
        await page.check("#age-confirmed")
        await page.locator("button.provider").click()
        await page.wait_for_url("**/staff/account?*welcome=1*")
        await page.fill("#new-username", "Ana Silva")  # not a username: refused in words, nothing changes
        await page.click("#username-save")
        await expect(page.locator("#status")).to_contain_text("Invalid username")
        await page.fill("#new-username", "ana.silva")
        await page.click("#username-save")
        await page.wait_for_url(f"{self.base}{PAGE}")  # on to where the login was going
        self.assertEqual((await self.fetch("SELECT username FROM users"))[0][0], "ana.silva")
        await expect(page.locator("#username-current")).to_have_text("Current name: ana.silva")
        await page.fill("#new-username", "ana.costa")  # later, with no welcome step: the same section
        await page.click("#username-save")
        await expect(page.locator("#status")).to_have_text("Username saved.")
        self.assertEqual((await self.fetch("SELECT username FROM users"))[0][0], "ana.costa")

    async def test_an_account_with_no_password_confirms_with_the_provider(self) -> None:
        page = await self.new_page(lang="en-GB")
        await self.provider(page)
        await self.virtual_authenticator(page)
        await page.goto(self.base + "/staff/login?next=%2Fstaff%2Faccount")
        await page.check("#notice-seen")
        await page.check("#age-confirmed")
        await page.locator("button.provider").click()
        await page.wait_for_url("**/staff/account?*welcome=1*")  # a new account: the username step first
        await page.click("#username-skip")
        await page.wait_for_url(f"{self.base}{PAGE}")
        await expect(page.locator("#confirm-recent-box")).to_be_visible()
        await expect(page.locator("#confirm-password-box")).to_be_hidden()
        await expect(page.locator("#password-state")).to_have_text("This account has no password.")
        await expect(page.locator("#password-remove")).to_be_hidden()
        # The login just made counts as the confirmation: a passkey can be added at once.
        await self.add_passkey(page, "First", None)
        await expect(page.locator("#status")).to_have_text("Passkey added.")
        # It has a passkey now, so changing its login methods needs a second factor: the page says so and the
        # passkey gives it (a provider would not count).
        await self.step_up(page)
        # Ten minutes later the confirmation is gone: setting a password is refused in words, then the provider again.
        await self.fetch("UPDATE sessions SET confirmed_at = now() - interval '20 minutes'")
        await page.fill("#new-password", "a-long-enough-pass-phrase-7")
        await page.click("#password-save")
        await expect(page.locator("#status")).to_have_text(
            "Confirm it is you first (see the confirmation above), then repeat the action.")
        self.assertIsNone((await self.fetch("SELECT password_hash FROM users"))[0][0])
        await page.locator("#confirm-providers button[data-provider=google]").click()
        await page.wait_for_url(f"{self.base}{PAGE}")
        await expect(page.locator("#status")).to_have_text("Confirmed with the provider. Repeat the action.")
        await page.fill("#new-password", "a-long-enough-pass-phrase-7")
        await page.click("#password-save")
        await expect(page.locator("#status")).to_contain_text("Password saved")
        await expect(page.locator("#password-state")).to_have_text("This account has a password.")
        await expect(page.locator("#password-remove")).to_be_visible()
        await expect(page.locator("#confirm-password-box")).to_be_visible()  # from now on the password confirms
        # The passkey confirms too,.
        await page.fill("#confirm-password", "a-long-enough-pass-phrase-7")
        await page.click("#password-remove")
        await expect(page.locator("#status")).to_have_text("Password removed.")
        await self.fetch("UPDATE sessions SET confirmed_at = now() - interval '20 minutes'")
        await page.click("#confirm-passkey")
        await expect(page.locator("#status")).to_have_text("Confirmed. Repeat the action.")
        recent = (await self.fetch("SELECT confirmed_at > now() - interval '1 minute' FROM sessions"))[0][0]
        self.assertTrue(recent)


class TotpAccountTests(AccountCase):
    async def test_turn_totp_on_and_off(self) -> None:
        _, name, _ = await self.make_user()
        page = await self.new_page(lang="en-GB")
        await self.open_account(page, name)
        await expect(page.locator("#totp-state")).to_have_text("TOTP is not on for this account.")
        await page.fill("#confirm-password", PASSWORD)
        await page.click("#totp-enable")
        await expect(page.locator("#totp-confirm-form")).to_be_visible()
        secret = (await page.locator("#totp-secret").text_content() or "").strip()
        self.assertGreaterEqual(len(secret), 16)
        await expect(page.locator("#totp-uri")).to_contain_text("otpauth://totp/")
        await page.fill("#totp-enrol-code", "000000")
        await page.click("#totp-confirm-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Wrong code.")
        await page.fill("#totp-enrol-code", self.code(secret))
        await page.click("#totp-confirm-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("TOTP turned on.")
        await expect(page.locator("#totp-state")).to_have_text("TOTP is on for this account.")
        self.assertTrue((await self.fetch("SELECT totp_enabled FROM users WHERE username = $1", name))[0][0])
        await page.fill("#confirm-password", PASSWORD)
        await page.fill("#totp-disable-code", self.code(secret))
        await page.click("#totp-disable-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("TOTP turned off.")
        await expect(page.locator("#totp-enable")).to_be_visible()
        self.assertFalse((await self.fetch("SELECT totp_enabled FROM users WHERE username = $1", name))[0][0])

    async def test_a_role_keeps_its_second_factor(self) -> None:
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.open_account(page, name, secret)
        await page.fill("#confirm-password", PASSWORD)
        await page.fill("#totp-disable-code", self.code(secret or ""))
        await page.click("#totp-disable-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text(
            "A role on this account needs a second factor: add a passkey before turning TOTP off.")
        self.assertTrue((await self.fetch("SELECT totp_enabled FROM users WHERE username = $1", name))[0][0])


class PasswordAccountTests(AccountCase):
    async def test_change_the_password_and_the_refusals(self) -> None:
        _, name, _ = await self.make_user()
        page = await self.new_page(lang="en-GB")
        await self.open_account(page, name)
        await page.fill("#confirm-password", PASSWORD)
        await page.fill("#new-password", "short")
        await page.click("#password-save")
        await expect(page.locator("#status")).to_have_text("The password is too short.")
        await page.fill("#new-password", "another-long-pass-phrase-9")
        await page.click("#password-save")
        await expect(page.locator("#status")).to_contain_text("Password saved")
        r = await self.client.post("/api/v1/auth/login", json={"username": name,
                                                              "password": "another-long-pass-phrase-9"})
        self.assertEqual(r.status_code, 200)


class AccountLanguageTests(AccountCase):
    async def test_german_at_375_px_and_the_other_languages(self) -> None:
        _, name, _ = await self.make_user()
        page = await self.new_page(lang="de-DE")
        await self.virtual_authenticator(page)
        await self.provider(page)
        await self.open_account(page, name)
        await self.add_passkey(page, "Mein sehr langer Passkey-Name für das Büro im ersten Stock")
        await expect(page.locator("#status")).to_have_text("Passkey hinzugefügt.")
        await expect(page.locator("#confirm-stepup")).to_contain_text("zweiten Faktor")
        await self.check_page(page, 375)
        await self.step_up(page, "Bestätigt. Wiederhole die Aktion.")
        await page.fill("#confirm-password", PASSWORD)
        await page.locator("#link-buttons button[data-provider=google]").click()
        await page.wait_for_url(f"{self.base}{PAGE}")
        await expect(page.locator("#status")).to_have_text("Login mit dem Konto verknüpft.")
        await expect(page.locator("h1")).to_have_text("Mein Konto")
        await expect(page.locator("#account-link")).to_have_text("Konto")
        await self.check_page(page, 375)
        # A refusal in German, then the layout again.
        await page.fill("#confirm-password", "falsch")
        await page.locator("#providers li[data-provider=google] button[data-act=unlink]").click()
        await expect(page.locator("#status")).to_have_text("Falsches Passwort.")
        await self.check_page(page, 375)
        for lang, title in (("pt-PT", "A minha conta"), ("en-GB", "My account"), ("zh-TW", "我的帳號")):
            with self.subTest(lang=lang):
                other = await self.new_page(lang=lang)
                await self.open_account(other, name)
                await expect(other.locator("h1")).to_have_text(title)
                await self.check_page(other, 375)
