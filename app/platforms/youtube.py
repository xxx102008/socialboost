import random

from ..mail import wait_for_code
from ..models import AccountStatus, ActionType, Platform
from ..security import decrypt
from .base import BasePlatform, StepError, click_first, fill_first, run_step, try_click

WATCH_SECONDS = 32
SIGNUP_URL = (
    "https://accounts.google.com/signup/v2/createaccount"
    "?flowName=GlifWebSignIn&flowEntry=SignUp"
)

LIKE_JS = """
() => {
  const sels = [
    'ytd-reel-video-renderer #like-button button',
    '#like-button button',
    'ytd-menu-renderer ytd-toggle-button-renderer:first-of-type button',
    'ytd-segmented-like-dislike-button-renderer button:first-of-type',
    'button[aria-label*="like this video" i]',
    'button[aria-label^="like" i]'
  ];
  for (const s of sels) {
    const el = document.querySelector(s);
    if (el) {
      if (el.getAttribute('aria-pressed') === 'true') return 'already:' + s;
      el.click();
      return 'clicked:' + s;
    }
  }
  return null;
}
"""

SUB_JS = """
() => {
  const sels = [
    '#subscribe-button button',
    'ytd-subscribe-button-renderer button',
    'button[aria-label*="subscribe" i]'
  ];
  for (const s of sels) {
    const el = document.querySelector(s);
    if (el) {
      const label = (el.getAttribute('aria-label') || '').toLowerCase();
      if (label.includes('subscribed') || label.startsWith('unsubscribe')) {
        return 'already:' + s;
      }
      el.click();
      return 'clicked:' + s;
    }
  }
  return null;
}
"""


class YouTubePlatform(BasePlatform):
    platform = Platform.youtube

    def _do(self, page, name: str, fn):
        return run_step(page, name, fn)

    def perform(self, context, action, target_url, account, comment=None):
        page = context.new_page()
        self._do(page, "open", lambda: page.goto(target_url, wait_until="domcontentloaded"))
        self._do(page, "initial-wait", lambda: page.wait_for_timeout(6000))

        if not self._logged_in(page):
            raise StepError(
                f"[step=login] url={page.url} :: החשבון {account.email} לא מחובר ליוטיוב"
            )

        if action == ActionType.view:
            self._do(page, "view", lambda: page.wait_for_timeout(WATCH_SECONDS * 1000))
            return {"action": "view", "watched_seconds": WATCH_SECONDS}

        if action == ActionType.like:
            self._do(page, "like-scroll", lambda: page.mouse.wheel(0, 500))
            self._do(page, "like-wait", lambda: page.wait_for_timeout(1500))
            result = self._do(page, "like", lambda: page.evaluate(LIKE_JS))
            if result is None:
                raise StepError(f"[step=like] url={page.url} :: לא נמצא כפתור לייק")
            self._do(page, "like-result-wait", lambda: page.wait_for_timeout(2000))
            return {"action": "like", "result": result}

        if action in (ActionType.subscribe, ActionType.follow):
            self._do(page, "subscribe-scroll", lambda: page.mouse.wheel(0, 400))
            self._do(page, "subscribe-wait", lambda: page.wait_for_timeout(1500))
            result = self._do(page, "subscribe", lambda: page.evaluate(SUB_JS))
            if result is None:
                raise StepError(f"[step=subscribe] url={page.url} :: לא נמצא כפתור מנוי")
            self._do(page, "subscribe-result-wait", lambda: page.wait_for_timeout(2000))
            return {"action": "subscribe", "result": result}

        if action == ActionType.comment:
            self._do(page, "comment-scroll", lambda: page.mouse.wheel(0, 1500))
            self._do(page, "comment-wait", lambda: page.wait_for_timeout(2500))
            box = page.locator("#simple-box, ytd-commentbox #contenteditable-root").first
            self._do(page, "comment-box", lambda: box.click())
            self._do(page, "comment-text", lambda: box.type(comment or "Great video!"))
            self._do(page, "comment-submit", lambda: click_first(page, ["#submit-button button"]))
            self._do(page, "comment-result-wait", lambda: page.wait_for_timeout(2500))
            return {"action": "comment", "text": comment}

        raise StepError(f"[step=perform] url={page.url} :: פעולה לא נתמכת: {action}")

    def _logged_in(self, page) -> bool:
        try:
            page.locator("button#avatar-btn, #avatar-btn").first.wait_for(
                state="visible", timeout=8000
            )
            return True
        except Exception:
            return False

    def create_account(self, context, account, mailbox):
        page = context.new_page()
        self._do(page, "open", lambda: page.goto(SIGNUP_URL, wait_until="domcontentloaded"))
        self._do(page, "open-wait", lambda: page.wait_for_timeout(4000))

        def name_step():
            fill_first(page, ['input[name="firstName"]'], "Social")
            fill_first(page, ['input[name="lastName"]'], "Boost")
            click_first(page, ['button:has-text("Next")', 'button:has-text("הבא")'])

        self._do(page, "name", name_step)
        self._do(page, "name-wait", lambda: page.wait_for_timeout(3500))

        def birthday_step():
            try:
                page.select_option("select#month", str(random.randint(1, 12)))
            except Exception:
                pass
            fill_first(page, ["input#day"], str(random.randint(1, 28)))
            fill_first(page, ["input#year"], str(random.randint(1990, 1999)))
            try:
                page.select_option("select#gender", "1")
            except Exception:
                pass
            click_first(page, ['button:has-text("Next")', 'button:has-text("הבא")'])

        self._do(page, "birthday", birthday_step)
        self._do(page, "birthday-wait", lambda: page.wait_for_timeout(3500))

        def username_step():
            try_click(
                page,
                [
                    'button:has-text("Use my current email address instead")',
                    'div[role="button"]:has-text("Use my current email")',
                ],
                timeout=6000,
            )
            fill_first(page, ['input[name="Username"]', 'input[type="email"]'], account.email)
            click_first(page, ['button:has-text("Next")', 'button:has-text("הבא")'])

        self._do(page, "username", username_step)
        self._do(page, "username-wait", lambda: page.wait_for_timeout(3500))

        def password_step():
            password = _decrypt_pw(account)
            fill_first(page, ['input[name="Passwd"]'], password)
            fill_first(page, ['input[name="ConfirmPasswd"]'], password)
            click_first(page, ['button:has-text("Next")', 'button:has-text("הבא")'])

        self._do(page, "password", password_step)
        self._do(page, "password-wait", lambda: page.wait_for_timeout(5000))

        def email_verification_step():
            code = wait_for_code(mailbox, timeout=150)
            if not code:
                return
            fill_first(
                page,
                [
                    'input[name="code"]',
                    'input[type="text"][aria-label*="code" i]',
                    'input[type="tel"]',
                ],
                code,
            )
            click_first(page, ['button:has-text("Next")', 'button:has-text("Verify")'])

        self._do(page, "email-verification", email_verification_step)
        self._do(page, "verification-wait", lambda: page.wait_for_timeout(4000))

        def terms_step():
            try_click(
                page,
                [
                    'button:has-text("I agree")',
                    'button:has-text("Confirm")',
                    'button:has-text("מסכים")',
                ],
                timeout=12000,
            )

        self._do(page, "terms", terms_step)
        self._do(page, "terms-wait", lambda: page.wait_for_timeout(4000))
        account.username = account.email.split("@")[0]
        account.status = AccountStatus.active
        return {"created": True, "email": account.email}


def _decrypt_pw(account) -> str:
    return decrypt(account.password) or "Sb!123456"
