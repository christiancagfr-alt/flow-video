import unittest
from app.services.flow_accounts import (
    automatic_login_allowed, connection_summary, display_note, display_status, format_plan,
    account_rows, arrange_account_rows, interpret_credit_check, limit_tasks, login_failure_status, merge_seen,
    parse_account_rows, parse_account_text, plan_submission, plugin_account_report, row_ready, totp_code,
)


def account(email, credits=None, checked='2026-10-13', order=1, account_id=1, enabled=1):
    return {
        'id': account_id, 'email': email, 'enabled': enabled, 'sort_order': order,
        'credits_remaining': credits, 'credits_checked_at': checked, 'daily_quota': 50,
    }


class FlowAccountPlanTests(unittest.TestCase):
    def test_totp_matches_rfc6238(self):
        self.assertEqual(totp_code('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', timestamp=59), '287082')

    def test_sheet_rows_skip_header_and_bad_secret(self):
        parsed = parse_account_rows([
            ['邮箱', '密码', '二步验证'],
            ['a@example.com', 'secret-pass', 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'],
            ['c@example.com', 'only-password', ''],
            ['d@example.com', '', ''],
            ['bad', '', ''],
            ['b@example.com', 'pw', '123456'],
        ])
        self.assertEqual([item['email'] for item in parsed['accounts']], ['a@example.com', 'c@example.com', 'd@example.com'])
        self.assertEqual(len(parsed['skipped']), 2)

    def test_page_text_reads_email_and_credits(self):
        parsed = parse_account_text('Google Account: Ada (ada@gmail.com)\n剩余 42 积分')
        self.assertEqual(parsed['email'], 'ada@gmail.com')
        self.assertEqual(parsed['credits'], 42)
        card = parse_account_text('pierre louis\ncag1991pt@gmail.com\n50 个 Google Flow 点数\n点数每天10:39 刷新')
        self.assertEqual(card['email'], 'cag1991pt@gmail.com')
        self.assertEqual(card['credits'], 50)
        found = interpret_credit_check('a@example.com', '已登录', 'a@example.com', '50')
        self.assertIn('50', found['message'])
        self.assertIn('点数', found['message'])
        self.assertNotIn('积分', found['message'])
        missing = interpret_credit_check('a@example.com', '已登录', 'a@example.com', '')
        self.assertIn('0.9.67', missing['message'])
        self.assertIn('点数', missing['message'])

    def test_plan_uses_checked_balance_then_next_account(self):
        accounts = [
            account('a@example.com', 20, account_id=1),
            account('b@example.com', 50, account_id=2, order=2),
        ]
        plan = plan_submission(accounts, 6, 1, 10, '2026-10-13')
        self.assertEqual(plan['accounts_needed'], 2)
        self.assertEqual([item['videos'] for item in plan['assignments']], [2, 4])
        self.assertEqual(plan['shortfall'], 0)
        self.assertIn('a@example.com', format_plan(plan))

    def test_unchecked_account_estimates_daily_quota(self):
        plan = plan_submission([account('a@example.com', None, checked='')], 3, 1, 10, '2026-10-13')
        self.assertEqual(plan['assignments'][0]['generations'], 3)
        self.assertTrue(plan['assignments'][0]['estimated'])

    def test_no_accounts_leaves_submission_unchanged(self):
        decision = limit_tasks([], ['one', 'two'], 1, 10, today='2026-10-13')
        self.assertFalse(decision['apply'])
        self.assertEqual(decision['tasks'], ['one', 'two'])

    def test_current_page_account_stops_when_one_video_does_not_fit(self):
        accounts = [
            account('a@example.com', 8, account_id=1),
            account('b@example.com', 50, account_id=2, order=2),
        ]
        decision = limit_tasks(accounts, ['v1', 'v2'], 1, 10, observed_email='a@example.com', today='2026-10-13')
        self.assertTrue(decision['hold'])
        self.assertEqual(decision['tasks'], [])
        self.assertEqual(decision['switch_to'], 'b@example.com')

    def test_account_with_balance_only_receives_what_it_can_pay(self):
        accounts = [account('a@example.com', 25, account_id=1), account('b@example.com', 50, account_id=2, order=2)]
        decision = limit_tasks(accounts, ['v1', 'v2', 'v3', 'v4'], 1, 10, observed_email='a@example.com', today='2026-10-13')
        self.assertEqual(decision['tasks'], ['v1', 'v2'])
        self.assertEqual(decision['account_id'], 1)
        self.assertIn('需要 2 个账号', decision['message'])

    def test_login_in_progress_does_not_submit(self):
        accounts = [account('b@example.com', 50, account_id=2)]
        decision = limit_tasks(accounts, ['v1'], 1, 10, pending_action='login', pending_email='b@example.com', today='2026-10-13')
        self.assertTrue(decision['hold'])
        self.assertEqual(decision['tasks'], [])

    def test_unobserved_page_uses_first_affordable_account_without_login(self):
        accounts = [
            account('a@example.com', 8, account_id=1),
            account('b@example.com', 30, account_id=2, order=2),
        ]
        decision = limit_tasks(accounts, ['v1', 'v2', 'v3', 'v4'], 1, 10, today='2026-10-13')
        self.assertFalse(decision['hold'])
        self.assertEqual(decision['switch_to'], '')
        self.assertEqual(decision['account_id'], 2)
        self.assertEqual(decision['tasks'], ['v1', 'v2', 'v3'])

    def test_password_page_is_not_an_extra_verification_failure(self):
        self.assertEqual(login_failure_status('没有找到二步验证输入框'), '失败')
        self.assertEqual(login_failure_status('Google 弹出了额外确认。请在当前浏览器里完成'), '失败')

    def test_credit_check_clears_verification_and_keeps_page_credits(self):
        same = interpret_credit_check('a@example.com', '需要验证', 'a@example.com', '42')
        self.assertEqual(same['credits'], 42)
        self.assertEqual(same['status'], '已登录')
        missing = interpret_credit_check('a@example.com', '需要验证', '', '')
        self.assertIsNone(missing['credits'])
        self.assertEqual(missing['status'], '已登录')
        self.assertNotIn('需要验证', missing['message'])
        connected = interpret_credit_check('a@example.com', '未登录', 'a@example.com', '')
        self.assertEqual(connected['status'], '已登录')
        self.assertIn('每天 50', connected['message'])
        other = interpret_credit_check('a@example.com', '已登录', 'page@example.com', '')
        self.assertEqual(other['status'], '已登录')
        self.assertIn('还没就绪', other['message'])
        self.assertNotIn('需要验证', other['message'])

    def test_no_waiting_videos_does_not_mean_the_account_cannot_generate(self):
        plan = plan_submission([account('a@example.com', 50)], 0, 1, 10, '2026-10-13')
        text = format_plan(plan)
        self.assertIn('没有等待提交的视频', text)
        self.assertNotIn('没有还能生成的账号', text)

    def test_failed_login_is_not_retried_automatically(self):
        row = account('a@example.com')
        row.update(status='需要验证', last_error='Google 弹出了额外确认', last_attempt=1)
        self.assertFalse(automatic_login_allowed(row, 120))
        fresh = account('a@example.com')
        fresh.update(status='未登录', last_error='', last_attempt=0)
        self.assertTrue(automatic_login_allowed(fresh, 120))
        opened = account('a@example.com')
        opened.update(status='已登录', last_error='已打开 Chrome 用户 Profile 1 的 Flow', last_attempt=1)
        self.assertFalse(automatic_login_allowed(opened, 120))

    def test_only_the_page_email_is_ready(self):
        rows = [
            {'email': 'cagchristian.pt@gmail.com', 'status': '已登录', 'chrome_profile': 'Profile 1', 'last_error': '插件还没有连上'},
            {'email': 'sdzwbkgl@gmail.com', 'status': '已登录', 'chrome_profile': '', 'last_error': ''},
        ]
        seen = 'cag1991pt@gmail.com'
        self.assertFalse(row_ready(rows[0], seen))
        self.assertEqual(display_status(rows[0], seen), '未连接')
        self.assertEqual(display_status(rows[1], ''), '未连接')
        summary = connection_summary(rows, seen)
        self.assertIn(seen, summary)
        self.assertIn('灰色', summary)
        self.assertNotIn('已就绪', summary)
        ready = connection_summary(rows, 'sdzwbkgl@gmail.com')
        self.assertIn('已就绪：sdzwbkgl@gmail.com', ready)
        low = {'email': 'a@example.com', 'status': '积分不足', 'chrome_profile': 'Default', 'last_error': '插件还没有连上'}
        self.assertEqual(display_status(low, 'A@example.com'), '就绪（点数不足）')
        note = display_note(rows[0], seen, True)
        self.assertIn('当前页面是 cag1991pt@gmail.com', note)
        self.assertNotIn('插件还没有连上', note)
        self.assertIn('Chrome 用户 Profile 1', note)
        self.assertIn('点数不足', display_note(low, 'a@example.com', False))
        both = [
            {'email': 'a@example.com', 'status': '已登录', 'chrome_profile': '', 'last_error': ''},
            {'email': 'b@example.com', 'status': '已登录', 'chrome_profile': 'Profile 2', 'last_error': ''},
        ]
        pages = [{'email': 'a@example.com', 'credits': None, 'at': 1}, {'email': 'c@example.com', 'credits': 8, 'at': 1}]
        self.assertTrue(row_ready(both[0], pages))
        self.assertFalse(row_ready(both[1], pages))
        self.assertEqual(display_status(both[0], pages), '就绪')
        text = connection_summary(both, pages)
        self.assertIn('已就绪 1 个：a@example.com', text)
        self.assertIn('c@example.com', text)
        self.assertIn('灰色', text)
        self.assertIn('不是这一行', display_note(both[1], pages, True))
        kept = merge_seen(
            [{'email': 'a@example.com', 'credits': 3, 'at': 10}, {'email': 'old@example.com', 'credits': 1, 'at': 0}],
            'b@example.com', None, now=100, ttl=90,
        )
        self.assertEqual([item['email'] for item in kept], ['a@example.com', 'b@example.com'])
        self.assertEqual(kept[0]['credits'], 3)

    def test_logged_flow_rows_can_be_filtered_and_sorted(self):
        rows = [
            {'kind': 'chrome', 'name': '用户22', 'email': 'b@x.com', 'profile': {'state': '可打开 Flow'}, 'account': account('b@x.com', 10, account_id=2)},
            {'kind': 'chrome', 'name': '您的 Chrome', 'email': 'a@x.com', 'profile': {'state': '未登录'}, 'account': account('a@x.com', 50)},
            {'kind': 'chrome', 'name': '作图', 'email': 'c@x.com', 'profile': {'state': '已登录 Flow'}, 'account': None},
        ]
        seen = [{'email': 'a@x.com', 'credits': 50, 'at': 1}]
        shown, logged = arrange_account_rows(rows, seen, only_logged=True, sort_mode='points_desc', today='2026-10-13')
        self.assertEqual(logged, 2)
        self.assertEqual([row['name'] for row in shown], ['您的 Chrome', '作图'])
        ordered, _count = arrange_account_rows(rows, seen, only_logged=False, sort_mode='ready', today='2026-10-13')
        self.assertEqual([row['name'] for row in ordered], ['您的 Chrome', '作图', '用户22'])

    def test_channel_less_plugin_report_is_kept_and_sheet_rows_share_the_table(self):
        event = {
            'type': 'flow_account_seen', 'channel_id': 0, 'host_id': 0,
            'channel_key': 'account:sdzwbkgl@gmail.com', 'account_email': 'sdzwbkgl@gmail.com',
        }
        self.assertEqual(plugin_account_report(event), ('sdzwbkgl@gmail.com', None))
        self.assertIsNone(plugin_account_report({'type': 'web_plugin_heartbeat', 'channel_id': 0, 'host_id': 0}))
        profiles = [
            {'directory': 'Profile 1', 'name': '您的 Chrome', 'email': 'sdzwbkgl@gmail.com'},
            {'directory': 'Profile 2', 'name': '作图', 'email': 'other@gmail.com'},
        ]
        accounts = [
            {'id': 1, 'email': 'sdzwbkgl@gmail.com', 'chrome_profile': 'Profile 1', 'enabled': 1},
            {'id': 2, 'email': 'sheet@gmail.com', 'chrome_profile': '', 'enabled': 1},
        ]
        rows = account_rows(profiles, accounts)
        self.assertEqual([item['name'] for item in rows], ['您的 Chrome', '作图', '表格账号'])
        self.assertEqual(rows[2]['email'], 'sheet@gmail.com')
        self.assertEqual(rows[0]['account']['id'], 1)

    def test_unobserved_page_holds_when_no_account_can_pay(self):
        accounts = [account('a@example.com', 8, account_id=1), account('b@example.com', 5, account_id=2, order=2)]
        decision = limit_tasks(accounts, ['v1'], 1, 10, today='2026-10-13')
        self.assertTrue(decision['hold'])
        self.assertEqual(decision['tasks'], [])
        self.assertEqual(decision['switch_to'], '')


if __name__ == '__main__':
    unittest.main()
