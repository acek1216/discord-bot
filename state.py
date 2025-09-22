# state.py - 統一メモリシステムへの移行完了
# このファイルの変数は enhanced_memory_manager.py に統合されました

# 後方互換性のためのインポートリダイレクト
try:
    from enhanced_memory_manager import get_enhanced_memory_manager

    def __getattr__(name: str):
        """動的属性アクセス - 統一メモリシステムにリダイレクト"""
        memory_manager = get_enhanced_memory_manager()

        # メモリ変数のリダイレクト
        if name.endswith('_base_memory'):
            ai_type = name.replace('_base_memory', '')
            return memory_manager.get_legacy_memory(ai_type, "base")

        elif name.endswith('_thread_memory'):
            ai_type = name.replace('_thread_memory', '')
            return memory_manager.get_legacy_memory(ai_type, "thread")

        # processing_channelsのリダイレクト
        elif name == 'processing_channels':
            return memory_manager.get_processing_channels()

        # 存在しない属性
        raise AttributeError(f"module 'state' has no attribute '{name}'")

    print("✅ state.py: 統一メモリシステムへの移行完了")
    print("ℹ️ 従来のメモリ変数は enhanced_memory_manager で管理されます")

except ImportError:
    # フォールバック: 従来の変数を保持
    print("⚠️ enhanced_memory_manager が見つかりません。従来システムで動作します。")

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

# 依存関係を維持するためのダミー変数（使用非推奨）
# これらは既存コードのインポートエラーを防ぐためのみ
if 'gpt_base_memory' not in locals():
    gpt_base_memory = {}
    gemini_base_memory = {}
    mistral_base_memory = {}
    claude_base_memory = {}
    llama_base_memory = {}
    grok_base_memory = {}
    gpt_thread_memory = {}
    gemini_thread_memory = {}
    perplexity_thread_memory = {}
    processing_channels = set()