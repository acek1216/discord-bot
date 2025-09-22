# -*- coding: utf-8 -*-
"""
state.py のバックアップ（統一メモリシステムへの移行前）
"""

# --- メモリ管理 ---
# 各AIの基本モード用の短期記憶
gpt_base_memory = {}
gemini_base_memory = {}
mistral_base_memory = {}
claude_base_memory = {}
llama_base_memory = {}
grok_base_memory = {}

# 各スレッド専用の長期記憶
gpt_thread_memory = {}
gemini_thread_memory = {}
perplexity_thread_memory = {}

# --- 状態管理 ---
# 現在処理中のチャンネルIDを管理するセット
processing_channels = set()

print("⚠️ これは旧state.pyのバックアップファイルです。実際の使用には enhanced_memory_manager を使用してください。")