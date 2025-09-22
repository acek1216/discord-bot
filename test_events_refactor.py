# -*- coding: utf-8 -*-
"""
events.py リファクタリング後のテスト
"""

import sys
import os

# プロジェクトルートをパスに追加
sys.path.append(os.path.dirname(__file__))

def test_syntax():
    """構文チェック"""
    try:
        import ast
        with open('cogs/events.py', 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        print("OK: events.py 構文チェック正常")
        return True
    except SyntaxError as e:
        print(f"ERROR: 構文エラー: {e}")
        return False
    except Exception as e:
        print(f"ERROR: エラー: {e}")
        return False

def test_channel_mapping():
    """チャンネルマッピングのテスト"""
    try:
        from cogs.events import EventCog
        import discord
        from discord.ext import commands

        # モックbotを作成
        bot = commands.Bot(command_prefix='!', intents=discord.Intents.default())
        cog = EventCog(bot)

        # テストケース
        test_cases = [
            ("gemini1.5pro-test", "gemini_1_5_pro"),
            ("gemini-1-5-pro-channel", "gemini_1_5_pro"),
            ("gpt4o-chat", "gpt4o"),
            ("gpt-general", "gpt5"),
            ("gemini-room", "gemini"),
            ("claude-test", "claude"),
            ("mistral-ai", "mistral"),
            ("grok-chat", "grok"),
            ("llama-test", "llama"),
            ("ラマ-room", "llama"),
            ("o1-pro-chat", "o1_pro"),
            ("o1-test", "o1_pro"),
            ("genius-room", "genius"),
            ("unknown-channel", None)
        ]

        all_passed = True
        for channel_name, expected in test_cases:
            result = cog._match_channel_to_ai_type(channel_name)
            if result == expected:
                print(f"OK: '{channel_name}' -> '{result}'")
            else:
                print(f"FAIL: '{channel_name}' -> expected '{expected}', got '{result}'")
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"ERROR: チャンネルマッピングテスト失敗: {e}")
        return False

def test_imports():
    """インポートテスト"""
    try:
        from cogs.events import EventCog
        print("OK: EventCog インポート正常")
        return True
    except Exception as e:
        print(f"ERROR: インポートエラー: {e}")
        return False

def main():
    """メインテスト実行"""
    print("=" * 50)
    print("events.py リファクタリングテスト開始")
    print("=" * 50)

    tests = [
        ("構文チェック", test_syntax),
        ("インポートテスト", test_imports),
        ("チャンネルマッピングテスト", test_channel_mapping)
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        result = test_func()
        results.append(result)

    print("\n" + "=" * 50)
    print("テスト結果サマリー")
    print("=" * 50)

    passed = sum(results)
    total = len(results)

    for i, (test_name, _) in enumerate(tests):
        status = "PASS" if results[i] else "FAIL"
        print(f"{test_name}: {status}")

    print(f"\n総合結果: {passed}/{total} テスト通過")

    if passed == total:
        print("✓ 全てのテストが成功しました！")
        print("Priority 1: events.py リファクタリング完了")
    else:
        print("✗ 一部テストが失敗しました")

    return passed == total

if __name__ == "__main__":
    main()