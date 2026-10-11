import random

from ..mail import wait_for_code
from ..models import ActionType, Platform
from .base import BasePlatform, click_first, fill_first, try_click

WATCH_SECONDS = 35


class YouTubePlatform(BasePlatform):
    platform = Platform.youtube

    # ---------- פעולות ----------
    def perform(self, context, action, target_url, account, comment=None):
        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        if action == ActionType.view:
            page.wait_for_timeout(WATCH_SECONDS * 1000)
            return {"action": "view", "watched_seconds": WATCH_SECONDS}

        if action == ActionType.like:
            click_first(page, [
                "ytd-menu-renderer ytd-toggle-button-renderer:first-of-type button",
                'button[aria-label*="like this video" i]',
            ])
            page.wait_for_timeout(2500)
            return {"action": "like", "url": target_url}

        if action in (ActionType.subscribe, ActionType.follow):
            click_first(page, [
                "#subscribe-button button",
                'button[aria-label*="subscribe" i]',
            ])
            page.wait_for_timeout(2500)
            return {"action": "subscribe", "url": target_url}

        if action == ActionType.comment:
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(2500)
            box = page.locator("#simple-box, ytd-commentbox #contenteditable-root").first
            box.click()
            box.type(comment or "Great video!")
            click_first(page, ["#submit-button button"])
            page.wait_for_timeout(2500)
            return {"action": "comment", "text": comment}

        raise ValueError(f"פעולה לא נתמכת ב-YouTube: {action}")

    # ---------- יצירת חשבון Google ----------
    def create_account(self, context, account, mailbox):
        page = context.new_page()
        page.goto(
            "https://accounts.google.com/signup/v2/createaccount"
            "?flowName=GlifWebSignIn&flowEntry=SignUp",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(4000)

        # 1. שם
        fill_first(page, ['input[name="firstName"]'], "Social")
        fill_first(page, ['input[name="lastName"]'], "Boost")
        click_first(page, ['button:has-text("Next")', 'button:has-text("הבא")'])
        page.wait_for_timeout(3500)

        # 2. תאריך לידה ומין
        try_click(page, ['select#month'])
        page.select_option("select#month", str(random.randint(1, 12)))
        fill_first(page, ["input#day"], str(random.randint(1, 28)))
        fill_first(page, ["input#year"], str(random.randint(1990, 1999)))
        try:
            page.select_option("select#gender", "1")
        except Exception:
            pass
        click_first(page, ['button:has-text("Next")', 'button:has-text("הבא")'])
        page.wait_for_timeout(3500)

        # 3. שם משתמש -> "השתמש בכתובת הדוא\"ל הנוכחית"
        try_click(page, [
            'button:has-text("Use my current email address instead")',
            'div[role="button"]:has-text("Use my current email")',
        ])
        page.wait_for_timeout(2000)
        fill_first(page, ['input[name="Username"]', 'input[type="email"]'], account.email)
        click_first(page, ['button:has-text("Next")', 'button:has-text("הבא")'])
        page.wait_for_timeout(3500)

        # 4. סיסמה
        pw = _decrypt_pw(account)
        fill_first(page, ['input[name="Passwd"]'], pw)
        fill_first(page, ['input[name="ConfirmPasswd"]'], pw)
        click_first(page, ['button:has-text("Next")', 'button:has-text("הבא")'])
        page.wait_for_timeout(5000)

        # 5. קוד אימות מהדוא"ל (אם Google שולח)
        code = wait_for_code(mailbox, timeout=150)
        if code:
            try:
                fill_first(page, [
                    'input[name="code"]',
                    'input[type="text"][aria-label*="code" i]',
                    'input[type="tel"]',
                ], code)
                click_first(page, ['button:has-text("Next")', 'button:has-text("Verify")'])
                page.wait_for_timeout(4000)
            except Exception:
                pass

        # 6. מסך תנאים
        try_click(page, [
            'button:has-text("I agree")',
            'button:has-text("Confirm")',
            'button:has-text("מסכים")',
        ], timeout=12000)
        page.wait_for_timeout(4000)

        account.username = account.email.split("@")[0]
        account.status = "active"
        return {"created": True, "email": account.email}


def _decrypt_pw(account) -> str:
    from ..security import decrypt

    return decrypt(account.password) or "Sb!123456"
